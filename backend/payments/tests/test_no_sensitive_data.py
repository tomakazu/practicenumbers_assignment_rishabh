import logging
import re

from django.db import connection
from django.test import TestCase

from payments.models import Payment

from .helpers import create_payment, make_event, post_webhook, test_settings

CARD_NUMBER = "4242424242424242"
CVV = "987"
ACCOUNT_NUMBER = "000123456789"

# Loggers that may not pass messages up to the root logger in some setups.
WATCHED_LOGGERS = ["", "django", "django.request", "django.db.backends", "payments", "mock_processor"]


class CaptureAllLogs(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.messages = []

    def emit(self, record):
        self.messages.append(self.format(record))


def every_row_as_text():
    """Every row of every table in the database, as text (not just our own models)."""
    rows = []
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names(cursor):
            cursor.execute(f'SELECT t::text FROM "{table}" AS t')
            rows.extend(row[0] for row in cursor.fetchall())
    return rows


@test_settings
class NoSensitiveDataTests(TestCase):
    def setUp(self):
        self.capture = CaptureAllLogs()
        self.saved_levels = {}
        for name in WATCHED_LOGGERS:
            logger = logging.getLogger(name)
            self.saved_levels[name] = logger.level
            logger.addHandler(self.capture)
            logger.setLevel(logging.DEBUG)
        # Also log every SQL statement, so the check covers the queries too.
        connection.force_debug_cursor = True

    def tearDown(self):
        connection.force_debug_cursor = False
        for name, level in self.saved_levels.items():
            logger = logging.getLogger(name)
            logger.removeHandler(self.capture)
            logger.setLevel(level)

    def pay_and_settle(self, details):
        token_response = self.client.post("/processor/tokenize", details, content_type="application/json")
        self.assertEqual(token_response.status_code, 201)
        payment_id = create_payment(self.client, token_response.json()["token"]).json()["id"]
        reference = Payment.objects.get(id=payment_id).processor_reference
        post_webhook(make_event(reference, "pending"))
        post_webhook(make_event(reference, "succeeded"))
        self.assertEqual(self.client.get(f"/api/payments/{payment_id}").json()["status"], "succeeded")
        self.client.get("/api/payments")

    def test_full_card_flow_stores_and_logs_no_card_number_or_cvv(self):
        self.pay_and_settle(
            {"method": "card", "number": CARD_NUMBER, "exp_month": 12, "exp_year": 2030, "cvv": CVV}
        )
        rows = every_row_as_text()
        logs = self.capture.messages
        self.assertTrue(rows)
        self.assertTrue(any("INSERT" in m for m in logs), "SQL statements should be captured")

        self.assertEqual([r for r in rows if CARD_NUMBER in r], [])
        self.assertEqual([r for r in rows if re.search(rf"[(,]{CVV}[,)]", r)], [])  # CVV as a column value
        self.assertEqual([m for m in logs if CARD_NUMBER in m or "cvv" in m.lower()], [])

    def test_full_bank_flow_stores_and_logs_no_account_number(self):
        self.pay_and_settle(
            {"method": "bank", "account_number": ACCOUNT_NUMBER, "routing_number": "110000000"}
        )
        self.assertEqual([r for r in every_row_as_text() if ACCOUNT_NUMBER in r], [])
        self.assertEqual([m for m in self.capture.messages if ACCOUNT_NUMBER in m], [])
