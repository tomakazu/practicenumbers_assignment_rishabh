import secrets

from .models import PaymentMethodToken
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
