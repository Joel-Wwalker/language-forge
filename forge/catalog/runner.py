"""Batch runner: take a slot plan, generate every slot.

Phase 1.2 (production roadmap v2). Sits on top of Phase 0.1's
`subprocess_runner` and adds the slot-aware orchestration layer:

  - Each slot's generated files land at `<output_root>/<slot_id>/`,
    not at `<output_root>/<lang_name>/`. The slot_id is the stable
    identifier; lang_name is just a label inside the spec.
  - The slot definition is copied as `slot.json` next to each
    generated language for traceability.
  - `state.json` at the batch root is updated incrementally as
    slots complete. `--resume` reads it and skips already-finished
    slots so a long batch can survive Ctrl+C / power loss / partial
    network outages.
  - One log line per slot completion with success / failure /
    duration / token usage (read back from generation_summary.json).
  - Failures don't crash the batch. Failed slots are recorded in
    state.json with their error message and stderr so they can be
    retried in isolation.

Public API:
    BatchState                         -- dataclass mirroring state.json
    BatchOutcome                       -- final aggregated result
    BatchRunner(plan, output_root, *)  -- orchestrator
        .run(*, resume=False)          -- main entry; returns BatchOutcome

Design choice: we DON'T just call `subprocess_runner.run_batch` and
let it loop. We drive `run_one` per slot in our own ThreadPoolExecutor
so that state.json + slot.json file operations happen between each
slot's completion and the next, without needing a multi-step callback
contract back into subprocess_runner.
"""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional

from forge.catalog.planner import Slot, slot_to_dict
from forge.catalog.smoke_test import smoke_test, SmokeResult
from forge.orchestrator.subprocess_runner import (
    SubprocessResult, run_one, write_batch_summary,
)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

# Slot completion states. "pending" means we haven't started; "running"
# means we have a subprocess in flight (only ever in the in-memory
# state, never persisted because a process crash leaves it stale);
# "completed" / "failed" are terminal. Resume reads only the terminal
# states.
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

_TERMINAL = {STATUS_COMPLETED, STATUS_FAILED}


@dataclass
class BatchState:
    """Mirror of `state.json`. Resume reads this; the runner updates
    it after every slot completion."""
    plan_path: str
    output_root: str
    started_at: str
    last_updated: str
    # slot_id -> dict with {status, lang_dir, error, duration_seconds, ...}
    slots: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def fresh(cls, plan_path: Path, output_root: Path) -> "BatchState":
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return cls(
            plan_path=str(plan_path), output_root=str(output_root),
            started_at=now, last_updated=now, slots={},
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def load(cls, path: Path) -> "BatchState":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(**raw)


def _state_path(output_root: Path) -> Path:
    return output_root / "state.json"


def _save_state_atomic(state: BatchState, output_root: Path) -> None:
    """Write state.json via tmp + os.replace so a partial write
    can never corrupt a previous state that resume depends on."""
    state.last_updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = _state_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(state.to_json(), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Slot -> spec translation
# ---------------------------------------------------------------------------

def _build_spec_for_slot(slot: Slot) -> dict:
    """Translate a Slot into a spec dict that subprocess_runner can
    consume. Uses slot_id as lang_name so the output dir is stable
    regardless of any randomized name the resolver might pick.

    The spec returned here is the BASE spec from build_spec; the
    subprocess will run resolve() on it (skip_resolver=False) before
    generation."""
    from forge.orchestrator.spec_builder import build_spec
    return build_spec(slot.options, slot.slot_id, **slot.to_build_spec_kwargs())


# ---------------------------------------------------------------------------
# Outcome aggregation
# ---------------------------------------------------------------------------

@dataclass
class BatchOutcome:
    """Final aggregated result of a batch run."""
    total: int
    completed: int
    failed: int
    skipped_resumed: int    # how many slots were skipped because resume found them done
    smoke_passed: int       # of `completed` slots, how many passed smoke
    smoke_failed: int       # of `completed` slots, how many failed smoke
    wall_clock_seconds: float
    state_path: str         # absolute path to state.json
    summary_path: str       # absolute path to batch_summary.json

    @property
    def pass_rate(self) -> float:
        denom = self.completed + self.failed
        return (self.completed / denom) if denom else 0.0

    @property
    def smoke_pass_rate(self) -> float:
        denom = self.smoke_passed + self.smoke_failed
        return (self.smoke_passed / denom) if denom else 0.0


# ---------------------------------------------------------------------------
# BatchRunner
# ---------------------------------------------------------------------------

# Type alias for the progress callback. Args:
#   slot_id, status, elapsed_seconds, extra_info
ProgressFn = Callable[[str, str, float, dict], None]


class BatchRunner:
    """Runs a slot plan to completion against `output_root`.

    Constructor parameters mirror the CLI's flags so the CLI is a
    thin argparse-and-call wrapper.

    Args:
      plan: list of Slot objects (from `planner.make_slot_plan`).
      output_root: directory to write per-slot outputs into.
      concurrency: how many slots to run in parallel.
      timeout_per_slot: per-subprocess wall-clock cap, seconds.
      client_provider: "api" or "claude_cli", or None for auto.
      on_progress: optional callback fired on every status change.
    """

    def __init__(self, plan: list[Slot], output_root: str | Path, *,
                 concurrency: int = 4,
                 timeout_per_slot: float = 600.0,
                 client_provider: Optional[str] = None,
                 plan_path: Optional[Path] = None,
                 run_smoke: bool = True,
                 on_progress: Optional[ProgressFn] = None):
        self.plan = list(plan)
        self.output_root = Path(output_root).resolve()
        self.concurrency = max(1, int(concurrency))
        self.timeout_per_slot = float(timeout_per_slot)
        self.client_provider = client_provider
        self.plan_path = Path(plan_path) if plan_path else Path("(in-memory)")
        self.run_smoke = bool(run_smoke)
        self.on_progress = on_progress
        self._state: Optional[BatchState] = None

    # ---- helpers ----

    def _emit(self, slot_id: str, status: str, elapsed: float = 0.0,
              **extra: Any) -> None:
        if self.on_progress:
            try:
                self.on_progress(slot_id, status, elapsed, extra)
            except Exception:
                pass

    def _copy_slot_json(self, slot: Slot) -> None:
        """Copy slot.json next to the generated language for traceability."""
        slot_dir = self.output_root / slot.slot_id
        slot_dir.mkdir(parents=True, exist_ok=True)
        path = slot_dir / "slot.json"
        path.write_text(json.dumps(slot_to_dict(slot), indent=2),
                        encoding="utf-8")

    def _load_or_init_state(self, *, resume: bool) -> BatchState:
        """If resuming, read existing state.json. Otherwise seed a
        fresh one with every slot at status=pending."""
        sp = _state_path(self.output_root)
        if resume and sp.exists():
            try:
                state = BatchState.load(sp)
            except Exception:
                # Corrupt state: start over rather than silently
                # processing wrong data. Resume should be safe.
                state = BatchState.fresh(self.plan_path, self.output_root)
        else:
            state = BatchState.fresh(self.plan_path, self.output_root)

        # Ensure every plan slot has a state entry. New slots added
        # to the plan file between runs are seeded as pending.
        for slot in self.plan:
            if slot.slot_id not in state.slots:
                state.slots[slot.slot_id] = {"status": STATUS_PENDING}
            elif state.slots[slot.slot_id].get("status") == STATUS_RUNNING:
                # Stale RUNNING from a crashed prior run: re-mark pending.
                state.slots[slot.slot_id]["status"] = STATUS_PENDING
        return state

    def _select_pending(self, state: BatchState, *, resume: bool
                        ) -> tuple[list[Slot], int]:
        """Return the slots that still need to run, plus the count of
        already-terminal slots (skipped_resumed for the outcome)."""
        if not resume:
            # Fresh run: do all of them. Reset any pre-existing terminal
            # statuses so the user gets exactly what they asked for.
            for slot_id in state.slots:
                state.slots[slot_id] = {"status": STATUS_PENDING}
            return list(self.plan), 0

        # Resume: skip terminal-status slots.
        pending: list[Slot] = []
        skipped = 0
        for slot in self.plan:
            entry = state.slots.get(slot.slot_id, {"status": STATUS_PENDING})
            if entry.get("status") in _TERMINAL:
                skipped += 1
            else:
                pending.append(slot)
        return pending, skipped

    def _run_single(self, slot: Slot, state: BatchState) -> SubprocessResult:
        """Build a spec for the slot, hand off to subprocess_runner,
        update state.json on completion. Returns the SubprocessResult.

        Failures (ValueError, build_spec errors, subprocess crashes)
        are caught and recorded — the batch never aborts on a single
        slot's failure."""
        # Mark running. We don't persist RUNNING because a crash leaves
        # the marker stuck; instead, in-memory state keeps it.
        state.slots[slot.slot_id] = {"status": STATUS_RUNNING}
        self._emit(slot.slot_id, STATUS_RUNNING)
        t0 = time.monotonic()
        try:
            spec = _build_spec_for_slot(slot)
        except Exception as e:
            elapsed = time.monotonic() - t0
            error_msg = f"build_spec failed: {type(e).__name__}: {e}"
            res = SubprocessResult(
                slot_id=slot.slot_id, lang_name=slot.slot_id,
                success=False, duration_seconds=elapsed,
                error=error_msg,
            )
            state.slots[slot.slot_id] = {
                "status": STATUS_FAILED,
                "error": error_msg,
                "duration_seconds": elapsed,
            }
            _save_state_atomic(state, self.output_root)
            self._emit(slot.slot_id, STATUS_FAILED, elapsed, error=error_msg)
            return res

        # Copy slot.json BEFORE the subprocess runs so even if the
        # subprocess hard-crashes mid-flight we still have the input
        # on disk for debugging.
        self._copy_slot_json(slot)

        res = run_one(
            spec, self.output_root,
            slot_id=slot.slot_id,
            seed=slot.seed,
            timeout=self.timeout_per_slot,
            client_provider=self.client_provider,
            skip_resolver=False,    # base specs need resolution before generation
        )

        elapsed = res.duration_seconds
        if res.success:
            entry = {
                "status": STATUS_COMPLETED,
                "lang_dir": res.lang_dir,
                "summary_path": res.summary_path,
                "duration_seconds": elapsed,
            }
            # Pull token usage from generation_summary.json if available.
            if res.summary_path and Path(res.summary_path).exists():
                try:
                    summary = json.loads(
                        Path(res.summary_path).read_text(encoding="utf-8"))
                    entry["llm_total_calls"] = summary.get("llm", {}).get("total_calls")
                    entry["llm_input_tokens"] = summary.get("llm", {}).get("total_input_tokens")
                    entry["llm_output_tokens"] = summary.get("llm", {}).get("total_output_tokens")
                except Exception:
                    pass

            # Phase 1.3: smoke-test the language. Doesn't affect the
            # slot's status (a smoke-failed slot is still `completed` —
            # it generated, just with quality issues). Smoke result
            # lands as a sub-field for Phase 2's filter to consume.
            if self.run_smoke and res.lang_dir:
                try:
                    smoke = smoke_test(res.lang_dir)
                    entry["smoke"] = {
                        "passed": smoke.passed,
                        "canonical": smoke.canonical,
                        "kata": smoke.kata,
                        "repl": smoke.repl,
                        "failures": smoke.failures,
                        "skips": smoke.skips,
                        "duration_seconds": smoke.duration_seconds,
                    }
                except Exception as e:
                    entry["smoke"] = {
                        "passed": False,
                        "failures": [f"smoke crashed: "
                                     f"{type(e).__name__}: {e}"],
                    }

            state.slots[slot.slot_id] = entry
            self._emit(slot.slot_id, STATUS_COMPLETED, elapsed,
                       lang_dir=res.lang_dir,
                       smoke_passed=entry.get("smoke", {}).get("passed"))
        else:
            # Trim stderr for state.json — full text lives on disk in
            # the per-slot output dir if the subprocess wrote it.
            stderr_tail = (res.stderr or "").strip().splitlines()[-5:]
            state.slots[slot.slot_id] = {
                "status": STATUS_FAILED,
                "error": res.error or f"exit {res.returncode}",
                "stderr_tail": "\n".join(stderr_tail),
                "duration_seconds": elapsed,
            }
            self._emit(slot.slot_id, STATUS_FAILED, elapsed,
                       error=res.error)

        # Persist after every slot completion so resume can pick up
        # cleanly even if Ctrl+C lands between two completions.
        _save_state_atomic(state, self.output_root)
        return res

    # ---- main entry ----

    def run(self, *, resume: bool = False) -> BatchOutcome:
        """Execute the plan. Returns a BatchOutcome summarizing the
        run. Always writes state.json + batch_summary.json to disk."""
        self.output_root.mkdir(parents=True, exist_ok=True)
        state = self._load_or_init_state(resume=resume)
        self._state = state
        pending, skipped = self._select_pending(state, resume=resume)
        total_to_run = len(pending)

        # Persist the seeded state up-front so a crash before the
        # first slot completes still leaves a usable state.json.
        _save_state_atomic(state, self.output_root)

        results: list[SubprocessResult] = []
        wall_t0 = time.monotonic()

        if total_to_run == 0:
            # Nothing to do (everything already completed, or empty plan).
            pass
        else:
            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                future_to_slot: dict[Future, Slot] = {
                    pool.submit(self._run_single, slot, state): slot
                    for slot in pending
                }
                for fut in as_completed(future_to_slot):
                    slot = future_to_slot[fut]
                    try:
                        res = fut.result()
                    except Exception as e:
                        # Belt-and-suspenders: _run_single swallows
                        # everything, but if a future crashes for some
                        # other reason (e.g. ThreadPool internal error),
                        # don't let it kill the whole batch.
                        res = SubprocessResult(
                            slot_id=slot.slot_id, lang_name=slot.slot_id,
                            success=False, duration_seconds=0.0,
                            error=f"executor crash: {type(e).__name__}: {e}",
                        )
                        state.slots[slot.slot_id] = {
                            "status": STATUS_FAILED, "error": res.error,
                        }
                        _save_state_atomic(state, self.output_root)
                    results.append(res)

        wall = time.monotonic() - wall_t0
        completed = sum(1 for s in state.slots.values()
                        if s.get("status") == STATUS_COMPLETED)
        failed = sum(1 for s in state.slots.values()
                     if s.get("status") == STATUS_FAILED)

        # Smoke aggregate: for completed slots only, how many passed/
        # failed smoke. Slots without a smoke field (run_smoke=False)
        # don't count either way.
        smoke_passed = sum(
            1 for s in state.slots.values()
            if s.get("status") == STATUS_COMPLETED
            and isinstance(s.get("smoke"), dict)
            and s["smoke"].get("passed") is True
        )
        smoke_failed = sum(
            1 for s in state.slots.values()
            if s.get("status") == STATUS_COMPLETED
            and isinstance(s.get("smoke"), dict)
            and s["smoke"].get("passed") is False
        )

        # Final batch summary using the existing helper. We pass only
        # this run's results, not historical ones, so a resumed run's
        # batch_summary.json reflects only what THIS invocation did.
        # state.json is the source of truth for cumulative status.
        summary_path = write_batch_summary(results, self.output_root)

        outcome = BatchOutcome(
            total=len(self.plan),
            completed=completed,
            failed=failed,
            skipped_resumed=skipped,
            smoke_passed=smoke_passed,
            smoke_failed=smoke_failed,
            wall_clock_seconds=round(wall, 3),
            state_path=str(_state_path(self.output_root)),
            summary_path=str(summary_path),
        )
        return outcome
