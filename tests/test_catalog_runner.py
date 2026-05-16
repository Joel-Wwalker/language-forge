"""Phase 1.2: tests for `BatchRunner`.

What we're pinning here:
  - Output structure: each slot lands at <output>/<slot_id>/, slot.json
    is copied next to it, generation_summary.json is in there.
  - Resume: a second run with `resume=True` skips slots whose state
    is terminal and re-runs only the others.
  - Failure tolerance: a single slot's failure (build_spec error,
    subprocess crash) doesn't stop the batch.
  - state.json shape and atomic-write contract.
  - The CLI returns sensible exit codes.

We test against TEMPLATED families (s_expression, stack_based) so the
test suite stays runnable without ANTHROPIC_API_KEY. The lazy LLM
client (Phase 0 closeout C2) means no real network calls are made on
the templated path. A separate gated test exercises a c_like slot
end-to-end with the API key.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.catalog.planner import Slot
from forge.catalog.runner import (
    BatchRunner, BatchOutcome, BatchState,
    STATUS_COMPLETED, STATUS_FAILED, STATUS_PENDING, STATUS_RUNNING,
    _state_path,
)


# ---------------------------------------------------------------------------
# Helpers: build small templated-family slots for cheap end-to-end tests
# ---------------------------------------------------------------------------

def _stack_slot(slot_id: str, *, seed: int = 0) -> Slot:
    return Slot(
        slot_id=slot_id,
        options={"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=seed,
        target_rarity="common",
        notes="test fixture",
    )


def _sexpr_slot(slot_id: str, *, seed: int = 0) -> Slot:
    return Slot(
        slot_id=slot_id,
        options={"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=seed,
        target_rarity="common",
        notes="test fixture",
    )


# ---------------------------------------------------------------------------
# Output structure
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_runner_produces_per_slot_output_dirs(tmp_path):
    """Slot 'foo' must produce <output>/foo/, not
    <output>/<lang_name>/. The slot_id is the stable identifier."""
    plan = [_stack_slot("foo_001", seed=1)]
    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=1)
    outcome = runner.run()

    slot_dir = tmp_path / "foo_001"
    assert slot_dir.exists(), (
        f"expected {slot_dir} to exist; got tmp_path contents: "
        f"{list(tmp_path.iterdir())}"
    )
    # Slot definition copied for traceability.
    assert (slot_dir / "slot.json").exists()
    saved_slot = json.loads((slot_dir / "slot.json").read_text(encoding="utf-8"))
    assert saved_slot["slot_id"] == "foo_001"
    # Generation summary from the subprocess.
    assert (slot_dir / "generation_summary.json").exists()
    assert outcome.completed == 1
    assert outcome.failed == 0


@pytest.mark.slow
def test_runner_records_slot_json_present_in_state(tmp_path):
    """Phase 4 pre-batch Fix 1: the runner records `slot_json_present`
    in each completed slot's state.json entry. This is a defense-in-
    depth assertion against a future regression in the Phase 1.5 Bug 4
    pinning (lang_name = slot_id across the resolver step). If pinning
    broke, the subprocess would write to <output>/<creative_name>/
    while _copy_slot_json wrote to <output>/<slot_id>/, and the
    customization columns would silently disappear from the DB.

    Tests the happy path: file present, flag True."""
    plan = [_stack_slot("slotjson_001")]
    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=1)
    runner.run()
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    entry = state["slots"]["slotjson_001"]
    assert entry["status"] == STATUS_COMPLETED
    assert entry.get("slot_json_present") is True, (
        f"expected slot_json_present=True after successful generation; "
        f"got entry={entry!r}"
    )


@pytest.mark.slow
def test_runner_recovers_slot_json_if_subprocess_deletes_it(tmp_path):
    """Phase 4 pre-batch Fix 1: if a future bug causes the subprocess
    to wipe slot.json (e.g. an aggressive lang_dir cleanup that
    pre-dates the _copy_slot_json's defensive pre-subprocess write),
    the runner's post-subprocess assertion catches it and recovers
    by re-copying. The slot is still recorded as completed; the
    `slot_json_present` flag reflects post-recovery state.

    Simulates the failure by deleting the file inside the runner's
    flow via a patched _run_single override. Confirms the file
    exists at end-of-run and the flag is True."""
    plan = [_stack_slot("slotjson_recover_001")]
    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=1)

    original = runner._copy_slot_json
    call_count = [0]

    def _copy_then_first_call_deletes_after(slot):
        # First call: copy + immediately delete (simulates the bug).
        # Second call: copy normally (the recovery path).
        original(slot)
        call_count[0] += 1
        if call_count[0] == 1:
            (tmp_path / slot.slot_id / "slot.json").unlink()

    with patch.object(runner, "_copy_slot_json",
                      side_effect=_copy_then_first_call_deletes_after):
        runner.run()

    slot_json = tmp_path / "slotjson_recover_001" / "slot.json"
    assert slot_json.exists(), (
        "post-subprocess assertion should have re-copied slot.json"
    )
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    entry = state["slots"]["slotjson_recover_001"]
    assert entry.get("slot_json_present") is True


@pytest.mark.slow
def test_runner_writes_state_json_with_terminal_status(tmp_path):
    plan = [_stack_slot("a_001"), _stack_slot("a_002", seed=2)]
    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=2)
    outcome = runner.run()

    state_file = tmp_path / "state.json"
    assert state_file.exists()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert set(state["slots"].keys()) == {"a_001", "a_002"}
    for sid in ("a_001", "a_002"):
        assert state["slots"][sid]["status"] in {STATUS_COMPLETED, STATUS_FAILED}
        assert "duration_seconds" in state["slots"][sid]


@pytest.mark.slow
def test_runner_writes_batch_summary_json(tmp_path):
    plan = [_stack_slot("bs_001")]
    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=1)
    runner.run()
    sf = tmp_path / "batch_summary.json"
    assert sf.exists()
    s = json.loads(sf.read_text(encoding="utf-8"))
    assert s["total"] == 1
    assert s["succeeded"] + s["failed"] == 1


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_resume_skips_completed_slots(tmp_path):
    """First run does 2 slots. Second run with resume=True does 0
    new work (both already terminal)."""
    plan = [_stack_slot("rs_001"), _stack_slot("rs_002", seed=2)]
    BatchRunner(plan=plan, output_root=tmp_path, concurrency=2).run()

    # Read state.json: both should be terminal.
    state = BatchState.load(_state_path(tmp_path))
    assert state.slots["rs_001"]["status"] == STATUS_COMPLETED
    assert state.slots["rs_002"]["status"] == STATUS_COMPLETED

    # Note the timestamps.
    completed_at_first_run = state.slots["rs_001"]["duration_seconds"]

    # Re-run with resume. Should skip both.
    outcome2 = BatchRunner(
        plan=plan, output_root=tmp_path, concurrency=2,
    ).run(resume=True)
    assert outcome2.skipped_resumed == 2
    assert outcome2.completed + outcome2.failed == 2  # tallied from state, not new work
    # State entries must be unchanged (we didn't re-run them).
    state2 = BatchState.load(_state_path(tmp_path))
    assert state2.slots["rs_001"]["duration_seconds"] == completed_at_first_run


@pytest.mark.slow
def test_resume_runs_only_pending_slots_when_plan_grows(tmp_path):
    """If a slot is added to the plan after a partial run, resume
    should run only the new one."""
    plan_v1 = [_stack_slot("grow_001")]
    BatchRunner(plan=plan_v1, output_root=tmp_path, concurrency=1).run()
    state_v1 = BatchState.load(_state_path(tmp_path))
    assert state_v1.slots["grow_001"]["status"] == STATUS_COMPLETED

    plan_v2 = [_stack_slot("grow_001"), _stack_slot("grow_002", seed=2)]
    outcome = BatchRunner(
        plan=plan_v2, output_root=tmp_path, concurrency=1,
    ).run(resume=True)
    assert outcome.skipped_resumed == 1   # grow_001 was already done
    assert outcome.completed >= 1          # grow_002 just ran
    state_v2 = BatchState.load(_state_path(tmp_path))
    assert state_v2.slots["grow_002"]["status"] == STATUS_COMPLETED


def test_resume_with_no_state_file_treats_as_fresh(tmp_path):
    """resume=True against an empty output dir should not crash; it
    should fall back to fresh-run behavior."""
    plan = [_stack_slot("noresume_001")]
    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=1)
    state = runner._load_or_init_state(resume=True)
    assert "noresume_001" in state.slots
    assert state.slots["noresume_001"]["status"] == STATUS_PENDING


def test_resume_recovers_from_corrupt_state_json(tmp_path):
    """Corrupt state.json shouldn't break resume — fall back to fresh."""
    (tmp_path / "state.json").write_text("{ this is not valid json", encoding="utf-8")
    plan = [_stack_slot("corrupt_001")]
    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=1)
    state = runner._load_or_init_state(resume=True)
    assert state.slots["corrupt_001"]["status"] == STATUS_PENDING


def test_stale_running_state_is_re_marked_pending(tmp_path):
    """A previous-run crash leaves status=RUNNING in state.json. Resume
    should re-run those slots, not skip them."""
    plan = [_stack_slot("stuck_001")]
    state = BatchState.fresh(Path("plan.json"), tmp_path)
    state.slots["stuck_001"] = {"status": STATUS_RUNNING}
    (tmp_path / "state.json").write_text(state.to_json(), encoding="utf-8")

    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=1)
    loaded = runner._load_or_init_state(resume=True)
    assert loaded.slots["stuck_001"]["status"] == STATUS_PENDING


# ---------------------------------------------------------------------------
# Failure tolerance
# ---------------------------------------------------------------------------

def test_build_spec_failure_recorded_not_raised(tmp_path):
    """A slot whose options can't even be expanded by build_spec
    should be recorded as failed; the runner should NOT raise."""
    bogus = Slot(
        slot_id="bogus_001",
        options={"syntax": "imaginary_family", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common",
    )
    runner = BatchRunner(plan=[bogus], output_root=tmp_path, concurrency=1)
    outcome = runner.run()
    assert outcome.failed == 1
    assert outcome.completed == 0
    state = BatchState.load(_state_path(tmp_path))
    assert state.slots["bogus_001"]["status"] == STATUS_FAILED
    assert "build_spec failed" in state.slots["bogus_001"]["error"]


@pytest.mark.slow
def test_one_failure_does_not_stop_the_batch(tmp_path):
    """Mix one bad slot with one good. Both should be processed; only
    the bad one fails."""
    bogus = Slot(
        slot_id="mixed_bad",
        options={"syntax": "nonsense", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common",
    )
    good = _stack_slot("mixed_good", seed=2)
    runner = BatchRunner(plan=[bogus, good], output_root=tmp_path, concurrency=2)
    outcome = runner.run()
    assert outcome.completed == 1
    assert outcome.failed == 1


# ---------------------------------------------------------------------------
# Empty plan / edge cases
# ---------------------------------------------------------------------------

def test_empty_plan_returns_zero_outcome(tmp_path):
    runner = BatchRunner(plan=[], output_root=tmp_path, concurrency=1)
    outcome = runner.run()
    assert outcome.total == 0
    assert outcome.completed == 0
    assert outcome.failed == 0


def test_progress_callback_fires_for_running_and_terminal_status(tmp_path):
    """The on_progress callback should fire at status transitions."""
    bogus = Slot(
        slot_id="cb_001",
        options={"syntax": "imaginary", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common",
    )
    events = []
    runner = BatchRunner(
        plan=[bogus], output_root=tmp_path, concurrency=1,
        on_progress=lambda sid, st, el, ex: events.append((sid, st)),
    )
    runner.run()
    statuses = [st for _, st in events]
    assert STATUS_RUNNING in statuses
    assert STATUS_FAILED in statuses


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------

def test_cli_rejects_missing_plan_file(tmp_path, capsys):
    from forge.catalog.batch import main
    code = main([
        "--plan", str(tmp_path / "no_such_file.json"),
        "--output", str(tmp_path / "out"),
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "no_such_file.json" in err or "ERROR" in err


def test_cli_rejects_invalid_plan_file(tmp_path, capsys):
    from forge.catalog.batch import main
    plan_path = tmp_path / "bad_plan.json"
    plan_path.write_text(json.dumps([{"missing_required_fields": True}]),
                         encoding="utf-8")
    code = main([
        "--plan", str(plan_path),
        "--output", str(tmp_path / "out"),
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "invalid slot plan" in err.lower() or "validation error" in err.lower()


@pytest.mark.slow
def test_cli_runs_a_single_slot_end_to_end(tmp_path, capsys):
    """End-to-end smoke: a one-slot plan loads, runs, exits 0."""
    plan_path = tmp_path / "tiny_plan.json"
    plan_path.write_text(json.dumps([{
        "slot_id": "cli_test_001",
        "options": {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"persona": None, "era": None, "theme": None,
                          "phrasebook": None, "feature_bans": []},
        "seed": 1,
        "target_rarity": "common",
    }]), encoding="utf-8")
    out_dir = tmp_path / "out"

    from forge.catalog.batch import main
    code = main([
        "--plan", str(plan_path),
        "--output", str(out_dir),
        "--concurrency", "1",
        "--timeout-per-slot", "180",
    ])
    assert code == 0
    captured = capsys.readouterr().out
    assert "BATCH COMPLETE" in captured
    assert (out_dir / "cli_test_001" / "slot.json").exists()
    assert (out_dir / "state.json").exists()
    assert (out_dir / "batch_summary.json").exists()
