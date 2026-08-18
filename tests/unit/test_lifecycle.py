"""The job state machine.

These tests are the specification for what a job may do. Everything that moves
a job - the queue, the reaper, the worker - goes through
``validate_transition``, so a change here is a change to the whole system, which
is exactly why the rules are tested in one place rather than at each caller.
"""

from __future__ import annotations

import uuid

import pytest

from app.domain.enums import JobStatus, RunOutcome
from app.domain.lifecycle import (
    ALLOWED_TRANSITIONS,
    IllegalTransitionError,
    is_terminal,
    validate_transition,
)
from app.domain.models import Job

pytestmark = pytest.mark.unit


def make_job(status: JobStatus = JobStatus.QUEUED) -> Job:
    """A job in a known state, with the defaults the database would have applied."""
    return Job(
        id=uuid.uuid4(),
        status=status,
        original_filename="sample.bin",
        sample_sha256="a" * 64,
        attempts=0,
    )


# -- The table itself ------------------------------------------------------


def test_every_status_appears_in_the_transition_table() -> None:
    """A status missing from the table would raise KeyError at runtime."""
    assert set(ALLOWED_TRANSITIONS) == set(JobStatus)


def test_all_five_run_outcomes_exist() -> None:
    """AC-13. The honest outcomes are defined before anything can produce them."""
    assert {outcome.value for outcome in RunOutcome} == {
        "completed",
        "timed_out",
        "crashed_on_launch",
        "no_activity_observed",
        "evasion_suspected",
    }


def test_no_outcome_expresses_a_verdict_about_the_sample() -> None:
    """Stage 1 records what happened to the run, never what the file is."""
    values = {outcome.value for outcome in RunOutcome}

    assert "clean" not in values
    assert "malicious" not in values
    assert "benign" not in values


@pytest.mark.parametrize("status", [JobStatus.FINISHED, JobStatus.CANCELLED])
def test_terminal_states_have_no_exits(status: JobStatus) -> None:
    assert is_terminal(status)
    assert ALLOWED_TRANSITIONS[status] == frozenset()


@pytest.mark.parametrize(
    "status", [JobStatus.QUEUED, JobStatus.CLAIMED, JobStatus.RUNNING]
)
def test_every_live_state_can_be_cancelled(status: JobStatus) -> None:
    """The decision to stop can arrive at any moment."""
    validate_transition(status, JobStatus.CANCELLED)


@pytest.mark.parametrize("status", [JobStatus.CLAIMED, JobStatus.RUNNING])
def test_held_work_can_be_returned_to_the_queue(status: JobStatus) -> None:
    """Otherwise a crashed worker silently deletes a submission."""
    validate_transition(status, JobStatus.QUEUED)


# -- Illegal moves ---------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.QUEUED, JobStatus.RUNNING),  # never claimed
        (JobStatus.QUEUED, JobStatus.FINISHED),  # never ran
        (JobStatus.CLAIMED, JobStatus.FINISHED),  # claimed is not started
        (JobStatus.FINISHED, JobStatus.QUEUED),  # terminal
        (JobStatus.FINISHED, JobStatus.RUNNING),  # terminal
        (JobStatus.CANCELLED, JobStatus.QUEUED),  # terminal
        (JobStatus.RUNNING, JobStatus.CLAIMED),  # no going backwards
    ],
)
def test_illegal_transitions_raise(current: JobStatus, target: JobStatus) -> None:
    with pytest.raises(IllegalTransitionError):
        validate_transition(current, target, run_outcome=_outcome_for(target))


def test_terminal_errors_say_so() -> None:
    """The message has to be readable in a log at three in the morning."""
    with pytest.raises(IllegalTransitionError, match="terminal"):
        validate_transition(JobStatus.FINISHED, JobStatus.QUEUED)


# -- The outcome pairing ---------------------------------------------------


def test_finishing_without_an_outcome_is_refused() -> None:
    """A finished job with nothing recorded is the exact ambiguity to avoid."""
    with pytest.raises(IllegalTransitionError, match="without a run outcome"):
        validate_transition(JobStatus.RUNNING, JobStatus.FINISHED)


def test_an_outcome_without_finishing_is_refused() -> None:
    """A queued job carrying "timed_out" claims a run that never happened."""
    with pytest.raises(IllegalTransitionError, match="only meaningful when finishing"):
        validate_transition(
            JobStatus.RUNNING, JobStatus.QUEUED, run_outcome=RunOutcome.TIMED_OUT
        )


@pytest.mark.parametrize("outcome", list(RunOutcome))
def test_any_outcome_may_finish_a_run(outcome: RunOutcome) -> None:
    validate_transition(JobStatus.RUNNING, JobStatus.FINISHED, run_outcome=outcome)


# -- The model applies the rules -------------------------------------------


def test_transition_to_records_timestamps() -> None:
    job = make_job()

    job.transition_to(JobStatus.CLAIMED)
    job.transition_to(JobStatus.RUNNING)
    assert job.started_at is not None

    job.transition_to(JobStatus.FINISHED, run_outcome=RunOutcome.NO_ACTIVITY_OBSERVED)
    assert job.finished_at is not None
    assert job.run_outcome is RunOutcome.NO_ACTIVITY_OBSERVED


def test_rejected_transition_changes_nothing() -> None:
    """AC-14. Validation runs before mutation, so nothing is half-applied."""
    job = make_job(JobStatus.QUEUED)

    with pytest.raises(IllegalTransitionError):
        job.transition_to(JobStatus.FINISHED, run_outcome=RunOutcome.COMPLETED)

    assert job.status is JobStatus.QUEUED
    assert job.run_outcome is None
    assert job.finished_at is None


def test_finishing_releases_the_lease() -> None:
    """A finished job is owned by nobody, so the reaper never looks at it."""
    job = make_job()
    job.transition_to(JobStatus.CLAIMED)
    job.grant_lease("worker-1", lease_seconds=60)
    job.transition_to(JobStatus.RUNNING)

    job.transition_to(JobStatus.FINISHED, run_outcome=RunOutcome.COMPLETED)

    assert job.claimed_by is None
    assert job.lease_expires_at is None


def test_requeueing_keeps_the_attempt_count() -> None:
    """Attempts are the record of how often this has gone wrong."""
    job = make_job()
    job.attempts = 2
    job.transition_to(JobStatus.CLAIMED)
    job.grant_lease("worker-1", lease_seconds=60)

    job.transition_to(JobStatus.QUEUED, failure_reason="worker died")

    assert job.attempts == 2
    assert job.claimed_by is None
    assert job.started_at is None
    assert job.failure_reason == "worker died"


def test_a_lease_that_has_not_been_granted_has_not_expired() -> None:
    assert make_job().lease_expired is False


def test_an_expired_lease_reports_itself() -> None:
    job = make_job()
    job.grant_lease("worker-1", lease_seconds=-1)

    assert job.lease_expired is True


def _outcome_for(target: JobStatus) -> RunOutcome | None:
    """Supply an outcome only where one would be legal.

    Without this the parametrised cases would fail the outcome-pairing rule
    rather than the edge rule, and pass for the wrong reason.
    """
    return RunOutcome.COMPLETED if target is JobStatus.FINISHED else None
