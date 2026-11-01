from django.db import models

class PaymentMethodToken(models.Model):
    class Method(models.TextChoices):
        CARD = "card", "Card"
        BANK = "bank", "Bank account"

    token = models.CharField(max_length=40, unique=True)
    method = models.CharField(max_length=4, choices=Method.choices)
    last4 = models.CharField(max_length=4)
    brand_or_bank_type = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.token} ({self.method} ****{self.last4})"


class Charge(models.Model):
    processor_reference = models.CharField(max_length=40, unique=True)
    payment_method = models.ForeignKey(
        PaymentMethodToken, on_delete=models.PROTECT, related_name="charges"
    )
    amount = models.PositiveIntegerField()
    currency = models.CharField(max_length=3)
    final_status = models.CharField(max_length=10)
    failure_code = models.CharField(max_length=32, null=True, blank=True)
    settle_delay_seconds = models.PositiveIntegerField(default=0)
    # Each charge has exactly two events. Every delivery (automatic or
    # simulated, first try or retry) reuses these IDs, like a real processor
    # retrying the same event.
    pending_event_id = models.CharField(max_length=40, blank=True, default="")
    final_event_id = models.CharField(max_length=40, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.processor_reference} -> {self.final_status}"
