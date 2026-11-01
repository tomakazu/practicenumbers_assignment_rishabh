from django.db import DatabaseError, transaction
from django.test import TestCase

from payments.models import AppendOnlyError, LedgerEntry, Payment

from .helpers import create_payment, test_settings, tokenize_card


@test_settings
class AppendOnlyLedgerTests(TestCase):
    def setUp(self):
        token = tokenize_card(self.client)
        self.payment = Payment.objects.get(id=create_payment(self.client, token).json()["id"])
        self.entry = self.payment.ledger_entries.get()

    def test_model_refuses_update_and_delete(self):
        self.entry.status = "failed"
        with self.assertRaises(AppendOnlyError):
            self.entry.save()
        with self.assertRaises(AppendOnlyError):
            self.entry.delete()

    def test_database_refuses_bulk_update(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            LedgerEntry.objects.filter(pk=self.entry.pk).update(status="failed")
        self.assertEqual(LedgerEntry.objects.get(pk=self.entry.pk).status, "pending")

    def test_database_refuses_bulk_delete(self):
        with self.assertRaises(DatabaseError), transaction.atomic():
            LedgerEntry.objects.filter(pk=self.entry.pk).delete()
        self.assertTrue(LedgerEntry.objects.filter(pk=self.entry.pk).exists())
