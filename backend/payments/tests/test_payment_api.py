from django.test import TestCase

from payments.models import LedgerEntry, Payment

from .helpers import create_payment, test_settings, tokenize_card


@test_settings
class CreatePaymentIdempotencyTests(TestCase):
    def setUp(self):
        self.token = tokenize_card(self.client)

    def test_same_key_same_body_returns_the_original_payment(self):
        first = create_payment(self.client, self.token, key="key-1")
        second = create_payment(self.client, self.token, key="key-1")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(second.headers["Idempotent-Replayed"], "true")
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(LedgerEntry.objects.count(), 1)

    def test_same_key_different_body_is_rejected(self):
        create_payment(self.client, self.token, amount=5000, key="key-1")
        response = create_payment(self.client, self.token, amount=9999, key="key-1")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"], "idempotency_key_reused")
        self.assertEqual(Payment.objects.count(), 1)

    def test_new_payment_starts_pending_with_one_ledger_entry(self):
        response = create_payment(self.client, self.token)
        payment = Payment.objects.get(id=response.json()["id"])

        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual(payment.current_status(), "pending")
        self.assertTrue(payment.processor_reference.startswith("pr_"))

    def test_missing_idempotency_key_is_rejected(self):
        response = self.client.post(
            "/api/payments",
            {"amount": 5000, "currency": "USD", "payment_token": self.token},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)

    def test_card_fields_are_refused_by_the_payments_api(self):
        response = self.client.post(
            "/api/payments",
            {"amount": 5000, "currency": "USD", "payment_token": self.token, "number": "4242424242424242"},
            content_type="application/json",
            headers={"Idempotency-Key": "key-x"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)

    def test_unknown_token_creates_nothing(self):
        response = create_payment(self.client, "tok_does_not_exist")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_token")
        self.assertEqual(Payment.objects.count(), 0)

    def test_get_payment_returns_status_and_ledger(self):
        payment_id = create_payment(self.client, self.token).json()["id"]
        response = self.client.get(f"/api/payments/{payment_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pending")
        self.assertEqual([e["status"] for e in response.json()["ledger"]], ["pending"])
