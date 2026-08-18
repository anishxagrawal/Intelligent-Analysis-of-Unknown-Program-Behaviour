"""Which job state changes are legal, in one place.

The transition table is data rather than a chain of ``if`` statements scattered
through the queue and the worker. That is the whole point: there is exactly one
answer to "can a job go from here to there", and every caller gets the same one.

Enforcement happens twice, and both times matter:

  * in Python, through :func:`validate_transition`, which refuses the move
    before anything is mutated, so an illegal transition cannot be half-applied
  * in SQL, because every queue update is guarded by the status it expects to
    find, so two processes racing on the same job cannot both win

The Python check gives a clear error. The SQL guard is what actually holds under
concurrency, where the state read a moment ago may already be stale.
"""

from __future__ import annotations

from app.domain.enums import JobStatus, RunOutcome

#: Legal moves, keyed by the state being left.
#:
#: Three edges are worth explaining:
#:
#:   claimed -> queued  and  running -> queued
#:       A lease expired, or a worker gave the job back. Work that nobody is
#:       doing must return to the queue, otherwise a crashed worker silently
#:       deletes a submission.
#:
#:   running -> finished
#:       The only route to finished. A job cannot finish without having run,
#:       which is what makes "finished" mean something.
#:
#:   * -> cancelled
#:       Reachable from every non-terminal state, because the decision to stop
#:       can arrive at any moment.
ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.CLAIMED, JobStatus.CANCELLED}),
    JobStatus.CLAIMED: frozenset({JobStatus.RUNNING, JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset({JobStatus.FINISHED, JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.FINISHED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}

#: States nothing leaves. A terminal job is a historical record.
TERMINAL_STATUSES: frozenset[JobStatus] = frozenset({JobStatus.FINISHED, JobStatus.CANCELLED})


class IllegalTransitionError(Exception):
    """Raised when a state change that the model forbids is attempted.

    Raised *before* any attribute is written, so a caught error leaves the job
    exactly as it was.
    """

    def __init__(self, current: JobStatus, target: JobStatus, reason: str | None = None) -> None:
        self.current = current
        self.target = target
        detail = reason or f"{current.value} -> {target.value} is not a legal transition"
        super().__init__(detail)


def is_terminal(status: JobStatus) -> bool:
    """Report whether a job in this state can still change."""
    return status in TERMINAL_STATUSES


def validate_transition(
    current: JobStatus,
    target: JobStatus,
    *,
    run_outcome: RunOutcome | None = None,
) -> None:
    """Raise :class:`IllegalTransitionError` unless the move is allowed.

    Two invariants beyond the edge list are checked here, because both are
    properties of the transition rather than of either state alone:

      * finishing requires an outcome - "finished" with nothing recorded is the
        exact ambiguity this project exists to remove
      * an outcome may only accompany finishing - a queued job carrying
        ``timed_out`` would be a claim about a run that has not happened
    """
    if target not in ALLOWED_TRANSITIONS[current]:
        if is_terminal(current):
            raise IllegalTransitionError(
                current, target, f"{current.value} is terminal; no transition leaves it"
            )
        raise IllegalTransitionError(current, target)

    if target is JobStatus.FINISHED and run_outcome is None:
        raise IllegalTransitionError(
            current, target, "a job cannot finish without a run outcome"
        )

    if target is not JobStatus.FINISHED and run_outcome is not None:
        raise IllegalTransitionError(
            current,
            target,
            f"a run outcome is only meaningful when finishing, not when moving to {target.value}",
        )
