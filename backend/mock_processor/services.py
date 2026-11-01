import secrets

from django.conf import settings
from django.db import transaction

from . import webhooks
from .models import Charge, PaymentMethodToken
from .validators import (
    TokenizationError,
    detect_brand,
    digits_only,
    expiry_valid,
    luhn_valid,
)


def tokenize(data):
    method = data.get("method")
    if method == "card":
        return _tokenize_card(data)
    if method == "bank":
        return _tokenize_bank(data)
    raise TokenizationError("invalid_method", "method must be 'card' or 'bank'.")


def _tokenize_card(data):
    number = digits_only(data.get("number"))
    if not number.isdigit() or not 12 <= len(number) <= 19 or not luhn_valid(number):
        raise TokenizationError("invalid_number", "Card number is invalid.")

    try:
        month = int(data.get("exp_month"))
        year = int(data.get("exp_year"))
    except (TypeError, ValueError):
        raise TokenizationError("invalid_expiry", "exp_month and exp_year are required.")
    if year < 100:
        year += 2000
    if not 1 <= month <= 12 or not expiry_valid(month, year):
        raise TokenizationError("invalid_expiry", "Card expiry is invalid or in the past.")

    cvv = digits_only(data.get("cvv"))
    if not cvv.isdigit() or len(cvv) not in (3, 4):
        raise TokenizationError("invalid_cvv", "CVV must be 3 or 4 digits.")

    return PaymentMethodToken.objects.create(
        token=_new_token(),
        method=PaymentMethodToken.Method.CARD,
        last4=number[-4:],
        brand_or_bank_type=detect_brand(number),
    )


def _tokenize_bank(data):
    account_number = digits_only(data.get("account_number"))
    routing_number = digits_only(data.get("routing_number"))
    account_type = data.get("account_type", "checking")

    if not routing_number.isdigit() or len(routing_number) != 9:
        raise TokenizationError("invalid_routing_number", "Routing number must be exactly 9 digits.")
    if not account_number.isdigit() or not 4 <= len(account_number) <= 17:
        raise TokenizationError("invalid_account_number", "Account number must be 4 to 17 digits.")
    if account_type not in ("checking", "savings"):
        raise TokenizationError("invalid_account_type", "account_type must be 'checking' or 'savings'.")

    return PaymentMethodToken.objects.create(
        token=_new_token(),
        method=PaymentMethodToken.Method.BANK,
        last4=account_number[-4:],
        brand_or_bank_type=account_type,
    )


def _new_token():
    return f"tok_{secrets.token_hex(12)}"

class ChargeError(Exception):
    """Raised when the processor cannot accept a charge request."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def decide_outcome(method, last4):
    """Return (final_status, failure_code, settle_delay_seconds) from the brief's test table."""
    if last4 == "0002":
        failure = "card_declined" if method == "card" else "insufficient_funds"
        return "failed", failure, 0
    if last4 == "0119":
        return "failed", "processor_error", 0
    if last4 == "0341":
        return "succeeded", None, 15
    return "succeeded", None, 0


def charge(token, amount, currency):
    try:
        payment_method = PaymentMethodToken.objects.get(token=token)
    except PaymentMethodToken.DoesNotExist:
        raise ChargeError("invalid_token", "Unknown payment token.")

    final_status, failure_code, delay = decide_outcome(payment_method.method, payment_method.last4)

    new_charge = Charge.objects.create(
        processor_reference=f"pr_{secrets.token_hex(12)}",
        payment_method=payment_method,
        amount=amount,
        currency=currency,
        final_status=final_status,
        failure_code=failure_code,
        settle_delay_seconds=delay,
        pending_event_id=webhooks.new_event_id(),
        final_event_id=webhooks.new_event_id(),
    )

    if getattr(settings, "PROCESSOR_AUTO_DELIVER_WEBHOOKS", True):
        # Send the result only after the caller's transaction commits, so the
        # webhook can never arrive before the payment exists.
        reference = new_charge.processor_reference
        transaction.on_commit(lambda: webhooks.schedule_automatic_delivery(reference))

    return {"processor_reference": new_charge.processor_reference}
