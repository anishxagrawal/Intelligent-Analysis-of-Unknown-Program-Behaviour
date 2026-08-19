# Stage 1 — Implementation Reference

**Input and Submission, as built.** This document is the single place to
understand what exists in the repository today: every module, every tool and why
it was chosen, the data model, the decisions that shaped the code, and the
limitations that survive. It is written for someone picking the project up cold
— including the author, six months from now.

| | |
|---|---|
| Status | Complete. All 25 numbered acceptance criteria green |
| Versions | v0 through v5, six commits |
| Code | ~4,200 lines across `app/` and `worker/` |
| Tests | ~4,300 lines, 332 tests, 95% coverage against a 90% gate |
| Last updated | 2026-08-19, at commit `c904961` |

### Where this fits among the other documents

| Document | Answers |
|---|---|
| [`docs/Project-Report.md`](Project-Report.md) | What the whole eight-stage system is for, and the research it comes from |
| [`VERSIONS.md`](../VERSIONS.md) | What gets built in what order, and why that order |
| [`ACCEPTANCE.md`](../ACCEPTANCE.md) | The numbered criteria, their tests, and every known limitation |
| [`README.md`](../README.md) | How to install, configure and run it |
| **This document** | What the code actually is, and why it is shaped that way |

---

## 1. What Stage 1 does

Stage 1 accepts a file from a machine caller, stores it safely, works out what
kind of container it is, and hands off a job for something else to analyse.

```
POST /api/v1/submissions
  -> authenticate the key, check its scope, check its rate limit
  -> stream the upload to a staging file, hashing as it goes, capped mid-stream
  -> identify the container format from the first 512 bytes
  -> deduplicate on SHA-256; store the bytes encrypted under their own digest
  -> create a job, stamp it with provenance, queue it
  -> 202 Accepted

python -m worker
  -> claim one queued job atomically, lease it, mark it running
  -> (Stage 2 would take it from here)

the reaper, running inside the API process
  -> return jobs whose leases lapsed; cancel the ones out of attempts
```

### The boundary this stage protects

**Stage 1 performs no analysis and forms no opinion about a file.** It accepts
bytes, stores them safely, identifies the container format, and hands off a job.
There is no `clean`, no `malicious`, no score anywhere in the code. If Stage 1
ever starts reasoning about whether something is dangerous, a boundary has
leaked.

The one place this was hardest to hold was the stub worker. It would have been
easy to have it mark jobs `finished` with an outcome, which would have made
every downstream test green. It records nothing instead, because all five run
outcomes are statements about a run that has not happened. See section 7.

---

## 2. Tools, and why each one

Every dependency here is justified by something the project needs. The list is
deliberately short: each addition is a thing that can break, a thing to keep
updated, and a thing the next reader has to learn.

### Runtime

| Tool | Version | Why this one |
|---|---|---|
| **Python** | 3.11 | `StrEnum`, `datetime.UTC` and the exception groups used by async code all arrive in 3.11. Nothing here needs 3.12. |
| **FastAPI** | 0.141 | Dependency injection that made scoped authentication one decorator per route, and an OpenAPI schema generated from the code rather than maintained beside it. AC-13 asserts against that generated schema. |
| **Starlette** | 1.6 | Comes with FastAPI. Used directly for the request-id middleware and for `UploadFile`, whose streaming `read()` is what keeps memory flat. |
| **Uvicorn** | 0.52 | ASGI server. Nothing exotic asked of it. |
| **SQLAlchemy** | 2.0 (asyncio) | The 2.0 typed ORM lets `mypy --strict` check model attributes, and the Core layer gives direct access to `FOR UPDATE SKIP LOCKED` and `ON CONFLICT DO NOTHING`, both of which the queue and intake depend on. An ORM that hid the SQL would have been the wrong choice for exactly those two statements. |
| **asyncpg** | 0.31 | The fast async PostgreSQL driver. Chosen with one known risk — its history with Windows' Proactor event loop — which was flagged in the v1 plan and never materialised. |
| **PostgreSQL** | 18 | Not incidental. `SELECT ... FOR UPDATE SKIP LOCKED` is the whole basis of the job queue, native enums enforce the state vocabulary at the schema level, and `ON CONFLICT DO NOTHING` resolves the duplicate-submission race. See 2.1. |
| **Pydantic** | 2.13 | Request and response models kept separate from the ORM, so a database change cannot silently alter what clients receive. |
| **pydantic-settings** | 2.15 | Environment configuration with validation. Two validators refuse to start in production with a development encryption key or a bootstrap API key. |
| **python-multipart** | 0.0.32 | Multipart parsing. It also, usefully, reduces a Windows absolute filename to its base name before the application sees it — discovered in v1, recorded because it matters to the path-safety tests. |
| **cryptography** | 50.0 | AES-256-GCM. Both the one-shot `AESGCM` interface and the lower-level `Cipher` used for the streaming path. Never a hand-rolled construction. |
| **Alembic** | 1.19 | Migrations, replacing `create_all` in v3. |

### Development

| Tool | Version | Why |
|---|---|---|
| **pytest** | 9.1 | Four markers — `unit`, `contract`, `integration`, `acceptance` — so `pytest -m acceptance` answers "is this version done" directly. |
| **pytest-asyncio** | 1.4 | `asyncio_mode = "auto"`, so async tests need no decorator. Session-scoped event loop for the throwaway-database fixture. |
| **pytest-cov** | 7.1 | The 90% gate, configured as `fail_under` in `pyproject.toml` so it applies to any coverage run. |
| **httpx** | 0.28 | `ASGITransport` drives the app in-process, so integration tests exercise real routing, real middleware and real dependency injection with no network. |
| **ruff** | 0.16 | Lint and import sorting. `E, F, I, N, UP, B, SIM, RUF`, 100-column lines. |
| **mypy** | 2.3 | `strict = true` over `app/` and `worker/`. Strict from v0, because retrofitting types is far more expensive than never losing them. |

### 2.1 Why PostgreSQL only, with no SQLite fallback

The original roadmap called for SQLite in development and PostgreSQL in
production. That was abandoned in v1, and the decision paid for itself twice.

**What it cost:** integration and acceptance tests now need a running database.
They fail loudly with setup instructions rather than skipping — a silently
skipped test in a suite whose green result defines "done" is worse than a
failing one.

**What it bought:** the atomic job claim in v3 was planned as dialect-aware
code, one path for SQLite and another for PostgreSQL, and it was named the
hardest part of the hardest version. Going PostgreSQL-only deleted that entirely
and left one statement. It also made native enum types and `ON CONFLICT`
available, both of which are used.

### 2.2 What was deliberately not used

- **No Celery, RQ, or a message broker.** The jobs already live in PostgreSQL. A
  separate broker means two systems that can disagree about what is queued. A
  row is claimed and its state recorded in one transaction, so there is no
  window where a job is handed out but not recorded.
- **No Redis.** The rate limiter is in-process behind an interface written for
  the day Redis replaces it. Adding it before there is a second process to
  coordinate would be infrastructure with no reader.
- **No `python-magic` or `libmagic`.** Detection is eight small classes over
  documented signatures. A C library dependency for what fits in 240 readable
  lines is a poor trade, and the explicit version can be made to answer
  `unknown` honestly rather than guessing.
- **No bcrypt or Argon2 for API keys.** These are 256 bits from
  `secrets.token_urlsafe`. There is nothing to guess, so a work factor would add
  latency to every request and buy no security. Reasoning recorded in
  `app/security/keys.py`.
- **No user accounts.** Machine keys with scopes are correct for a machine-facing
  API. Users belong to Stage 8.

---

## 3. Architecture

### 3.1 Layers

```
   HTTP
     |
  app/api/          routes, dependency wiring, RFC 7807 error handling
     |
  app/services/     intake: the one place several steps must agree
     |
  +--+---------------+--------------+----------------+
  |                  |              |                |
app/domain/    app/storage/    app/queue/     app/security/
models,        SampleStorage   JobQueue       keys, scopes,
enums,         protocol +      protocol +     rate limits,
lifecycle,     local, memory   database,      audit
hashing                        memory
  |                  |              |                |
  +------------------+------+-------+----------------+
                            |
                       app/db/  engine, sessions, migrations
                            |
                       PostgreSQL 18

app/filetypes/    detector registry, called by intake
worker/           the stub consumer, the first caller of JobQueue
```

### 3.2 The two protocols, and how they were arrived at

Both `SampleStorage` and `JobQueue` were **extracted from working code once a
second implementation existed to shape them**, never designed in advance. That
rule is in `VERSIONS.md` and it held.

- `SampleStorage` (`app/storage/base.py`) came out of the local filesystem
  writer in v2. Every method exists because a caller needed it: intake puts and
  checks existence, download gets. It knows nothing about paths, directories,
  encryption or buckets, which is what would let object storage replace the
  filesystem without touching a caller.
- `JobQueue` (`app/queue/base.py`) came out of v3 once the stub worker and the
  reaper both existed. Absent by design: priorities, delays, backoff,
  dead-letter queues. None has a caller.

Each protocol has two implementations and a **contract suite** that runs every
assertion against both. That is the point of the second implementation: a suite
that only ever ran against PostgreSQL would prove the backend works while
quietly letting SQL-shaped assumptions leak into callers.

### 3.3 Request lifecycle

A submission, end to end:

1. **Middleware** binds a request id (honouring an inbound `X-Request-ID`) and
   echoes it on the response, including on every error.
2. **`require_scope(SUBMISSIONS_WRITE)`** authenticates, then rate limits, then
   authorises — in that order, and the order is the security decision. Limiting
   after authentication makes the limit per key rather than per connection;
   authorising last means a caller with a valid key and the wrong scope is told
   so instead of being throttled.
3. **`IntakeService.submit`** streams the upload through a 64 KB buffer into a
   temporary file, updating SHA-256, SHA-1 and MD5 as it goes, keeping the first
   512 bytes, and enforcing the size cap *during* the stream.
4. **Detection** runs over those 512 bytes. A duplicate keeps the type decided
   the first time, since the content is identical by definition.
5. **Storage** puts the bytes under their digest, sealing them a chunk at a time
   with AES-256-GCM. Storing is idempotent, so a repeat write is harmless.
6. **The rows** are written: sample via `ON CONFLICT DO NOTHING`, job via
   `JobQueue.enqueue`, both in the caller's transaction so the job becomes
   claimable at the same instant its input becomes readable.
7. **Audit** records the acceptance on its own session.
8. **202 Accepted**, with a `Location` header pointing at the job.

---

## 4. Module reference

### `app/api/`

| File | What it holds |
|---|---|
| `deps.py` | Everything request-scoped is read from `app.state`, never a module global. That is what lets the suite build an app around a throwaway database and a temporary storage root without touching process-wide state. |
| `errors.py` | RFC 7807 problem details for every failure, carrying the request id. One error shape, decided before the API grew. Adds `Retry-After` when the exception carries one. |
| `routes/submissions.py` | Thin. Audits both acceptance and rejection — a trail of successes hides the pattern worth finding. |
| `routes/jobs.py` | One job by id. Scope `jobs:read`. |
| `routes/samples.py` | Metadata by digest, plus the scope-gated download. |
| `routes/health.py` | `/healthz` touches nothing; `/readyz` checks the database. See section 6. |

### `app/domain/`

| File | What it holds |
|---|---|
| `enums.py` | `JobStatus` (5) and `RunOutcome` (5). Separate vocabularies: one describes the request, the other describes the run. Merging them makes "how many jobs are in flight" and "how many runs told us nothing" the same query. |
| `lifecycle.py` | The transition table as data, plus two invariants: finishing requires an outcome, and an outcome is only accepted when finishing. |
| `models.py` | Four tables. Domain behaviour (`transition_to`, `grant_lease`) lives on `Job` rather than in the queue, so both queue backends inherit identical semantics. |
| `schemas.py` | Pydantic request/response models, separate from the ORM. |
| `hashing.py` | `StreamHasher`, updating three digests over one pass of the bytes. |

### `app/storage/`

`base.py` (protocol), `local.py` (encrypted filesystem), `memory.py` (test
double), `encryption.py` (AES-256-GCM envelope), `factory.py` (settings to
backend).

The envelope is `magic(4) + key_id_len(1) + key_id + nonce(12) + ciphertext+tag`.
The key id travels with the object so keys can rotate without rewriting what is
already stored. The header is authenticated but not encrypted, so a tampered key
id is detected rather than followed.

`seal_stream` encrypts chunk-by-chunk from one file to another and produces a
byte-identical envelope to the one-shot `seal`, which is why the streaming path
could be introduced in v5 without a format change or a data migration.

### `app/queue/`

`base.py` (protocol), `database.py` (PostgreSQL), `memory.py` (test double),
`reaper.py` (recovery policy).

The claim is one statement:

```sql
UPDATE jobs SET status='claimed', claimed_by=..., lease_expires_at=...,
                attempts = attempts + 1
WHERE id = (SELECT id FROM jobs WHERE status='queued'
            ORDER BY created_at LIMIT 1
            FOR UPDATE SKIP LOCKED)
RETURNING id, lease_expires_at, attempts
```

`FOR UPDATE` locks the candidate; `SKIP LOCKED` makes a concurrent claimer step
over it rather than block. N workers claiming at once take N different jobs and
nobody waits. The obvious alternative — select then update — passes every
single-threaded test and duplicates work the first time two workers ask
together.

Every mutating method verifies the caller still holds the lease. A worker that
comes back with a result for a job that was reclaimed while it was busy is
refused, which is what stops two workers writing conflicting outcomes.

### `app/security/`

`scopes.py`, `keys.py`, `auth.py`, `ratelimit.py`, `audit.py`,
`provisioning.py`.

Three scopes. `samples:download` is deliberately separate from `jobs:read`:
reading that a job finished is unremarkable, retrieving the bytes of a suspected
malware sample is the most dangerous thing this API can be asked to do, and it
must be possible to grant everything else without granting that.

Audit rows are written **on their own session, never the request's**. The events
most worth recording belong to requests that fail, and a row that rolls back
with the request it describes is not an audit trail. The cost — the pair is not
atomic — is far smaller than the alternative.

### `app/filetypes/`

Eight detectors asked in registration order; first match wins. Order is meaning:
`OOXMLDetector` runs before `ArchiveDetector` because every OOXML document is
also a ZIP and the more specific answer is more useful; `ScriptDetector` runs
last because it is the only one that infers rather than compares.

A detector that raises is logged and skipped rather than allowed to fail the
submission. Identification is advisory — getting it wrong costs Stage 2 some
effort, while refusing the upload loses the sample, and the sample is the thing
that cannot be recreated.

### `worker/`

`StubWorker.process_one` claims a job, marks it running, and stops. It never
calls `complete`. See section 7.

---

## 5. Data model

Four tables, three migrations (`0001` v3, `0002` v4, `0003` v5).

**`samples`** — one distinct piece of content, keyed by its SHA-256. Content
addressing means the same bytes are always the same row, so a duplicate is a
lookup rather than an insert, and an object left behind by a failed transaction
is adopted by the next submission of those bytes rather than duplicated.
Carries `sha1`, `md5` (for lookup against external corpora, never for identity),
`size_bytes` as `BIGINT`, and `file_type`.

**`jobs`** — one request to analyse one sample. `original_filename` lives here
rather than on the sample because it belongs to the submission: the same bytes
may arrive as `invoice.exe` one day and `update.exe` the next, and that
difference is itself evidence. Carries `status`, `run_outcome`, the lease
columns (`claimed_by`, `claimed_at`, `lease_expires_at`, `attempts`), timestamps,
`failure_reason`, and the three provenance versions.

**`api_keys`** — hashed credential, scope array, `disabled_at`. Keys are
disabled, never deleted, because audit rows point at them.

**`audit_events`** — append-only by convention. Event name, outcome, optional
key, request id, method, path, client IP, free-text detail. Never a credential.

**Deliberately absent: no `storage_path` on `Job`.** Where bytes live is an
infrastructure concern; putting it on the model would fight the `SampleStorage`
protocol. **Files are stored under the content hash, never the submitted
filename**, which closes a path-traversal hole for almost no extra code.

### Job state machine

```
queued --claim--> claimed --start--> running --complete--> finished (+ outcome)
   ^                 |                   |
   |                 +--lease lapsed-----+
   |                          |
   +--------------------------+   attempts survives the round trip

any live state --> cancelled   (operator, or attempts exhausted; no outcome)
```

Enforced twice: in Python before any mutation, so a rejected transition leaves
the object untouched; and in SQL, because every queue update is guarded by the
status it expects to find. The Python check gives a clear error, the SQL guard
is what holds under concurrency.

---

## 6. Operational behaviour

**Migrations** are never run at startup. Starting three replicas would start
three migrations, and the schema is not each replica's business. `alembic
upgrade head` is a deployment step. The test suite migrates a throwaway database
on every single run, so a migration that disagrees with the models fails the
suite rather than a deployment.

**Liveness and readiness answer different questions.** `/healthz` touches
nothing external, on purpose: a liveness probe that fails when the database is
unreachable causes the orchestrator to kill and restart every replica of a
healthy service during a database incident, turning a partial outage into a
total one. `/readyz` checks the database and returns 503 when it cannot, which
takes the instance out of the load balancer and leaves it running.

**The reaper runs inside the API process**, one per instance, no coordination
needed — two reapers sweeping the same table is harmless because every update is
guarded by the state it expects. It is on by default because a recovery
mechanism that must be started separately is one that eventually is not started
at all. `UPA_RUN_REAPER=false` turns it off.

**Configuration** is entirely environment-driven with the `UPA_` prefix, around
twenty settings, defaults suitable for local development. Two production guards:
refusing to start with the public development encryption key, and refusing to
start with a bootstrap API key set.

---

## 7. Decisions worth remembering

Ordered by how much trouble each would cause if reversed without understanding
why.

**All five run outcomes were defined in v3, before anything could produce them.**
The project's central claim is that a sandbox run which observed nothing must be
reported as *nothing observed* rather than as *clean*. That only holds if the
vocabulary can express it from the beginning. Adding the honest states later
means a migration plus an audit of every query, dashboard and count that assumed
the shorter list, and one of them is always missed.

**The stub worker records no outcome.** It claims a job, marks it running, and
stops — `running` is the handoff point. Completing requires an outcome, and all
five are statements about a run that has not happened. A stub recording
`completed`, or worse `no_activity_observed`, would be fabricating evidence in
exactly the place the project argues against. A job left running has its lease
expire and is requeued; after its attempts, it is **cancelled, not finished**,
because a worker dying says nothing about the sample.

**Store before commit, never the reverse.** If the commit fails, an unreferenced
object is left in storage. That is inert, and content addressing makes it
self-healing — the next submission of those bytes adopts it. The reverse
ordering leaves a committed row pointing at content that was never stored, which
is a lie every later reader has to defend against.

**The size cap is enforced during the stream, not after.** Checking afterwards
would let a caller make the service consume unbounded disk before the request is
refused. Named in `VERSIONS.md` as v2's main risk, and tested from v2 even
though the formal criterion belongs to v5.

**The extension is never consulted, and nothing is guessed.** A file matching no
detector is `unknown` — a real enum value, so "nothing recognised this" stays
distinguishable from "detection never ran".

**Unknown and disabled API keys produce identical responses.** Distinguishing
them confirms that a particular key exists.

**Every version ended green.** No version left failing tests for the next, and
`ACCEPTANCE.md` records limitations at the version that accepted them and the
version that resolved them.

### Things found by testing, not by reasoning

Recorded because they were surprises:

- `str(sqlalchemy.URL)` masks the password as `***`, producing a URL that cannot
  authenticate. Use `render_as_string(hide_password=False)`.
- `python-multipart` reduces a Windows absolute filename to its base name before
  the application sees it, while leaving relative traversal sequences untouched.
- After a SQLAlchemy `rollback()`, every loaded attribute is expired; reading one
  inside an error path triggers a refresh and a `MissingGreenlet`. Read what the
  error message needs *before* rolling back.
- Two callers storing identical bytes at once collide on the staging filename,
  and Windows refuses a rename onto a path another writer is replacing. Losing
  that race is now tolerated rather than reported — content addressing means the
  winner wrote the same bytes.

---

## 8. Testing strategy

332 tests: **142 unit** (no I/O), **56 contract** (28 assertions against 2
backends), **104 integration** (real PostgreSQL, real ASGI app), **30
acceptance** (one per numbered criterion). 95% coverage against a 90% gate.

**One throwaway database per run**, created on the configured server, migrated to
head, dropped at the end; tables truncated between tests. A crashed run cannot
poison the next one, and the suite never touches development data.

**Tests that need a database fail rather than skip.** A silently skipped test in
a suite whose green result defines "done" is worse than a failing one.

**Concurrency is tested with real concurrency.** `test_concurrent_claim.py` runs
twelve workers against five jobs, each on its own session and therefore its own
connection — sharing one session would serialise the requests and prove nothing.
The duplicate-submission tests do the same with six simultaneous identical
uploads.

**Memory is measured away from the HTTP client.** httpx builds an entire
multipart body in memory, so measuring through it would measure the harness.
AC-24 drives `IntakeService` directly with a generator-backed upload, pushing
64 MB through and asserting peak allocation stays under an eighth of it.

**Contract suites are the reason the protocols can be trusted.** Every assertion
runs against both backends. If a test needed to know which backend it was
talking to, the protocol would have a hole in it.

---

## 9. Limitations that survive Stage 1

Full list, with reasoning, at the end of [`ACCEPTANCE.md`](../ACCEPTANCE.md).
Summarised:

| Limitation | Consequence | Where it belongs |
|---|---|---|
| Docker artifacts unverified | Reviewed by inspection, never built or run; Docker is not installed on the development machine. Both files say so in their first lines | Whenever Docker is available |
| Rate limiter is per process | N replicas enforce N times the configured rate. The `RateLimiter` interface exists so Redis can replace it | Before horizontal scaling |
| Audit trail append-only by convention | The database does not stop anyone who tries to edit it. A rule or trigger would | Deployment hardening |
| Downloads read into memory | A 100 MB download costs 100 MB. Uploads stream; downloads do not | A streaming read on `SampleStorage` |
| Detection reads only 512 bytes | Formats not recognisable from a header are `unknown` — correct but incomplete | Stage 2 |
| `duplicate: false` under a race | Exactly one sample row is created, but simultaneous first submitters may both be told they were first | Cosmetic; recorded, not fixed |
| No cancellation endpoint | `cancelled` is reachable internally, no route exposes it | Stage 8 |
| Nothing runs samples | The whole point of the remaining stages | Stage 2 onward |

---

## 10. Picking this up again

```bash
pip install -e ".[dev]"
psql -U postgres -f scripts/setup-db.sql
cp .env.example .env
alembic upgrade head
python -m pytest
uvicorn app.main:app --reload
```

Set the database password and `UPA_BOOTSTRAP_API_KEY` in `.env` before the
migration step. Run `python -m worker` in a second terminal. The 332 tests must
be green before anything else is attempted.

**Read in this order:** `app/domain/enums.py` (the vocabulary), then
`app/domain/lifecycle.py` (the rules), then `app/services/intake.py` (where the
steps meet), then whichever of `app/queue/database.py` or `app/storage/local.py`
the task touches. The docstrings carry the reasoning; the comments explain the
non-obvious choices rather than restating the code.

**Before Stage 2**, the roadmap calls for an architecture review. The questions
worth asking with the code in hand:

1. Is `SampleStorage` the right shape once Stage 2 needs to read samples
   repeatedly? A streaming `get` is the obvious missing method.
2. Should the reaper stay in the API process once workers are real?
3. Does `RunOutcome` survive contact with an actual sandbox, or does the run
   need its own record rather than a column on the job?
4. Where does static triage output live — on `Sample`, since it is a property of
   the content, or in its own table keyed by analyser version?
