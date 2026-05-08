"""Phase 1.5 bugfix Fix 1: state.json writes are concurrent-safe.

Gate 2 surfaced a real race: with concurrency≥2, every worker wrote
to the same `state.json.tmp` path then called `os.replace`. The
first worker's `os.replace` succeeded; subsequent workers found the
tmp gone and crashed with FileNotFoundError. The crash halted the
50-slot batch around slot 47.

The fix in `forge/catalog/runner.py`:
- Module-level `_state_write_lock` (threading.Lock).
- `_save_state_atomic` acquires the lock around tmp-write +
  os.replace.
- New helper `_update_slot_and_save` does mutate-then-save under
  one lock acquisition so concurrent workers don't lose progress
  via overlapping read-modify-write windows.
- New helper `_set_slot_status_in_memory` for the in-flight RUNNING
  marker (no disk write, but still lock-guarded so concurrent
  serializers see a consistent dict).

These tests pin the contract.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from forge.catalog.runner import (
    BatchState, _save_state_atomic, _update_slot_and_save,
    _set_slot_status_in_memory, _state_path,
)


def test_concurrent_save_state_does_not_crash(tmp_path):
    """N threads each call _save_state_atomic with distinct payloads.
    No FileNotFoundError, no crash. Final state.json is valid JSON
    matching some writer's payload. Pre-fix this would intermittently
    raise the Gate 2 FileNotFoundError on os.replace."""
    state = BatchState.fresh(Path("plan.json"), tmp_path)
    state.slots = {f"slot_{i:03d}": {"status": "pending"} for i in range(8)}

    errors: list[Exception] = []

    def writer(thread_id: int):
        # Each thread mutates its own slot and saves repeatedly.
        # Repeated writes increase the chance of catching a race.
        try:
            for j in range(10):
                _update_slot_and_save(
                    state, f"slot_{thread_id:03d}",
                    {"status": "completed", "iteration": j},
                    tmp_path,
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, (
        f"concurrent _save_state_atomic raised {len(errors)} exception(s); "
        f"first: {errors[0]!r}"
    )

    # Final state.json must be valid JSON and have all 8 slots.
    final = json.loads(_state_path(tmp_path).read_text(encoding="utf-8"))
    assert "slots" in final
    for i in range(8):
        sid = f"slot_{i:03d}"
        assert sid in final["slots"], (
            f"slot {sid} missing from final state — concurrent write "
            f"lost progress"
        )
        assert final["slots"][sid]["status"] == "completed"


def test_concurrent_progress_is_not_lost(tmp_path):
    """Two threads write distinct progress (slot_5 vs slot_6); both
    must persist in the final state. Pre-fix the read-modify-write
    pattern outside the lock could lose one update — both threads
    snapshot the same in-memory state, mutate their own slot, save;
    the second save's serialization captures both mutations because
    they're both writing to the same shared dict, but ONE writer's
    persisted JSON could miss the other's mutation if iteration
    overlapped a write."""
    state = BatchState.fresh(Path("plan.json"), tmp_path)
    state.slots = {
        "slot_5": {"status": "pending"},
        "slot_6": {"status": "pending"},
    }

    barrier = threading.Barrier(2)

    def writer_5():
        barrier.wait()  # both threads start at the same instant
        _update_slot_and_save(
            state, "slot_5", {"status": "completed", "by": "thread_a"},
            tmp_path,
        )

    def writer_6():
        barrier.wait()
        _update_slot_and_save(
            state, "slot_6", {"status": "completed", "by": "thread_b"},
            tmp_path,
        )

    t1 = threading.Thread(target=writer_5)
    t2 = threading.Thread(target=writer_6)
    t1.start(); t2.start()
    t1.join(); t2.join()

    final = json.loads(_state_path(tmp_path).read_text(encoding="utf-8"))
    # Both slots must reflect their respective writes.
    assert final["slots"]["slot_5"]["status"] == "completed"
    assert final["slots"]["slot_5"]["by"] == "thread_a"
    assert final["slots"]["slot_6"]["status"] == "completed"
    assert final["slots"]["slot_6"]["by"] == "thread_b"


def test_set_slot_status_in_memory_does_not_crash_under_load(tmp_path):
    """The in-flight RUNNING marker is mutated in memory only. With
    many threads racing the mutation while another thread serializes
    via _save_state_atomic, the lock prevents `dictionary changed
    size during iteration` errors during to_json()."""
    state = BatchState.fresh(Path("plan.json"), tmp_path)
    state.slots = {f"slot_{i:03d}": {"status": "pending"} for i in range(20)}

    stop = threading.Event()
    errors: list[Exception] = []

    def mutator(thread_id: int):
        try:
            i = 0
            while not stop.is_set():
                _set_slot_status_in_memory(
                    state, f"slot_{thread_id:03d}",
                    {"status": "running", "tick": i},
                )
                i += 1
        except Exception as e:
            errors.append(e)

    def serializer():
        try:
            for _ in range(20):
                _save_state_atomic(state, tmp_path)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=mutator, args=(i,)) for i in range(8)]
    threads.append(threading.Thread(target=serializer))
    for t in threads:
        t.start()

    # Wait briefly for all writers + the serializer to interleave.
    threads[-1].join(timeout=5)
    stop.set()
    for t in threads[:-1]:
        t.join(timeout=2)

    assert not errors, (
        f"concurrent mutation+serialization raised "
        f"{len(errors)} exception(s); first: {errors[0]!r}"
    )


def test_save_state_atomic_creates_state_json_with_valid_content(tmp_path):
    """Sanity baseline: a single _save_state_atomic call writes a
    parseable state.json with the expected fields."""
    state = BatchState.fresh(Path("plan.json"), tmp_path)
    state.slots = {"only_slot": {"status": "completed"}}
    _save_state_atomic(state, tmp_path)
    sp = _state_path(tmp_path)
    assert sp.exists()
    data = json.loads(sp.read_text(encoding="utf-8"))
    assert data["plan_path"] == "plan.json"
    assert "last_updated" in data
    assert data["slots"]["only_slot"]["status"] == "completed"
    # No leftover .tmp file.
    assert not sp.with_suffix(".json.tmp").exists()
