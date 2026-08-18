"""The two vocabularies the whole project depends on.

These are separate on purpose, and the distinction is the reason both exist.

``JobStatus`` describes *the request*: where a unit of work has got to inside
this system. ``RunOutcome`` describes *the run*: what happened when the sample
was actually executed. A job that reaches ``finished`` always carries an
outcome, and only a finished job carries one.

Collapsing the two - a single "status" containing both ``running`` and
``timed_out`` - is the mistake this split avoids. It makes "how many jobs are in
flight" and "how many runs told us nothing" the same query, and those questions
have nothing to do with each other.

All five outcomes are defined now, in v3, before anything produces them. The
project's central claim is that a sandbox run which observed nothing must be
reported as *nothing observed* rather than as *clean*, and that claim only holds
if the vocabulary can express it from the beginning. Adding the honest states
later means a migration plus an audit of every query, dashboard and count that
already assumed the shorter list, and one of them is always missed.
"""

from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    """Where a job has got to inside this system.

    ``claimed`` and ``running`` are deliberately distinct. A worker takes
    ownership before it begins, and the gap between the two - environment
    preparation, sample retrieval - is where a badly behaved worker most often
    dies. Keeping the states separate makes "died before starting" visible
    rather than indistinguishable from "started and produced nothing".
    """

    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    FINISHED = "finished"
    CANCELLED = "cancelled"


class RunOutcome(StrEnum):
    """What the run itself produced.

    Only ``completed`` means the analysis ran to its natural end. The remaining
    four are all forms of "this run did not tell us what we hoped", and they are
    kept apart because the correct response to each differs.

    Note what is absent: there is no ``clean``, and no ``malicious``. Stage 1
    records what happened to the run. Judging the sample belongs to Stage 6 and
    later, and encoding a verdict here would leak that boundary.
    """

    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    CRASHED_ON_LAUNCH = "crashed_on_launch"
    NO_ACTIVITY_OBSERVED = "no_activity_observed"
    EVASION_SUSPECTED = "evasion_suspected"
