# Intelligent Analysis of Unknown Program Behaviour

A system that takes a program nobody has seen before and works out what it does — by running it in a sealed environment, recording everything it touches, deciding whether that behaviour is dangerous, and explaining the decision with the evidence attached.

**Current state: v0 — project setup.** No analysis capability yet. See [VERSIONS.md](VERSIONS.md) for the roadmap.

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

With coverage:

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

## Configuration

Every setting is read from the environment using the `UPA_` prefix, with defaults suitable for local development. See [.env.example](.env.example) for the full list.

| Variable | Default | Meaning |
|---|---|---|
| `UPA_ENVIRONMENT` | `development` | development, test or production |
| `UPA_LOG_LEVEL` | `INFO` | Root log level |
| `UPA_DATABASE_URL` | `postgresql+asyncpg://upa:upa@localhost:5432/upa_dev` | SQLAlchemy async URL |
| `UPA_STORAGE_ROOT` | `var/samples` | Where stored samples live |
| `UPA_MAX_UPLOAD_BYTES` | `104857600` | Largest accepted upload |
| `UPA_API_PREFIX` | `/api/v1` | Prefix for versioned routes |

---

## Project layout

```
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
| [docs/Project-Report.md](docs/Project-Report.md) | Problem statement, literature survey, gaps, methodology, references |
| [docs/Prerequisites.md](docs/Prerequisites.md) | What to study for each architecture stage |
| [docs/Overview-v2.png](docs/Overview-v2.png) | Architecture diagram |
| [docs/plans/](docs/plans/) | Checkpoint-level implementation plans per version |
