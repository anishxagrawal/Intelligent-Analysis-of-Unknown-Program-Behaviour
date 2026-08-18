# Acceptance Criteria — Stage 1

Each criterion is one numbered requirement with one test. A version is finished when its criteria are green and nothing earlier has regressed.

```bash
python -m pytest -m acceptance -v
```

Legend: **done** — implemented and green · **pending** — not yet built.

---

## v0 — Project Setup

| ID | Requirement | Test | Status |
|---|---|---|---|
| AC-S1 | Package installs editable with dev extras | manual, see README | done |
| AC-S2 | `pytest` collects and passes | `tests/unit/test_smoke.py` | done |
| AC-S3 | `ruff check .` reports no errors | manual | done |
| AC-S4 | `mypy app` reports no errors | manual | done |
| AC-S5 | Settings load defaults, environment variables override them | `tests/unit/test_config.py` | done |
| AC-S6 | Logger emits parseable JSON including a request id | `tests/unit/test_logging.py` | done |
| AC-S7 | Version constants exist and are non-empty strings | `tests/unit/test_version.py` | done |

---

## v1 — Walking Skeleton

| ID | Requirement | Test | Status |
|---|---|---|---|
| AC-01 | A valid submission returns 202 with a job id | `tests/acceptance/test_ac01.py` | done |
| AC-V1a | The job is retrievable and its fields match what was submitted | `tests/acceptance/test_v1_criteria.py` | done |
| AC-V1b | An unknown job id returns 404 as `application/problem+json` | `tests/acceptance/test_v1_criteria.py` | done |
| AC-V1c | `/healthz` returns 200 | `tests/acceptance/test_v1_criteria.py` | done |
| AC-V1d | Every response carries a request id header | `tests/acceptance/test_v1_criteria.py` | done |
| AC-V1e | A traversal filename writes nothing outside the storage root | `tests/acceptance/test_v1_criteria.py` | done |

### Known limitations accepted in v1

These are deliberate. Recording them is the point: a documented weakness is
engineering, a silent one is a bug waiting for someone else to find.

**Orphaned files on commit failure.** The submission route writes the file
before committing the job row. If the write succeeds and the commit then fails,
an unreferenced file is left in storage and nothing cleans it up.

The alternative ordering is worse: committing first would allow a job row
pointing at a file that does not exist, which every later reader would have to
defend against. An unreferenced file is inert.

v1 deliberately introduces no transaction manager, outbox, compensating delete
or background reaper. The question belongs with the storage boundary in v2.

**No size limit is enforced.** `UPA_MAX_UPLOAD_BYTES` is configured but unused
until v5 (AC-08). v1 will accept an upload of any size.

**No content inspection.** No hashing, deduplication, encryption or file type
detection. v2 and v4 cover these.

---

## v2 — Safe Intake

| ID | Requirement | Test | Status |
|---|---|---|---|
| AC-02 | Sample stored under its content hash; filename never used as a path | `tests/acceptance/test_v2_criteria.py` | done |
| AC-03 | Bytes on disk are encrypted — plaintext absent from the stored object | `tests/acceptance/test_v2_criteria.py` | done |
| AC-04 | SHA-256, SHA-1 and MD5 match known test vectors | `tests/acceptance/test_v2_criteria.py` | done |
| AC-05 | Duplicate bytes reuse the sample row, create a new job, flag the duplicate | `tests/acceptance/test_v2_criteria.py` | done |
| AC-21 | Storage contract suite passes against local and in-memory backends | `tests/contract/test_sample_storage.py` | done |

### Resolved in v2

**The orphaned-file limitation from v1 is now benign.** Objects are keyed by
their own content hash, so an object left behind by a failed commit is adopted
by the next submission of those bytes rather than duplicated. It is inert and
self-healing. The ordering is unchanged and still deliberate: storing before
committing is safer than the reverse, because a committed row pointing at
content that was never stored is a lie every later reader must defend against.

**The size cap is enforced during the stream**, not after, so an oversize
upload cannot make the service consume unbounded disk before being refused.
AC-08 formally covers this in v5; the mechanism landed here because it belongs
in the streaming path.

### Known limitations remaining after v2

**No file type detection.** Every submission is accepted regardless of content.
v4 (AC-06, AC-07).

**No authentication.** Any caller can submit, read any job, and read any sample.
v4 (AC-10 to AC-12).

**Empty uploads are accepted.** A zero-byte file produces a valid sample and
job. v5 (AC-09).

**Concurrent identical submissions may both insert.** Two requests carrying the
same new bytes at the same moment can race on the sample row. The storage layer
is unaffected — content addressing makes the double write harmless — but one
request may fail on the primary key. v5 (AC-25).

---

## v3 — Job Lifecycle and Queue

| ID | Requirement | Test | Status |
|---|---|---|---|
| AC-13 | New job is `queued`; all five run outcomes exist in enum and schema | `tests/acceptance/test_v3_criteria.py` | done |
| AC-14 | Illegal state transition raises and does not persist | `tests/acceptance/test_v3_criteria.py` | done |
| AC-15 | Two concurrent workers cannot claim the same job | `tests/acceptance/test_v3_criteria.py` | done |
| AC-16 | An expired lease returns the job to the queue | `tests/acceptance/test_v3_criteria.py` | done |
| AC-22 | Queue contract suite passes against database and in-memory backends | `tests/contract/test_job_queue.py` | done |

### Resolved in v3

**Schema changes are no longer silent.** `create_all` has been replaced by
Alembic. It created missing tables and ignored existing ones, so a column added
to a model never reached a database that already had that table. Every test run
now migrates a throwaway database from scratch, which means a migration that
disagrees with the models fails the suite rather than a deployment.

**Work handed to a worker can no longer be lost.** A claim is one statement
using `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers cannot take the same
job, and ownership is leased rather than given away, so a worker that dies
silently has its job returned by the reaper.

### Known limitations remaining after v3

**Nothing runs samples.** The worker claims a job, marks it running, and stops.
It records no run outcome, deliberately: all five are statements about a run
that has not happened. Stage 2.

**Jobs cannot be cancelled through the API.** `cancelled` is reachable from the
domain and from the reaper, but no endpoint exposes it. Stage 8 owns operator
interaction; until then cancellation is an internal transition only.

**The reaper is not started by the application.** It exists and is tested, but
nothing runs it on a timer yet. Deployment topology - one process, a sidecar, a
scheduled task - is a v5 question.

**No file type detection.** Every submission is accepted regardless of content.
v4 (AC-06, AC-07).

**No authentication.** Any caller can submit, read any job, and read any sample.
v4 (AC-10 to AC-12).

**Empty uploads are accepted.** A zero-byte file produces a valid sample and
job. v5 (AC-09).

**Concurrent identical submissions may both insert.** Two requests carrying the
same new bytes at the same moment can race on the sample row. v5 (AC-25).

---

## v4 — Identification and Access

| ID | Requirement | Status |
|---|---|---|
| AC-06 | A PE renamed to `.txt` is still detected as PE | pending |
| AC-07 | Unknown file type recorded as `unknown`, not guessed | pending |
| AC-10 | Missing or bad API key returns 401 | pending |
| AC-11 | Valid key with the wrong scope returns 403 | pending |
| AC-12 | Exceeding the rate limit returns 429 | pending |
| AC-19 | Every submission and every auth failure writes an audit row | pending |

---

## v5 — Operations and Release

| ID | Requirement | Status |
|---|---|---|
| AC-08 | Oversize upload rejected with 413, nothing persisted | pending |
| AC-09 | Empty file rejected with 422 | pending |
| AC-17 | Job status response includes state and provenance stamp | pending |
| AC-18 | Provenance records app, schema and config versions | pending |
| AC-20 | Download is attachment-only, octet-stream, scope-gated, `nosniff` | pending |
| AC-23 | `/healthz` and `/readyz` behave correctly when the database is up and down | pending |
| AC-24 | A large upload does not scale memory with file size | pending |
| AC-25 | Concurrent identical submissions do not create duplicate sample rows | pending |
