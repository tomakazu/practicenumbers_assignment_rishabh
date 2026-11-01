import hashlib
import hmac
import json
import uuid

from django.test import Client, override_settings

WEBHOOK_SECRET = "test-webhook-secret"
GOOD_CARD = "4242424242424242"

# Every test runs with a known secret and without automatic webhook delivery,
# so tests decide exactly which events arrive and in what order.
test_settings = override_settings(
    PROCESSOR_WEBHOOK_SECRET=WEBHOOK_SECRET,
    PROCESSOR_AUTO_DELIVER_WEBHOOKS=False,
)


def tokenize_card(client, number=GOOD_CARD, cvv="123"):
    response = client.post(
        "/processor/tokenize",
        {"method": "card", "number": number, "exp_month": 12, "exp_year": 2030, "cvv": cvv},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    return response.json()["token"]


def create_payment(client, token, amount=5000, key=None):
    return client.post(
        "/api/payments",
        {"amount": amount, "currency": "USD", "payment_token": token},
        content_type="application/json",
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )


def make_event(reference, status, event_id=None, failure_code=None):
    return {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:24]}",
        "processor_reference": reference,
        "status": status,
        "failure_code": failure_code,
        "occurred_at": "2026-09-28T10:15:02.113Z",
    }


def sign(body):
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def post_webhook(event, client=None, signature="valid"):
    """Send a webhook like the processor would. signature: 'valid', 'missing' or any wrong string."""
    client = client or Client()
    body = json.dumps(event).encode()
    headers = {}
    if signature == "valid":
        headers["X-Processor-Signature"] = sign(body)
    elif signature != "missing":
        headers["X-Processor-Signature"] = signature
    return client.post("/webhooks/processor", body, content_type="application/json", headers=headers)
