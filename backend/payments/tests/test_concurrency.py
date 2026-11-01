import threading

from django.db import connection
from django.test import Client, TransactionTestCase

from payments import services
from payments.models import LedgerEntry, Payment, WebhookEvent

from .helpers import create_payment, make_event, post_webhook, test_settings, tokenize_card


def run_at_the_same_moment(func, count=2):
    """Run func in `count` threads, released together. Each thread uses its own DB connection."""
    barrier = threading.Barrier(count)
    results, errors = [None] * count, []

    def worker(index):
        try:
            barrier.wait()
            results[index] = func()
        except Exception as error:  # surface thread errors in the test
            errors.append(error)
        finally:
            connection.close()  # Django gives each thread its own connection

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise errors[0]
    return results


@test_settings
class ConcurrentDeliveryTests(TransactionTestCase):
    """Real commits on separate database connections (no wrapping test transaction)."""

    def test_two_concurrent_copies_of_the_final_event_write_one_entry(self):
        token = tokenize_card(Client())
        payment = Payment.objects.get(id=create_payment(Client(), token).json()["id"])
        event = make_event(payment.processor_reference, "succeeded")

        responses = run_at_the_same_moment(lambda: post_webhook(event, client=Client()))

        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(sorted(r.json()["outcome"] for r in responses), ["applied", "duplicate"])
        self.assertEqual(LedgerEntry.objects.filter(event_id=event["event_id"]).count(), 1)
        self.assertEqual(WebhookEvent.objects.filter(event_id=event["event_id"]).count(), 1)
        self.assertEqual(payment.current_status(), "succeeded")
        self.assertEqual(payment.ledger_entries.count(), 2)

    def test_two_concurrent_creates_with_the_same_key_make_one_payment(self):
        token = tokenize_card(Client())
        data = {"amount": 5000, "currency": "USD", "payment_token": token}

        results = run_at_the_same_moment(lambda: services.create_payment("same-key", data))

        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(results[0].body["id"], results[1].body["id"])
        self.assertEqual(sorted(r.replayed for r in results), [False, True])
