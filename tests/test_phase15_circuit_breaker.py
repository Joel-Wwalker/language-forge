"""Phase 1.5 bugfix Fix 3: rate-limit circuit breaker.

# THE BUG (Gate 2 Bug 1)

A single API rate-limit event around slot 14 cascaded into ~29 failed
slots. Every claude-cli invocation after the rate limit died with
`exit 1`, but the runner cheerfully kept submitting the rest of the
plan, burning each slot's retry budget for no reason. By the time
the batch finished, the operational failure rate looked like a
catastrophic pipeline regression — but the root cause was a single
upstream incident.

# THE FIX

A circuit breaker that pauses the batch after N (default 3)
consecutive operational failures of the same error class. Operational
classes: timeout, non-zero exit, rate_limit, executor crash, 'other'.
Non-operational (build_spec / user input) failures don't count.

When the breaker trips:
  - Pending futures are cancelled.
  - In-flight futures get to drain (so their state.json updates
    persist).
  - A clear stderr message tells the user to resume after the
    underlying issue is resolved.
  - BatchOutcome carries `circuit_breaker_tripped`, `_class`,
    `_message` so callers can react programmatically.

These tests pin the contract.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from forge.catalog.planner import Slot
from forge.catalog.runner import (
    BatchRunner, BatchOutcome, BatchState, _CircuitBreaker, _classify_error,
    _state_path, STATUS_FAILED, STATUS_PENDING, STATUS_COMPLETED,
)
from forge.orchestrator.subprocess_runner import SubprocessResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stack_slot(slot_id: str, *, seed: int = 0) -> Slot:
    return Slot(
        slot_id=slot_id,
        options={"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=seed,
        target_rarity="common",
        notes="circuit-breaker test fixture",
    )


def _make_run_one_mock(behavior_iter):
    """Wrap an iterable of (success, error) tuples into a function that
    matches `subprocess_runner.run_one`'s signature. Each call consumes
    the next behavior from the iterator."""
    behavior_iter = iter(behavior_iter)

    def fake_run_one(spec, output_root, **kwargs):
        slot_id = kwargs.get("slot_id") or spec.get("lang_name", "?")
        try:
            success, error = next(behavior_iter)
        except StopIteration:
            success, error = True, None
        return SubprocessResult(
            slot_id=slot_id, lang_name=slot_id,
            success=success, duration_seconds=0.01,
            lang_dir=None, summary_path=None,
            stdout="", stderr="" if success else (error or "exit 1"),
            returncode=0 if success else 1,
            error=None if success else (error or "exit 1"),
        )
    return fake_run_one


# ---------------------------------------------------------------------------
# Unit tests for the classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("err, expected", [
    (None, None),
    ("", None),
    ("build_spec failed: ValueError: bad slot", "build_spec"),
    ("timeout after 30s", "timeout"),
    ("subprocess timed out", "timeout"),
    ("exit 1", "exit_1"),
    ("Exit 2", "exit_2"),
    ("nonzero exit -1", "exit_-1"),
    ("rate limit exceeded", "rate_limit"),
    ("Anthropic RateLimit error", "rate_limit"),
    ("executor crash: RuntimeError: oops", "executor"),
    ("something weird happened", "other"),
])
def test_classify_error_buckets(err, expected):
    assert _classify_error(err) == expected


# ---------------------------------------------------------------------------
# Unit tests for the breaker
# ---------------------------------------------------------------------------

def test_circuit_breaker_trips_on_3_consecutive_same_class():
    b = _CircuitBreaker(threshold=3)
    for _ in range(3):
        b.record(success=False, error_class="exit_1")
    assert b.tripped is True
    assert b.trip_class == "exit_1"
    assert b.consecutive == 3


def test_circuit_breaker_does_not_trip_on_2():
    b = _CircuitBreaker(threshold=3)
    b.record(success=False, error_class="exit_1")
    b.record(success=False, error_class="exit_1")
    assert b.tripped is False


def test_circuit_breaker_resets_on_success():
    """A success between failures clears the counter so intermittent
    flakes don't trip the breaker."""
    b = _CircuitBreaker(threshold=3)
    b.record(success=False, error_class="exit_1")
    b.record(success=False, error_class="exit_1")
    b.record(success=True, error_class=None)
    b.record(success=False, error_class="exit_1")
    assert b.tripped is False
    assert b.consecutive == 1


def test_circuit_breaker_resets_on_class_change():
    """Different operational classes don't accumulate together."""
    b = _CircuitBreaker(threshold=3)
    b.record(success=False, error_class="exit_1")
    b.record(success=False, error_class="exit_1")
    b.record(success=False, error_class="timeout")
    assert b.tripped is False
    assert b.consecutive == 1
    assert b.last_class == "timeout"


def test_circuit_breaker_trips_on_3_after_class_change():
    """3 timeouts after a different-class failure still trips."""
    b = _CircuitBreaker(threshold=3)
    b.record(success=False, error_class="exit_1")
    b.record(success=False, error_class="timeout")
    b.record(success=False, error_class="timeout")
    b.record(success=False, error_class="timeout")
    assert b.tripped is True
    assert b.trip_class == "timeout"


def test_circuit_breaker_skips_build_spec_failures():
    """build_spec is a user-input error, not operational. It must NOT
    count toward the threshold AND must NOT reset the counter."""
    b = _CircuitBreaker(threshold=3)
    b.record(success=False, error_class="exit_1")
    b.record(success=False, error_class="build_spec")  # ignored
    b.record(success=False, error_class="exit_1")
    b.record(success=False, error_class="build_spec")  # ignored
    b.record(success=False, error_class="exit_1")
    assert b.tripped is True
    assert b.trip_class == "exit_1"


# ---------------------------------------------------------------------------
# Integration tests: BatchRunner pauses on cascading failures
# ---------------------------------------------------------------------------

def test_runner_pauses_after_3_consecutive_exit1_failures(tmp_path):
    """Mock run_one to fail every slot with exit 1. A 10-slot batch
    must stop after 3 failures (not 10)."""
    plan = [_stack_slot(f"slot_{i:03d}", seed=i) for i in range(10)]
    runner = BatchRunner(
        plan=plan, output_root=tmp_path, concurrency=1, run_smoke=False,
    )

    # Force every slot to fail with the same class.
    fake = _make_run_one_mock([(False, "exit 1")] * 10)
    with patch("forge.catalog.runner.run_one", side_effect=fake):
        outcome = runner.run()

    assert outcome.circuit_breaker_tripped is True
    assert outcome.circuit_breaker_class == "exit_1"
    assert "exit_1" in (outcome.circuit_breaker_message or "")
    # Exactly 3 failed slots (the breaker fires AFTER the 3rd failure).
    # The remaining 7 are still pending in state.json so --resume can
    # pick them up.
    assert outcome.failed == 3, (
        f"expected exactly 3 failures, got {outcome.failed}; the breaker "
        f"may have fired late"
    )
    state = BatchState.load(_state_path(tmp_path))
    pending = sum(1 for s in state.slots.values()
                  if s.get("status") == STATUS_PENDING)
    assert pending == 7, (
        f"expected 7 pending slots after circuit breaker trip; got "
        f"{pending}. Resume would have nothing to do otherwise."
    )


def test_runner_does_not_trip_on_intermittent_failures(tmp_path):
    """Alternating fail/success doesn't trip the breaker. The runner
    runs every slot to completion (3 fails + 3 successes = 6 slots,
    none cancelled)."""
    plan = [_stack_slot(f"slot_{i:03d}", seed=i) for i in range(6)]
    runner = BatchRunner(
        plan=plan, output_root=tmp_path, concurrency=1, run_smoke=False,
    )

    fake = _make_run_one_mock([
        (False, "exit 1"),
        (True, None),
        (False, "exit 1"),
        (True, None),
        (False, "exit 1"),
        (True, None),
    ])
    with patch("forge.catalog.runner.run_one", side_effect=fake):
        outcome = runner.run()

    assert outcome.circuit_breaker_tripped is False
    # All 6 slots ran: 3 completed, 3 failed.
    assert outcome.completed == 3
    assert outcome.failed == 3


def test_runner_does_not_trip_on_build_spec_failures(tmp_path):
    """build_spec failures don't count. Three slots with malformed
    options would still allow subsequent valid slots to run."""
    # We can't easily fake build_spec failures without invasive mocks.
    # Instead, fake run_one to return build_spec-shaped errors for the
    # first 3 slots, then succeed. The breaker's classifier should
    # bucket those as 'build_spec' and NOT trip.
    plan = [_stack_slot(f"slot_{i:03d}", seed=i) for i in range(5)]
    runner = BatchRunner(
        plan=plan, output_root=tmp_path, concurrency=1, run_smoke=False,
    )

    fake = _make_run_one_mock([
        (False, "build_spec failed: ValueError: bad option"),
        (False, "build_spec failed: ValueError: bad option"),
        (False, "build_spec failed: ValueError: bad option"),
        (True, None),
        (True, None),
    ])
    with patch("forge.catalog.runner.run_one", side_effect=fake):
        outcome = runner.run()

    # Note: when run_one returns success=False with a build_spec-shaped
    # error, the runner records it with that error string, so the
    # classifier sees 'build_spec' and skips it. Breaker doesn't trip.
    assert outcome.circuit_breaker_tripped is False, (
        f"breaker tripped on build_spec failures: "
        f"{outcome.circuit_breaker_message}"
    )
    # All 5 slots ran: 2 completed, 3 failed.
    assert outcome.completed == 2
    assert outcome.failed == 3


def test_runner_circuit_breaker_message_is_user_friendly(tmp_path):
    """The trip message must contain `--resume` so the user knows how
    to recover."""
    plan = [_stack_slot(f"slot_{i:03d}", seed=i) for i in range(5)]
    runner = BatchRunner(
        plan=plan, output_root=tmp_path, concurrency=1, run_smoke=False,
    )
    fake = _make_run_one_mock([(False, "exit 1")] * 5)
    with patch("forge.catalog.runner.run_one", side_effect=fake):
        outcome = runner.run()

    assert outcome.circuit_breaker_tripped is True
    msg = outcome.circuit_breaker_message
    assert msg is not None
    assert "paused" in msg.lower()
    assert "--resume" in msg
    assert "exit_1" in msg


def test_runner_resume_after_circuit_breaker_trip_works(tmp_path):
    """After a circuit-breaker trip leaves slots pending, a second
    `runner.run(resume=True)` picks them up. With successful subprocesses
    on the resume run, those pending slots complete normally."""
    plan = [_stack_slot(f"slot_{i:03d}", seed=i) for i in range(6)]

    # First run: trip the breaker after slot 3.
    runner1 = BatchRunner(
        plan=plan, output_root=tmp_path, concurrency=1, run_smoke=False,
    )
    fake_fail = _make_run_one_mock([(False, "exit 1")] * 6)
    with patch("forge.catalog.runner.run_one", side_effect=fake_fail):
        out1 = runner1.run()
    assert out1.circuit_breaker_tripped is True
    assert out1.failed == 3

    # Second run: resume. The 3 already-failed slots stay failed
    # (resume only picks up pending slots — failed is terminal). The
    # 3 still-pending slots get retried and succeed this time.
    runner2 = BatchRunner(
        plan=plan, output_root=tmp_path, concurrency=1, run_smoke=False,
    )
    fake_ok = _make_run_one_mock([(True, None)] * 3)
    with patch("forge.catalog.runner.run_one", side_effect=fake_ok):
        out2 = runner2.run(resume=True)
    assert out2.circuit_breaker_tripped is False
    # Three slots should have completed in the resume run.
    assert out2.completed == 3
    # The other 3 stay failed.
    assert out2.failed == 3


def test_circuit_breaker_default_threshold_is_3():
    """Production threshold is 3 unless overridden."""
    runner = BatchRunner(plan=[], output_root=Path("/tmp"))
    assert runner.circuit_breaker_threshold == 3


def test_circuit_breaker_threshold_is_configurable():
    """Tests can lower or raise the threshold via the constructor."""
    runner = BatchRunner(
        plan=[], output_root=Path("/tmp"),
        circuit_breaker_threshold=5,
    )
    assert runner.circuit_breaker_threshold == 5
