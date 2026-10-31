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
