# Version Roadmap

This file is the single source of truth for what gets built, in what order, and what proves each step is finished.

---

## Versions are not stages

Two numbering schemes exist in this project and they **deliberately do not correspond**. Confusing them is the most likely source of misunderstanding six months from now, so the distinction is stated first.

**Architecture stages** describe *what the system does*. They come from the design in `docs/Project-Report.md`:

| Stage | Name |
|---|---|
| Stage 1 | Input and Submission |
| Stage 2 | Static Triage |
| Stage 3 | Detonation Orchestrator |
| Stage 4 | Analysis Environment |
| Stage 5 | Data Collection and Normalisation |
| Stage 6 | Analysis Engine |
| Stage 7 | AI Reasoning and Report Generation |
| Stage 8 | Output and Interaction |

**Development versions** describe *what has been built*: v0, v1, v2, and so on.

So **v5** means "Stage 1 is implemented and verified." **Stage 5** means "Data Collection and Normalisation." Different concepts, unrelated numbers.

---

## Method

**Each version is a coherent block** — storage, or lifecycle, or access control. That keeps related work together and gives every version a clear identity.

**Inside a version, work runs as a vertical slice** — cutting through routes, services, domain and tests together, ending runnable.

Two rules hold throughout:

1. **Every version ends green.** No version leaves failing tests for the next one to fix.
2. **Protocols are extracted, not predicted.** `SampleStorage` and `JobQueue` get pulled out of working code once a real caller exists to shape the interface. No abstraction is written before something needs it.

---

## Stage 1 — version summary

| Version | Name | Difficulty | Estimate | What exists at the end | Status |
|---|---|---|---|---|---|
| **v0** | Project Setup | Easy | 0.5 day | Installable package, green test harness, lint and types clean | done |
| **v1** | Walking Skeleton | Easy–Moderate | 1 day | A running API that accepts a file and returns a job you can fetch | done |
| **v2** | Safe Intake | Moderate | 2–3 days | Encrypted, content-addressed, deduplicated storage behind a swappable protocol | done |
| **v3** | Job Lifecycle and Queue | **Hard** | 3–4 days | Workers claim work safely; all five run outcomes locked in | done |
| **v4** | Identification and Access | Moderate | 2–3 days | File type from magic bytes; API keys, scopes, rate limits, audit | done |
| **v5** | Operations and Release | Moderate | 2–3 days | Provenance, safe download, health checks, coverage gate, Docker | done |

Roughly 11–15 days at a steady pace.

**Stage 1 is complete.** Every criterion in `ACCEPTANCE.md` is green: 332 tests,
95% coverage against a 90% gate, ruff clean, mypy strict clean. What "complete"
does and does not mean — including the unverified Docker artifacts and the
per-process rate limiter — is written out in full at the end of `ACCEPTANCE.md`.

---

## v0 — Project Setup

**Goal:** a repository that installs, tests, lints and type-checks cleanly, with no application behaviour at all.

**Why it comes first:** it proves the Python environment, packaging, pytest, async testing, ruff, mypy, configuration and logging all work *before* any business logic depends on them. Every later version can then assume the tooling is sound.

**Delivers**
- Git repository with `.gitignore`; existing documents moved into `docs/`
- `pyproject.toml` with runtime and dev dependency groups, and tool configuration
- Package skeleton for `app/`, `worker/`, `tests/`
- `app/version.py` — version constants that v5 provenance will read
- `app/config.py` — settings from environment with `UPA_` prefix
- `app/logging.py` — structured JSON logging with request-id correlation
- Test harness and developer scripts
- CI workflow — last item, and non-blocking

**Acceptance:** AC-S1 to AC-S7. See `ACCEPTANCE.md`.

**Explicitly not here:** any API, route, database table or domain logic.

---

## v1 — Walking Skeleton

**Goal:** prove FastAPI, async SQLAlchemy, PostgreSQL, pytest-asyncio and httpx work together, by pushing one file through the thinnest possible end-to-end path.

v1 is meant to be boring:

```
POST /submissions  ->  save file  ->  create Job  ->  202
GET  /jobs/{id}    ->  the job
```

**Delivers**
- Async engine, session factory, session dependency
- One `Job` table: id, created_at, status, original_filename, size_bytes
- `POST /api/v1/submissions`, `GET /api/v1/jobs/{id}`, `GET /healthz`
- Problem-details error handling, request-id middleware
- Integration tests over httpx ASGI transport

**Deliberately naive:** the file is written directly by the route, with no hashing, no encryption and **no storage abstraction**. One local writer, nothing more. v2 replaces it entirely.

**Files are stored under the job id, never the submitted filename.** The filename is a database column and never touches the filesystem, which closes a path-traversal hole for almost no extra code.

**No `storage_path` on the domain model.** Where bytes live is an infrastructure concern. Putting it on `Job` would fight the `SampleStorage` protocol that arrives in v2.

**Acceptance:** AC-01, AC-V1a to AC-V1e.

---

## v2 — Safe Intake

**Goal:** files are stored the way a malware analysis platform must store them.

**Delivers**
- Streaming upload with incremental SHA-256, SHA-1 and MD5, size cap enforced *during* the stream
- `Sample` table keyed by SHA-256; the original filename is metadata only and never a path
- Duplicate detection: identical bytes reuse the sample row and create a new job
- `SampleStorage` protocol extracted from the working local backend
- AES-256-GCM encryption, per-object nonce, stored key id so keys can be rotated
- In-memory backend, plus the contract suite both backends must pass

**Acceptance:** AC-02, AC-03, AC-04, AC-05, AC-21.

**Main risk:** enforcing the size cap *after* the stream instead of during it, which would let an attacker make the service buffer an enormous upload before rejecting it.

---

## v3 — Job Lifecycle and Queue

**Goal:** work can be handed to a worker safely, and the state model the whole project depends on gets locked in.

**Delivers**
- `JobStatus`: queued, claimed, running, finished, cancelled
- `RunOutcome`: completed, timed_out, crashed_on_launch, no_activity_observed, evasion_suspected — **all five, now**
- Centralised transition validation that raises on illegal moves
- First Alembic migration, replacing `create_all`
- `JobQueue` protocol: enqueue, claim, heartbeat, complete, fail
- Atomic claim using `SELECT ... FOR UPDATE SKIP LOCKED` — one code path, no dialect branching
- Lease expiry and a reaper returning abandoned jobs
- Stub worker that claims a job and marks it ready for Stage 2

**Acceptance:** AC-13, AC-14, AC-15, AC-16, AC-22.

**Hardest version in Stage 1.** Concurrency is the reason: AC-15 requires proving two workers cannot claim the same job, which needs a genuine concurrency test rather than a happy-path assertion. A read-then-write claim looks correct and fails under load.

Postgres makes this easier than originally planned. The roadmap once called for a dialect-aware claim with one path for SQLite and another for Postgres; going Postgres-only removes that entirely and leaves `SKIP LOCKED`, which is the right tool for the job.

**Why all five outcomes now:** the project's central contribution is refusing to report "no activity observed" as "clean". Retrofitting these states later means a migration plus auditing every query and dashboard count, and something always gets missed.

---

## v4 — Identification and Access

**Goal:** the system knows what kind of file it received, and only authorised callers can submit.

**Delivers**
- Detector registry, one class per format: PE, ELF, script, OLE/OOXML, archive
- Dispatch on magic bytes; the extension is never trusted; unknown types recorded as `unknown` rather than guessed
- API keys stored hashed, with scopes: `submissions:write`, `jobs:read`, `samples:download`
- Token-bucket rate limiter behind an interface, so Redis can replace it
- Append-only audit trail covering every submission and every auth failure

**Acceptance:** AC-06, AC-07, AC-10, AC-11, AC-12, AC-19.

**Risk to resist:** scope creep into full user management. API keys with scopes are correct for a machine-facing analysis API; user accounts belong to Stage 8.

---

## v5 — Operations and Release

**Goal:** Stage 1 complete and provably finished.

**Delivers**
- Provenance stamp on job creation, returned on read
- Scope-gated download: `application/octet-stream`, attachment only, `nosniff`, never inline
- `/healthz` and `/readyz`, readiness failing correctly when the database is down
- Remaining rejection paths: empty file 422, oversize 413 with nothing persisted
- Race tests for concurrent duplicate submissions and large-upload memory behaviour
- Coverage gate at 90%, ruff clean, mypy strict
- Dockerfile and docker-compose

**Acceptance:** AC-08, AC-09, AC-17, AC-18, AC-20, AC-23, AC-24, AC-25.

**What "Stage 1 complete" means:** the Stage 1 functional and security requirements are implemented and verified. It does **not** mean production ready. The Docker artifacts ship marked **unverified**, because Docker is not installed on the development machine and they have been checked by inspection only.

---

## Beyond Stage 1

```
v0  ->  repository and tooling
v1  ->  working API
v2  ->  secure storage
v3  ->  job state and queue
v4  ->  file identification and auth
v5  ->  Stage 1 complete
         |
    review architecture
         |
Stage 2  ->  static triage
Stage 5  ->  canonical telemetry
Stage 6  ->  analysis
Stage 7  ->  evidence explanation
         |
v1.0  ->  first complete offline system
         |
Stage 3/4  ->  real VM and detonation
```

Live VM work comes **last**, after the event schema has settled and the pipeline already works on recorded traces. Stages 3 and 4 are the most expensive parts of the project and the most likely to consume unplanned time; everything before them can be built and demonstrated using public datasets and purpose-written harmless test programs.

---

## A boundary worth protecting

**Stage 1 knows nothing about malware analysis.** It accepts bytes, stores them safely, identifies the container format, and hands off a job. It performs no analysis and forms no opinion about the file. Everything malware-specific begins in Stage 2.

If Stage 1 code ever starts reasoning about whether something is malicious, a boundary has leaked.
