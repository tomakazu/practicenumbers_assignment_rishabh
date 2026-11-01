import json

from django.test import TestCase

from payments.models import LedgerEntry, Payment, WebhookEvent

from .helpers import create_payment, make_event, post_webhook, sign, test_settings, tokenize_card


@test_settings
class WebhookTests(TestCase):
    def setUp(self):
        token = tokenize_card(self.client)
        self.payment = Payment.objects.get(id=create_payment(self.client, token).json()["id"])
        self.reference = self.payment.processor_reference

    def statuses(self):
        return list(self.payment.ledger_entries.values_list("status", flat=True))

    def test_duplicate_event_writes_exactly_one_ledger_entry(self):
        event = make_event(self.reference, "succeeded")

        first = post_webhook(event)
        second = post_webhook(event)

        self.assertEqual(first.json()["outcome"], "applied")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["outcome"], "duplicate")
        self.assertEqual(LedgerEntry.objects.filter(event_id=event["event_id"]).count(), 1)
        self.assertEqual(self.statuses(), ["pending", "succeeded"])

    def test_reverse_order_ends_in_the_final_status(self):
        final = make_event(self.reference, "failed", failure_code="card_declined")
        pending = make_event(self.reference, "pending")

        post_webhook(final)
        late = post_webhook(pending)

        self.assertEqual(late.json()["outcome"], "late_pending")
        self.assertEqual(self.payment.current_status(), "failed")
        self.assertEqual(self.statuses(), ["pending", "failed"])

    def test_normal_order(self):
        post_webhook(make_event(self.reference, "pending"))
        post_webhook(make_event(self.reference, "succeeded"))

        self.assertEqual(self.payment.current_status(), "succeeded")
        self.assertEqual(self.statuses(), ["pending", "succeeded"])

    def test_conflicting_final_event_is_recorded_but_does_not_change_status(self):
        post_webhook(make_event(self.reference, "succeeded"))
        conflict = post_webhook(make_event(self.reference, "failed", failure_code="processor_error"))

        self.assertEqual(conflict.json()["outcome"], "conflict")
        self.assertEqual(self.payment.current_status(), "succeeded")
        self.assertEqual(self.statuses(), ["pending", "succeeded"])
        self.assertTrue(WebhookEvent.objects.filter(outcome="conflict").exists())

    def test_invalid_signature_is_rejected_and_changes_nothing(self):
        response = post_webhook(make_event(self.reference, "succeeded"), signature="0" * 64)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.statuses(), ["pending"])
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_missing_signature_is_rejected_and_changes_nothing(self):
        response = post_webhook(make_event(self.reference, "succeeded"), signature="missing")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.statuses(), ["pending"])
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_signature_for_a_different_body_is_rejected(self):
        real = make_event(self.reference, "failed", failure_code="card_declined")
        forged_signature = sign(json.dumps(make_event(self.reference, "succeeded")).encode())
        response = post_webhook(real, signature=forged_signature)

        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.statuses(), ["pending"])

    def test_unknown_reference_returns_404(self):
        response = post_webhook(make_event("pr_unknown", "succeeded"))
        self.assertEqual(response.status_code, 404)
