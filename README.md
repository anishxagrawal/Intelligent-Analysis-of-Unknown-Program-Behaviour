# Intelligent Analysis of Unknown Program Behaviour

A system that takes a program nobody has seen before and works out what it does — by running it in a sealed environment, recording everything it touches, deciding whether that behaviour is dangerous, and explaining the decision with the evidence attached.

**Current state: v5 — Stage 1 complete.** Files are streamed, hashed, deduplicated and stored encrypted at rest; jobs are claimed by workers exactly once and recovered when a worker dies; the container format is identified from magic bytes; every call needs a scoped API key and is audited; and every submission carries a provenance stamp. No analysis capability yet — that is Stage 2. See [VERSIONS.md](VERSIONS.md) for the roadmap and [ACCEPTANCE.md](ACCEPTANCE.md) for exactly what "complete" does and does not mean.

---

## What this is

Given an unknown executable, the finished system will:

1. Inspect the file without running it — hashes, structure, entropy, imports, packing
2. Detonate it inside an isolated virtual machine with five sensors watching
3. Normalise the resulting telemetry into one event schema
4. Classify the behaviour using rules, machine learning, anomaly detection and similarity search
5. Map what it saw onto MITRE ATT&CK, with every technique linked to the events that justify it
6. Write a readable report where every claim cites the evidence behind it

Three design commitments shape the whole architecture:

- **Silence is reported honestly.** "We watched it do nothing harmful" and "we could not observe it" are different results and never collapse into one. Most sandboxes report both as clean, which is wrong exactly on the samples that matter most.
- **Every claim carries evidence.** Nothing appears in a report that cannot be traced to specific recorded events.
- **The language model explains, it never decides.** Its input is text controlled by an adversary, so the verdict stays with deterministic components.

Full design in [docs/Project-Report.md](docs/Project-Report.md). Study guide in [docs/Prerequisites.md](docs/Prerequisites.md).

---

## Requirements

- Python 3.11 or newer
- PostgreSQL 14 or newer, running locally
- Git

---

## Setup

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS and Linux:

```bash
source .venv/bin/activate
```

Then install with development extras:

```bash
pip install -e ".[dev]"
```

### Database

Create the role and database once, as a superuser, choosing your own password:

```bash
psql -U postgres -f scripts/setup-db.sql
```

The `upa` role is created with `CREATEDB` because the test suite creates a
throwaway database for each run and drops it afterwards, so tests never touch
your development data.

### Configuration

Copy the example configuration and set the password you chose:

```bash
cp .env.example .env
```

`.env` is gitignored and is the only place a password should ever appear.

### Schema

The schema is managed by Alembic. Nothing is created at startup, so bring the
database up to date before running the application for the first time and after
pulling any change that touches a model:

```bash
alembic upgrade head
```

v1 and v2 created tables at startup with SQLAlchemy's `create_all`. That was
replaced in v3 because `create_all` creates missing tables and ignores existing
ones entirely — a column added in code never reaches a database that already has
that table, quietly, with no error, until something reads it in production.

Tests build their own throwaway database and migrate it on every run, so a
migration that disagrees with the models fails the suite immediately.

If a development database ever does get into a state migrations cannot fix, drop
everything and start again:

```bash
psql -U upa -d upa_dev -f scripts/reset-dev-db.sql
```

This destroys all development data.

---

## Running

The API:

```bash
uvicorn app.main:app --reload
```

A worker, in a second terminal:

```bash
python -m worker
```

The worker claims queued jobs, leases them, and marks them running. It performs
no analysis and records no run outcome — that belongs to Stage 2, which does not
exist yet. A job left running is recovered when its lease expires, which is the
correct treatment of work that was accepted and never done.

### API keys

Every endpoint except `/healthz` and `/readyz` requires a key in the `X-API-Key`
header. Keys carry scopes, and a key holding the wrong one gets a 403 rather
than a 401 — the caller is known, just not allowed.

| Scope | Grants |
|---|---|
| `submissions:write` | Submit files |
| `jobs:read` | Read job and sample records |
| `samples:download` | Retrieve stored sample bytes |

Issue one:

```bash
python scripts/create-api-key.py --name ingest --scope submissions:write
```

The token is printed once and stored only as a hash. If it is lost, issue
another — it cannot be looked up, including by whoever runs the database.

For local development, set `UPA_BOOTSTRAP_API_KEY` in `.env` and a key with
every scope is created at startup. Production refuses to start with it set.

---

## Running the tests

```bash
python -m pytest -v
```

Integration and acceptance tests need a running PostgreSQL server. They fail
with a clear message rather than skipping, because a silently skipped test in a
suite whose green result defines "done" is worse than a failing one.

Just the acceptance suite, which defines whether a version is finished:

```bash
python -m pytest -m acceptance -v
```

With coverage, which enforces a 90% gate:

```bash
python -m pytest --cov=app --cov-report=term-missing
```

Linting and type checking:

```bash
python -m ruff check .
```

```bash
python -m mypy app
```

---

## Containers

**Unverified.** Docker is not installed on the development machine, so
`Dockerfile` and `docker-compose.yml` have been reviewed by inspection and never
built or run. They are a starting point, not a tested artifact, and both say so
in their first lines.

```bash
docker compose up --build
```

That brings up PostgreSQL, applies migrations as their own one-shot service,
then starts the API on port 8000 and one worker. Migrations run separately
rather than at application startup, because starting three replicas would
otherwise start three migrations.

---

## Configuration

Every setting is read from the environment using the `UPA_` prefix, with defaults suitable for local development. See [.env.example](.env.example) for the full list.

| Variable | Default | Meaning |
|---|---|---|
| `UPA_ENVIRONMENT` | `development` | development, test or production |
| `UPA_LOG_LEVEL` | `INFO` | Root log level |
| `UPA_DATABASE_URL` | `postgresql+asyncpg://upa:upa@localhost:5432/upa_dev` | SQLAlchemy async URL |
| `UPA_STORAGE_ROOT` | `var/samples` | Where stored samples live |
| `UPA_STORAGE_BACKEND` | `local` | `local` or `memory` (tests only) |
| `UPA_SAMPLE_ENCRYPTION_KEY` | _unset_ | Base64 32-byte key. Required in production |
| `UPA_SAMPLE_ENCRYPTION_KEY_ID` | `dev` | Recorded per object so keys can rotate |
| `UPA_MAX_UPLOAD_BYTES` | `104857600` | Largest accepted upload |
| `UPA_JOB_LEASE_SECONDS` | `300` | How long a worker owns a claimed job |
| `UPA_JOB_MAX_ATTEMPTS` | `3` | Hand-outs before a job is cancelled |
| `UPA_REAPER_INTERVAL_SECONDS` | `30` | How often lapsed leases are swept |
| `UPA_WORKER_POLL_SECONDS` | `2` | Worker wait when the queue is empty |
| `UPA_RATE_LIMIT_PER_MINUTE` | `120` | Requests per API key per minute |
| `UPA_RATE_LIMIT_BURST` | _rate_ | Largest burst a key may spend at once |
| `UPA_BOOTSTRAP_API_KEY` | _unset_ | Development key created at startup. Refused in production |
| `UPA_RUN_REAPER` | `true` | Run the lease reaper alongside the API |
| `UPA_API_PREFIX` | `/api/v1` | Prefix for versioned routes |

---

## Project layout

```
Dockerfile        unverified: reviewed by inspection, never built
alembic/          schema migrations, applied with `alembic upgrade head`
app/
  config.py       settings from environment
  logging.py      structured JSON logs with request-id correlation
  version.py      version constants read by provenance stamping
  api/            routes, dependencies, error handling
  domain/         enums, ORM models, schemas, state machine
  storage/        sample storage backends
  queue/          job queue backends
  filetypes/      magic-byte format detection
  security/       API keys, rate limiting, audit trail
  services/       submission and job orchestration
  db/             engine and session management
worker/           job consumers
tests/            unit, contract, integration, acceptance
docs/             design report, study guide, architecture diagrams
```

---

## Safety

This project is built to analyse malicious software. Two rules matter before any real sample is involved:

- **Never run an unknown sample on your main machine or your normal network.** Use a dedicated virtual machine with no shared folders and isolated networking, and snapshot before every run.
- **Store samples in password-protected archives** so nothing executes them by accident.

Most of this system can be built and demonstrated using public datasets and purpose-written harmless programs, with no live malware at all.

---

## Documentation

| Document | Contents |
|---|---|
| [VERSIONS.md](VERSIONS.md) | Roadmap: what is built in what order, and why |
| [ACCEPTANCE.md](ACCEPTANCE.md) | Numbered acceptance criteria and their current status |
| [docs/Stage-1-Implementation.md](docs/Stage-1-Implementation.md) | What was built, which tools and why, and the decisions behind the code |
| [docs/Project-Report.md](docs/Project-Report.md) | Problem statement, literature survey, gaps, methodology, references |
| [docs/Prerequisites.md](docs/Prerequisites.md) | What to study for each architecture stage |
| [docs/Overview-v2.png](docs/Overview-v2.png) | Architecture diagram |
| [docs/plans/](docs/plans/) | Checkpoint-level implementation plans per version |
