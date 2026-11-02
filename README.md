# Payments Service: Idempotent Payment Ledger

A small payments service built on Vinta's Django React Boilerplate. It has
two Django apps:

- **`mock_processor`** stands in for an external processor such as Stripe or
  Adyen: it tokenizes card/bank details, accepts charges and sends signed
  webhooks (including messy deliveries).
- **`payments`** is the service itself: an idempotent payments API, a signed
  webhook endpoint and an append-only ledger from which every payment's
  status is derived.

---

## Setup (Docker Compose)

Requirements: Docker Desktop, `make`, Git.

```bash
git clone <this repo> && cd <repo>
cp backend/.env.example backend/.env
cp backend/payments_service/settings/local.py.example backend/payments_service/settings/local.py
# edit backend/.env: uncomment the Docker DATABASE_URL line and set
# PROCESSOR_WEBHOOK_SECRET to any long random string
make docker_setup
make docker_up
docker compose exec backend python manage.py migrate
```

The app runs at http://localhost:8000.

## Run the full test suite

```bash
docker compose exec backend python manage.py test mock_processor payments
```

## Try it

**Demo page:** http://localhost:8000/demo. Pick a test card, pay, and watch
the status move from `pending` to its final state. The page lists every
payment, its append-only ledger, and the webhook events received with what
the service did with each one. It also has buttons for idempotent retries
and the four messy-delivery modes.

**Messy delivery from the command line:**

```bash
docker compose exec backend python manage.py simulate_webhooks --reference <pr_...> --mode normal|duplicate|reverse|concurrent
```

To see the modes act on a payment that is still pending, set
`PROCESSOR_AUTO_DELIVER_WEBHOOKS=false` in `backend/.env` and restart the
backend. Results then arrive only through `simulate_webhooks`. Card `...0341`
also stays pending for 15 seconds with automatic delivery on.

**Test values:** `4242 4242 4242 4242` succeeds; numbers ending `0002`
(declined / insufficient funds), `0119` (processor error) and `0341`
(pending 15 s, then success) follow the brief's table. Luhn-valid examples:
`4000000000000002`, `4000000000000119`, `4000000000000341`.

---

## Design notes

### State rules

A payment moves `pending → succeeded` or `pending → failed`; `succeeded` and
`failed` are final.

| Current | Incoming event | Result |
|---|---|---|
| pending | succeeded / failed | ledger entry written (`applied`) |
| pending | pending | nothing written (`no_change`) |
| final | same final status, new event | nothing written (`no_change`) |
| final | pending (late or reordered) | ignored (`late_pending`), status does not regress |
| final | the other final status | ignored (`conflict`), logged as a warning |

**Conflicting final events: the first final status wins.** Once a payment is
`succeeded` or `failed`, money has moved (or definitely has not) and the
patient may already have been shown that result. Flipping it silently would
make the history dishonest. A real reversal (a refund or chargeback) should
be a new, explicit ledger event rather than an edit. The conflicting event
is still stored in `WebhookEvent` with outcome `conflict` and logged as a
warning, so an operator can investigate it.

### Append-only ledger

`Payment` has **no status column**: its status is always the status of its
latest `LedgerEntry`. Every state change appends one entry, and entries are
never changed or removed. This is enforced in two layers:

1. **Model:** `LedgerEntry.save()` refuses existing rows and `delete()` always
   raises, which stops normal application code.
2. **Database:** a Postgres trigger (`BEFORE UPDATE OR DELETE ... FOR EACH
   ROW`) raises an exception, which also blocks bulk queryset updates/deletes
   and raw SQL that bypass model methods.

`TRUNCATE` is not blocked because Django's `TransactionTestCase` uses it
between tests. In production I would also revoke `UPDATE`, `DELETE` and
`TRUNCATE` on the ledger table from the application's database role.
Payments cannot be deleted while they have ledger entries (`PROTECT`).

### Idempotent payment creation

`POST /api/payments` requires an `Idempotency-Key` header. The validated
body is reduced to a SHA-256 fingerprint and stored with the key and the
exact response that was returned.

- **Same key, same body:** the stored original response is returned (HTTP
  201 with `Idempotent-Replayed: true`). Nothing is created and nothing is
  charged again. As with Stripe, this is the *original* response; the
  current status comes from `GET /api/payments/{id}`.
- **Same key, different body:** rejected with HTTP 422 `idempotency_key_reused`.
- **Concurrent requests with one key:** `Payment.idempotency_key` has a
  unique index. Creating the payment, charging, writing the first ledger
  entry and storing the response happen in one transaction. A concurrent
  insert with the same key waits on the index until the first commits, then
  fails with `IntegrityError`; the code catches it and replays the first
  response. The database, not timing, guarantees one payment per key.
- If the processor rejects the token, the transaction rolls back and the
  key is not stored, so the client may retry.

### Webhooks: each event processed at most once, safely under races

`POST /webhooks/processor` first verifies `X-Processor-Signature` (hex
HMAC-SHA256 of the raw body with `PROCESSOR_WEBHOOK_SECRET`, compared in
constant time). Missing or invalid signatures get HTTP 401 and change
nothing; with no secret configured, every delivery is rejected (fail closed).

Each valid event is applied in one transaction:

1. **`SELECT ... FOR UPDATE` on the payment row.** Deliveries for the same
   payment are serialized: a second copy waits until the first commits.
   Locking the payment (not the event) also protects the state rules when
   *different* events race, e.g. `succeeded` and `failed` at once.
2. **Look up `event_id` in `WebhookEvent`.** If it was seen, the delivery is a
   duplicate and is acknowledged without changes.
3. **Apply the state rules,** append a `LedgerEntry` if the status changes, and
   record the event in `WebhookEvent` with its outcome.

**Backstops:** `WebhookEvent.event_id` and `LedgerEntry.event_id` are unique
in the database, so even if the application logic were bypassed, a second
ledger entry for the same event cannot be written.

Every accepted event, including ignored ones, gets HTTP 200, so the
processor does not keep retrying events that have already been handled.
Unknown references get 404.

### Processor boundary

The payments app reaches the processor only through
`payments/processor_client.py`, which calls the processor's public `charge()`
in-process (allowed by the brief) and converts its errors into the payments
app's own `ProcessorError`. Payments code never imports processor models or
reads processor tables, so switching to a real HTTP processor changes only
that module. Card and bank details go from the client straight to
`/processor/tokenize`; the payments API accepts only a token and rejects
unknown fields, so card fields sent by mistake get a 400 and are never used.

### What I would change at 10x volume

- **Queue webhook work.** Verify the signature, store the raw event, return
  200 at once, and apply it in a worker (Celery/SQS). Send outgoing events
  through an outbox table instead of in-process threads, so nothing is lost
  on restart.
- **Cache the current status.** Add a status column on `Payment`, updated in
  the same transaction as each ledger insert. The ledger stays the source
  of truth, but list pages no longer read the ledger per payment.
- **Scope and expire idempotency keys.** Make keys unique per practice
  (`unique(practice_id, key)`) and expire them after a retention window.
- **Grow the database.** Partition the ledger and webhook tables by month, add
  PgBouncer for connection pooling, and use a read replica for
  `GET` endpoints.
- **Watch the edge cases.** Add metrics and alerts for conflicts, late
  events, signature failures and payments stuck in `pending`.

Row locks are per payment, so contention stays low as volume grows; the
unique constraints keep their guarantees at any scale.

---

## Assumptions

- **Authentication** is out of scope; the payments endpoints are open. In
  production they would require practice-level auth.
- **Tokenize request format.** The brief names the inputs, not the fields:

  ```json
  {"method": "card", "number": "4242 4242 4242 4242", "exp_month": 12, "exp_year": 2030, "cvv": "123"}
  {"method": "bank", "account_number": "000123456789", "routing_number": "110000000", "account_type": "checking"}
  ```

  Spaces and dashes are ignored, a 2-digit `exp_year` means 20xx, and a card
  is valid through the end of its expiry month. Card numbers must be 12–19
  digits and pass Luhn, CVV must be 3–4 digits, routing numbers exactly 9
  digits, and account numbers 4–17 digits. Errors return 400
  `{"error": "<code>", "message": "..."}` with codes `invalid_number`,
  `invalid_expiry`, `invalid_cvv`, `invalid_routing_number`,
  `invalid_account_number`, `invalid_account_type` or `invalid_method`.
- **`brand_or_bank_type`** holds the card network (`visa`, `mastercard`,
  `amex`, `discover`, `unknown`) for cards, and the account type for bank
  accounts. The brief does not define bank types, so `account_type` is
  `checking` (default) or `savings`, the two standard US ACH types.
- **The processor stores only last4.** The full number and CVV are validated
  in memory and discarded; neither app stores or logs them. last4 is enough
  because the brief decides every outcome from the last 4 digits.
- **Payment IDs are UUIDs,** so other patients' payments cannot be guessed
  by trying `/api/payments/41`, `/42`, and so on, and IDs do not reveal volume.
- **Amounts** are positive integer cents; **currency** must be `USD`.
- **Status codes:** 400 for invalid input, a bad Idempotency-Key header or an
  unknown token; 422 for a reused key with a different body.
- **Events per charge.** Each charge has two events (`pending` and the final
  one) whose `event_id`s are fixed at charge time. Every delivery, retry or
  simulation reuses them, as a real processor retries the same event.
- **Automatic delivery** after each charge runs in background threads
  (pending at once, final after 2 s, or 15 s for `0341`), started only after
  the charge's transaction commits. That is enough for a mock; production
  would use a durable queue (see above).
- **`POST /processor/simulate`** is a test helper for the demo page that
  runs the same delivery modes as the `simulate_webhooks` command.
- **Demo page.** The optional read-only React page was replaced by a small
  server-rendered page with plain JavaScript (`/demo`), which also acts as
  the client that calls the processor directly. It shows masked processor
  references only.

## Setup notes (changes to the boilerplate)

- **Postgres pinned to `postgres:17-alpine`.** The unpinned `postgres:alpine`
  image now resolves to Postgres 18, whose new data-directory layout is
  incompatible with the boilerplate's volume mount, so the database exits on
  start.
- **After changing `backend/.env`,** run
  `docker compose up -d --force-recreate backend`. A plain `restart` keeps
  the old environment values.
- **`users` migrations generated during bootstrap,** as the boilerplate's
  README instructs (it ships the `users` app without a migration).
