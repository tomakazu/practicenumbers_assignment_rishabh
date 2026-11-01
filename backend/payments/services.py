import hashlib
import json
import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from . import processor_client
from .models import TERMINAL_STATUSES, LedgerEntry, Payment, PaymentStatus, WebhookEvent
from .serializers import payment_to_dict

logger = logging.getLogger(__name__)


# ------------------------------------------------------ creating a payment


class IdempotencyConflict(Exception):
    """The Idempotency-Key was already used with a different request body."""


@dataclass
class CreateResult:
    body: dict
    status_code: int
    replayed: bool


def create_payment(idempotency_key, data):
    fingerprint = _fingerprint(data)

    existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
    if existing is not None:
        return _replay(existing, fingerprint)

    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                idempotency_key=idempotency_key,
                request_hash=fingerprint,
                amount=data["amount"],
                currency=data["currency"],
                payment_token=data["payment_token"],
            )
            payment.processor_reference = processor_client.charge(
                payment.payment_token, payment.amount, payment.currency
            )
            LedgerEntry.objects.create(payment=payment, status=PaymentStatus.PENDING)
            payment.response_body = payment_to_dict(payment)
            payment.save(update_fields=["processor_reference", "response_body"])
    except IntegrityError:
        # Another request with the same key won the race and committed first.
        existing = Payment.objects.get(idempotency_key=idempotency_key)
        return _replay(existing, fingerprint)

    return CreateResult(body=payment.response_body, status_code=201, replayed=False)


def _replay(payment, fingerprint):
    if payment.request_hash != fingerprint:
        raise IdempotencyConflict()
    return CreateResult(body=payment.response_body, status_code=201, replayed=True)


def _fingerprint(data):
    canonical = json.dumps(dict(data), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ------------------------------------------------ processor webhook events


class UnknownPayment(Exception):
    pass


DUPLICATE = "duplicate"


def apply_processor_event(event):
    """Apply one verified webhook event. Safe under duplicates, reordering and concurrency.

    Returns the outcome: "applied", "no_change", "late_pending", "conflict"
    or "duplicate".
    """
    try:
        with transaction.atomic():
            # Lock this payment's row. A second delivery for the same payment
            # waits here until the first one commits, so events for one
            # payment are handled one at a time.
            try:
                payment = Payment.objects.select_for_update().get(
                    processor_reference=event["processor_reference"]
                )
            except Payment.DoesNotExist:
                raise UnknownPayment()

            if WebhookEvent.objects.filter(event_id=event["event_id"]).exists():
                outcome = DUPLICATE
            else:
                outcome = decide_outcome(payment.current_status(), event["status"])
                if outcome == WebhookEvent.Outcome.APPLIED:
                    LedgerEntry.objects.create(
                        payment=payment,
                        status=event["status"],
                        failure_code=event.get("failure_code"),
                        event_id=event["event_id"],
                        occurred_at=event["occurred_at"],
                    )
                WebhookEvent.objects.create(
                    event_id=event["event_id"],
                    payment=payment,
                    status=event["status"],
                    failure_code=event.get("failure_code"),
                    occurred_at=event["occurred_at"],
                    outcome=outcome,
                )
    except IntegrityError:
        # Backstop: the unique event_id constraints refused a second copy.
        outcome = DUPLICATE

    log = logger.warning if outcome == WebhookEvent.Outcome.CONFLICT else logger.info
    log("Webhook %s (%s) for payment reference %s: %s",
        event["event_id"], event["status"], event["processor_reference"], outcome)
    return outcome


def decide_outcome(current_status, new_status):
    """The state rules: pending -> succeeded | failed, and final states never change."""
    if current_status in TERMINAL_STATUSES:
        if new_status == current_status:
            return WebhookEvent.Outcome.NO_CHANGE
        if new_status == PaymentStatus.PENDING:
            return WebhookEvent.Outcome.LATE_PENDING
        return WebhookEvent.Outcome.CONFLICT  # first final status wins
    if new_status == current_status:
        return WebhookEvent.Outcome.NO_CHANGE
    return WebhookEvent.Outcome.APPLIED
