import uuid

from django.db import models


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


TERMINAL_STATUSES = {PaymentStatus.SUCCEEDED, PaymentStatus.FAILED}


class Payment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="USD")
    payment_token = models.CharField(max_length=64)
    processor_reference = models.CharField(max_length=64, unique=True, null=True, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def current_status(self):
        last_entry = self.ledger_entries.order_by("-id").first()
        return last_entry.status if last_entry else None

    def __str__(self):
        return f"Payment {self.id} ({self.amount} {self.currency})"


class AppendOnlyError(Exception):
    pass


class LedgerEntry(models.Model):
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    status = models.CharField(max_length=10, choices=PaymentStatus.choices)
    failure_code = models.CharField(max_length=32, null=True, blank=True)
    event_id = models.CharField(max_length=64, unique=True, null=True, blank=True)
    occurred_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("Ledger entries cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("Ledger entries cannot be deleted.")

    def __str__(self):
        return f"{self.payment_id}: {self.status}"
