"""How the mock processor builds, signs and sends webhook events.

Every charge has two events: "pending" and the final one ("succeeded" or
"failed"). Their event IDs are fixed when the charge is created, so any
retry or duplicate delivery carries the same event_id, as with a real
processor.
"""
import hashlib
import hmac
import json
import logging
import secrets
import threading
import urllib.error
import urllib.request
from datetime import timedelta, timezone

from django.conf import settings

from .models import Charge

logger = logging.getLogger(__name__)

MODES = ("normal", "duplicate", "reverse", "concurrent")


class UnknownCharge(Exception):
    pass


def new_event_id():
    return f"evt_{secrets.token_hex(12)}"


def _iso(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_events(charge):
    """Return (pending_event, final_event) as plain dictionaries."""
    pending = {
        "event_id": charge.pending_event_id,
        "processor_reference": charge.processor_reference,
        "status": "pending",
        "failure_code": None,
        "occurred_at": _iso(charge.created_at),
    }
    final = {
        "event_id": charge.final_event_id,
        "processor_reference": charge.processor_reference,
        "status": charge.final_status,
        "failure_code": charge.failure_code,
        "occurred_at": _iso(charge.created_at + timedelta(seconds=charge.settle_delay_seconds)),
    }
    return pending, final


def sign(body):
    """Hex HMAC-SHA256 of the raw body bytes, keyed with PROCESSOR_WEBHOOK_SECRET."""
    secret = settings.PROCESSOR_WEBHOOK_SECRET.encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def deliver(event):
    """POST one signed event to the merchant's webhook URL. Returns the HTTP status (or None)."""
    body = json.dumps(event, separators=(",", ":")).encode()
    request = urllib.request.Request(
        settings.PROCESSOR_WEBHOOK_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "X-Processor-Signature": sign(body)},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
    except urllib.error.HTTPError as error:
        status = error.code
    except urllib.error.URLError as error:
        logger.warning("Webhook %s could not be delivered: %s", event["event_id"], error.reason)
        return None
    logger.info("Webhook %s (%s) delivered: HTTP %s", event["event_id"], event["status"], status)
    return status


def _load_events(reference):
    try:
        charge = Charge.objects.get(processor_reference=reference)
    except Charge.DoesNotExist:
        raise UnknownCharge(reference)
    return charge, build_events(charge)


def schedule_automatic_delivery(reference):
    """Normal delivery after a charge: pending right away, final after the settle delay."""
    charge, (pending, final) = _load_events(reference)
    final_delay = max(charge.settle_delay_seconds, 2)
    for delay, event in ((0.5, pending), (final_delay, final)):
        timer = threading.Timer(delay, deliver, args=[event])
        timer.daemon = True
        timer.start()


def deliver_with_mode(reference, mode):
    """Send this charge's events using one of the messy-delivery modes and wait.

    Returns a list of (event_id, status, http_status) in the order sent.
    """
    events = _events_for_mode(reference, mode)
    return _send(events, mode)


def deliver_with_mode_in_background(reference, mode):
    """Same as deliver_with_mode, but returns at once and sends from a background thread.

    Used by the demo page: the web server must be free to receive the
    webhooks it is sending to itself.
    """
    events = _events_for_mode(reference, mode)
    thread = threading.Thread(target=_send, args=(events, mode), daemon=True)
    thread.start()


def _events_for_mode(reference, mode):
    if mode not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    _, (pending, final) = _load_events(reference)
    return {
        "normal": [pending, final],
        "duplicate": [pending, pending, final, final],
        "reverse": [final, pending],
        "concurrent": [final, final],
    }[mode]


def _send(events, mode):
    if mode == "concurrent":
        return _deliver_at_same_moment(events)
    return [(event["event_id"], event["status"], deliver(event)) for event in events]


def _deliver_at_same_moment(events):
    barrier = threading.Barrier(len(events))
    results = [None] * len(events)

    def send(index, event):
        barrier.wait()  # every thread waits here, then all fire together
        results[index] = (event["event_id"], event["status"], deliver(event))

    threads = [threading.Thread(target=send, args=(i, e)) for i, e in enumerate(events)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results
