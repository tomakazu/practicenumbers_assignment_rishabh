import hashlib
import hmac

from django.conf import settings


def signature_is_valid(raw_body, received_signature):
    """Check X-Processor-Signature: hex HMAC-SHA256 of the raw body with the shared secret."""
    secret = settings.PROCESSOR_WEBHOOK_SECRET
    if not secret or not received_signature:
        return False  # fail closed: no secret configured or no signature sent
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    # compare_digest takes the same time whether the first or last character
    # differs, so an attacker cannot guess the signature byte by byte.
    return hmac.compare_digest(expected, received_signature.strip())
