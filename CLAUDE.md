# Project instructions

## Communication style

Use the `caveman` skill (`.claude/skills/caveman/SKILL.md`) for all responses in this repository. Terse, compressed, full technical accuracy retained.

Default intensity: **full**. Change with `/caveman lite|full|ultra`. Turn off with "stop caveman" or "normal mode".

Applies to chat responses only. Written artefacts stay normal prose: code, comments, commit messages, `README.md`, `VERSIONS.md`, `ACCEPTANCE.md`, `docs/`, and anything else another human reads outside this session.

Drop caveman for security warnings, irreversible-action confirmations, and any place compression creates ambiguity. Resume after.

## Project context

Stage 1 (Input and Submission) of a malware behaviour analysis platform. See `VERSIONS.md` for the roadmap and `ACCEPTANCE.md` for the criteria that define each version as done.

Current state: v5 complete — Stage 1 finished. Next: review the architecture, then Stage 2 (static triage).

Rules that hold across versions:
- Every version ends green. No version leaves failing tests for the next.
- Protocols are extracted from working code, never predicted in advance.
- Stage 1 performs no analysis and forms no opinion about a file. Anything malware-specific belongs to Stage 2.
