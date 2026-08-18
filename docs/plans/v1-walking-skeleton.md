# v1 — Walking Skeleton (PostgreSQL)

> **Status:** approved, in progress. Checkpoint 0 complete.
> Roadmap-level summary lives in [`VERSIONS.md`](../../VERSIONS.md); this file
> holds the checkpoint-by-checkpoint detail and the reasoning behind decisions
> that would otherwise be lost.


## Context

v0 is complete: package installs, 19 tests pass, ruff and mypy clean, roadmap in the repo. What exists is scaffolding — settings, logging, version constants — and nothing that does anything.

v1 pushes one file through the thinnest possible end-to-end path:

```
POST /api/v1/submissions  ->  save file  ->  create Job  ->  202
GET  /api/v1/jobs/{id}    ->  the job
```

The point is not the feature. It is proving FastAPI, async SQLAlchemy, **PostgreSQL** and pytest-asyncio work together before any real design depends on them.

**Change from the approved roadmap: PostgreSQL replaces SQLite everywhere.** No dual-database support, no SQLite fallback. This has consequences beyond swapping a URL, covered below.

## Environment check (already done)

- PostgreSQL 18 installed at `C:\Program Files\PostgreSQL\18`
- Service `postgresql-x64-18` running, port 5432 listening
- Password authentication required; no `pgpass.conf`

**I do not need and will not ask for your password.** You put the connection URL in `.env`, which is gitignored. Settings already load `.env` automatically, so the test suite picks it up without the value passing through me or appearing in any file I write.

---

## What going Postgres-only changes

**It makes v3 simpler, which is the good news.** The approved plan had the hardest part of the hardest version — a dialect-aware atomic job claim, one path for SQLite and another for Postgres. That disappears. `SELECT … FOR UPDATE SKIP LOCKED` is available, which is the correct way to build a database-backed queue, and it is one code path.

**It costs test hermeticity.** Tests now need a running database. Unit tests stay pure; integration and acceptance tests do not. They will **fail loudly with a clear message** if the database is unreachable rather than skipping — a silent skip in a suite whose green result defines "done" is worse than a failure.

**It amends three v0 files.** Honest accounting: v0 shipped with SQLite defaults, so `pyproject.toml`, `app/config.py`, `tests/conftest.py`, `.env.example`, `README.md` and `VERSIONS.md` all need updating. `tests/unit/test_config.py` asserts a SQLite default URL and must change with them. AC-S1 to AC-S7 stay green, but the code behind two of them moves.

**One real risk, flagged early:** `asyncpg` has a history of trouble with Windows' default Proactor event loop. If checkpoint 1 fails on event-loop errors, the fix is a `WindowsSelectorEventLoopPolicy` in `conftest.py` and `main.py`. This is precisely the kind of thing the walking skeleton exists to surface, and it surfaces in checkpoint 1 with nothing else that could be at fault.

---

## One-time database setup (you run this)

`scripts/setup-db.sql` gets written for you to execute:

```sql
CREATE ROLE upa WITH LOGIN PASSWORD 'choose-your-own' CREATEDB;
CREATE DATABASE upa_dev OWNER upa;
```

`CREATEDB` matters: the test suite creates a uniquely named throwaway database per run and drops it afterwards, which needs that privilege. It also means test runs never touch `upa_dev`.

You then create `.env` from `.env.example` and set:

```
UPA_DATABASE_URL=postgresql+asyncpg://upa:your-password@localhost:5432/upa_dev
```

If you would rather use the `postgres` superuser and an existing database, that works too — only the URL changes.

---

## Method: test-driven, block by block

Four checkpoints. Each is test-first — write the failing test, implement until green, stop — and each leaves a working system. No checkpoint starts before the previous is green.

---

## Checkpoint 0 — dependencies and configuration

Small, but it comes first because everything else needs it.

- `pyproject.toml` — replace `aiosqlite` with `asyncpg`
- `app/config.py` — `database_url` default becomes `postgresql+asyncpg://upa:upa@localhost:5432/upa_dev`; add `test_database_url` used only by the suite
- `.env.example`, `README.md` — updated URLs and setup steps
- `scripts/setup-db.sql` — the role and database SQL above
- `tests/unit/test_config.py` — assert the Postgres default instead of the SQLite one
- `VERSIONS.md` — remove dual-database language; record that v3's claim is now a single `SKIP LOCKED` path

**Green:** the existing 19 tests still pass.

---

## Checkpoint 1 — the app starts and answers

**Test first:** `tests/integration/test_health.py` — `GET /healthz` returns 200, carries `X-Request-ID`, echoes an incoming one.

**Then build:**

- `app/db/base.py` — `Base(DeclarativeBase)` with shared `MetaData` and an explicit naming convention for indexes and constraints. Alembic in v3 needs deterministic names; adding the convention later causes churn.
- `app/db/session.py` — `create_engine_and_sessionmaker(settings)` returning an async engine and session factory, built per application instance so each test run is isolated.
- `app/domain/models.py` — the `Job` table.
- `app/main.py` — `create_app(settings: Settings | None = None) -> FastAPI` with lifespan (build engine, `create_all`, dispose on shutdown), request-id middleware, router registration, and `app = create_app()` for uvicorn.
- `app/api/routes/health.py` — `GET /healthz`.
- `tests/conftest.py` — database fixtures (below), plus `app`, `client`, `sample_bytes`.

**This is the checkpoint that matters.** If asyncpg, the Windows event loop, or the ASGI transport are going to cause trouble, it happens here.

### The `Job` table

```
Job
  id                 UUID, primary key          (native uuid on Postgres)
  created_at         timestamptz, UTC
  status             text, default "queued"
  original_filename  text
  size_bytes         integer
```

- `sqlalchemy.Uuid` now maps to a genuine Postgres `uuid` column.
- Timestamps are timezone-aware UTC, defaulted in Python for consistency with later code paths.
- `status` is plain text in v1 and becomes a real enum in v3.
- **No `storage_path`** — where bytes live is infrastructure, and the column would fight the `SampleStorage` protocol arriving in v2.

### Test database strategy

- **Session-scoped:** connect to the server, `CREATE DATABASE upa_test_<random>`, run `create_all`, and `DROP DATABASE` at the end. Throwaway per run, so a crashed run never poisons the next.
- **Function-scoped:** `TRUNCATE` all tables between tests. Fast, and far simpler than SAVEPOINT-based rollback trickery.
- **No database reachable:** fail with a message naming the URL tried and pointing at `scripts/setup-db.sql`.

---

## Checkpoint 2 — errors have one shape

**Test first:** `tests/integration/test_errors.py` — an unknown route returns `application/problem+json` with the expected fields.

**Then build:**

- `app/api/errors.py` — RFC 7807 problem details: an `AppError` base plus handlers for `AppError`, `HTTPException` and `RequestValidationError`, all returning `application/problem+json` with `type`, `title`, `status`, `detail` and the request id.
- `app/domain/schemas.py` — `JobRead`, `SubmissionAccepted`, `from_attributes` enabled.
- `app/api/deps.py` — `get_settings_dep` reading `request.app.state`, and `get_session` yielding an `AsyncSession` per request. Settings come from app state rather than the cached `get_settings()`, so tests build an app around a temporary database without touching the cache.

---

## Checkpoint 3 — the submission path

**Test first:** `tests/integration/test_submission_flow.py` and `tests/integration/test_path_safety.py`.

**Then build:**

- `app/api/routes/submissions.py` — `POST /api/v1/submissions`, multipart, 202 with a `Location` header pointing at the job.
- `app/api/routes/jobs.py` — `GET /api/v1/jobs/{job_id}`, 404 as problem+json when absent.

### Two deliberate decisions

**Files are written under the job id, never the submitted filename.** The original filename is a database column and never touches the filesystem. Barely more code, and it removes a path-traversal hole — `../../../evil.exe` would otherwise escape the storage directory.

**The write is a chunked copy, not `await file.read()`.** Still naive — no hashing, no encryption, no abstraction, no size enforcement — but a 64 KiB loop avoids pulling an entire upload into memory. A `while` loop is not an abstraction. Replaced wholesale in v2, with a comment saying so.

No storage class, no factory, no service object. The route writes the file itself.

### The consistency question, answered honestly

**Order:** generate the job id in Python → write the file to `storage_root/<job_id>` → insert the `Job` row → commit.

**If the write succeeds but the commit fails:** an orphaned file sits in storage with no row referring to it. Disk is consumed and nothing cleans it up.

**Why this order anyway:** the alternative — commit first, then write — fails worse. A job row pointing at a missing file is a lie every later reader must defend against. An unreferenced file is inert: nothing looks for it, nothing breaks, it merely wastes space.

**What v1 does about it: nothing.** No transaction manager, no outbox, no compensating delete, no background reaper, no storage service, no rollback protocol. Each is exactly the abstraction a walking skeleton exists to avoid, and v2's storage boundary is where the question belongs.

**What v1 must not do is overclaim.** The limitation is recorded in two places: a comment in the route explaining the ordering and its failure mode, and a "Known limitations" entry in `ACCEPTANCE.md`. Documented weakness is engineering; silent weakness is a bug waiting for someone else to find.

---

## Checkpoint 4 — acceptance and record

**Test first:** `tests/acceptance/test_ac01.py`, marked `acceptance`.

**Then:** `tests/unit/test_models.py` for `Job` defaults. Update `ACCEPTANCE.md` — mark v1 criteria done, add AC-V1e, add the known-limitation note. Update `.github/workflows/ci.yml` to run a `postgres:16` service container so CI still works.

---

## Acceptance criteria

| ID | Requirement |
|---|---|
| AC-01 | A valid submission returns 202 with a job id |
| AC-V1a | The job is retrievable and its fields match what was submitted |
| AC-V1b | An unknown job id returns 404 as `application/problem+json` |
| AC-V1c | `/healthz` returns 200 |
| AC-V1d | Every response carries a request id header |
| AC-V1e | A traversal filename writes nothing outside the storage root |

## Exit condition

```
v0 unit tests (updated for Postgres)
        +
v1 integration tests
        +
v1 unit tests
        +
AC-01, AC-V1a, AC-V1b, AC-V1c, AC-V1d, AC-V1e
        |
pytest GREEN
ruff   GREEN
mypy   GREEN
        |
record the result
        |
STOP
```

v2 is not touched until the v1 result is recorded.

## Verification

```bash
python -m pytest -v
```

```bash
python -m pytest -m acceptance -v
```

```bash
python -m ruff check . && python -m mypy app
```

Manual smoke test:

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`, submit a file, confirm 202 with a job id, fetch the job, confirm filename and size match. Check `var/samples/` and confirm the file is named by job id. Then confirm the row exists:

```bash
psql -U upa -d upa_dev -c "select id, status, original_filename, size_bytes from jobs;"
```

## Scope boundaries

**In:** the Postgres migration of v0's config, the files above, their tests, and the `ACCEPTANCE.md` update.

**Out:** hashing, encryption, deduplication, `SampleStorage`, the job state machine, the queue, workers, authentication, rate limiting, file type detection, size enforcement, Alembic, the job list endpoint, and every form of orphan cleanup or transactional coordination.

**Blocking dependency:** I cannot run checkpoint 1 onward until `.env` exists with a working `UPA_DATABASE_URL`. I will write `scripts/setup-db.sql` and the docs in checkpoint 0, then pause for you to run the setup and create `.env` before continuing.

**Reporting:** I stop at any checkpoint that surprises me, and at the end of v1 regardless, with test results, before touching v2.
