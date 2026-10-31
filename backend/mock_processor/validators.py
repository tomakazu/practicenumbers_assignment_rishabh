import re
from datetime import date


class TokenizationError(Exception):
    """Raised when card or bank details fail validation."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def digits_only(value):
    """Remove spaces and dashes: '4242 4242-4242 4242' -> '4242424242424242'."""
    return re.sub(r"[\s-]", "", str(value or ""))


def luhn_valid(number):
    total = 0
    for position, char in enumerate(reversed(number)):
        digit = int(char)
        if position % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def detect_brand(number):
    if number.startswith("4"):
        return "visa"
    if number[:2] in ("34", "37"):
        return "amex"
    if 51 <= int(number[:2]) <= 55 or 2221 <= int(number[:4]) <= 2720:
        return "mastercard"
    if number.startswith(("6011", "65")):
        return "discover"
    return "unknown"


def expiry_valid(month, year, today=None):
    """A card is valid through the last day of its expiry month."""
    today = today or date.today()
    return (year, month) >= (today.year, today.month)
