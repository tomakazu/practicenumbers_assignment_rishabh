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
    request_hash = models.CharField(max_length=64, default="")
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def current_status(self):
        """The status is always read from the ledger: the latest entry wins."""
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


class WebhookEvent(models.Model):
    """Every processor event we accepted, with what we did about it.

    The unique event_id is how we process each event at most once. Events
    that did not change the payment (late "pending", conflicting final
    status) are still recorded here, so nothing the processor told us is lost.
    """

    class Outcome(models.TextChoices):
        APPLIED = "applied", "Applied: wrote a ledger entry"
        NO_CHANGE = "no_change", "Ignored: payment already in this status"
        LATE_PENDING = "late_pending", "Ignored: pending after a final status"
        CONFLICT = "conflict", "Ignored: conflicts with an earlier final status"

    event_id = models.CharField(max_length=64, unique=True)
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="webhook_events")
    status = models.CharField(max_length=10, choices=PaymentStatus.choices)
    failure_code = models.CharField(max_length=32, null=True, blank=True)
    occurred_at = models.DateTimeField()
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.event_id}: {self.status} ({self.outcome})"
