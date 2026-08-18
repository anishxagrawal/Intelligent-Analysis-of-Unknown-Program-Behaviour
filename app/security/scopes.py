"""What an API key is allowed to do.

Scopes rather than roles, and machine keys rather than user accounts. This is an
API consumed by other programs: a submission pipeline needs to submit and
nothing else, a dashboard needs to read job state and nothing else, and an
analyst tool needs to pull sample bytes. Those are three different levels of
danger and they should not travel together on one credential.

``samples:download`` is deliberately separate from ``jobs:read``. Reading that a
job finished is unremarkable; retrieving the bytes of a suspected malware sample
is the single most dangerous thing this API can be asked to do, and it should be
possible to grant everything else without granting that.

User accounts are out of scope for Stage 1, and adding them here would be scope
creep dressed as thoroughness. They belong to Stage 8.
"""

from __future__ import annotations

from enum import StrEnum


class Scope(StrEnum):
    """One permission a key may hold."""

    SUBMISSIONS_WRITE = "submissions:write"
    JOBS_READ = "jobs:read"
    SAMPLES_DOWNLOAD = "samples:download"


ALL_SCOPES: frozenset[Scope] = frozenset(Scope)


def parse_scopes(values: list[str]) -> frozenset[Scope]:
    """Turn stored scope strings into scopes, discarding anything unrecognised.

    An unknown scope grants nothing. A key written by an older or newer version
    of this code must never accidentally widen into a permission that did not
    exist when it was issued.
    """
    known = {scope.value: scope for scope in Scope}
    return frozenset(known[value] for value in values if value in known)
