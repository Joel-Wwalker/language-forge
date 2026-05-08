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
import re
import sys
import threading
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


# Module-local lock that serializes state.json writes across the
# runner's ThreadPoolExecutor workers. Phase 1.5 Gate 2 surfaced a
# real race: with concurrency≥2 every worker wrote to the same
# `state.json.tmp` path then called `os.replace`. The first
# worker's `os.replace` succeeded; subsequent workers found the
# tmp file gone and crashed with FileNotFoundError. The crash
# halted the batch around slot 47 of 50 in Gate 2.
#
# The lock fixes both the crash AND the underlying issue (last
# writer wins → another writer's progress disappears) by
# serializing the read-modify-write window.
#
# Process-local: this lock only serializes writes from threads
# inside ONE Python process. The runner's ThreadPoolExecutor is
# thread-based within a single process, so this is enough today.
# A future multi-process batch capability (not in Phase 1.5
# scope) would need `fcntl.flock` or similar.
_state_write_lock = threading.Lock()


def _atomic_replace_with_retry(tmp: Path, dst: Path, attempts: int = 3) -> None:
    """Wrap `os.replace(tmp, dst)` with a small retry loop. Phase 1.5
    scope-expansion Gate 2: even within `_state_write_lock`, on Windows
    `os.replace` can throw `PermissionError: Access is denied` when
    another process briefly holds the source file open (antivirus,
    OneDrive sync, indexer). The lock prevents in-process races but
    can't prevent OS-level file-handle contention.

    Each retry sleeps a few ms — typically the contending process
    releases its handle within one tick. We re-raise the last error
    if all attempts fail rather than silently corrupting state."""
    last_err: Optional[Exception] = None
    for i in range(attempts):
        try:
            os.replace(tmp, dst)
            return
        except (PermissionError, OSError) as e:
            last_err = e
            if i < attempts - 1:
                time.sleep(0.05 * (i + 1))  # 50ms, 100ms, ...
    if last_err is not None:
        raise last_err


def _save_state_atomic(state: BatchState, output_root: Path) -> None:
    """Write state.json atomically. Serialized across threads via
    `_state_write_lock` to prevent the Phase 1.5 Gate 2 race.

    Within the lock: tmp write + os.replace pattern still applies so
    a process crash mid-write can't corrupt the existing state.json
    (the existing file remains intact until os.replace swaps in the
    new version)."""
    state.last_updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = _state_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with _state_write_lock:
        tmp.write_text(state.to_json(), encoding="utf-8")
        _atomic_replace_with_retry(tmp, path)


def _update_slot_and_save(state: BatchState, slot_id: str, entry: dict,
                          output_root: Path) -> None:
    """Mutate `state.slots[slot_id]` and persist to disk under one
    lock acquisition. Phase 1.5 Gate 2 fix: workers were doing
    read-modify-write outside the lock, which let two workers read
    the same snapshot, each write a different progress, and lose
    one of the writes. Doing both under the lock means each worker's
    update fully lands before the next worker reads."""
    with _state_write_lock:
        state.slots[slot_id] = entry
        state.last_updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path = _state_path(output_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(state.to_json(), encoding="utf-8")
        _atomic_replace_with_retry(tmp, path)


def _set_slot_status_in_memory(state: BatchState, slot_id: str,
                               entry: dict) -> None:
    """Mutate state.slots in memory ONLY (no disk write). Used for
    the in-flight RUNNING marker that we deliberately don't persist
    (a crash mid-run leaves a stale RUNNING that the resume loader
    re-marks pending). Lock-guarded so concurrent serializers don't
    see a half-written dict during their iteration."""
    with _state_write_lock:
        state.slots[slot_id] = entry


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
# Rate-limit / operational-cascade circuit breaker
# ---------------------------------------------------------------------------
#
# Phase 1.5 bugfix Fix 3 (Bug 1).
#
# Gate 2 wedged when the API rate-limited us mid-batch. Every subsequent
# slot's claude-cli invocation died with `exit 1`, but the runner kept
# submitting the rest, burning the retry budget for no reason. By the
# time the batch finished, ~29 slots had failed in a cascade tracing
# back to a single rate-limit event around slot 14.
#
# The fix is operational, not pipeline. After N (default 3) consecutive
# operational failures of the same class, pause the batch. The user
# gets a clear "stopped at slot K, here's why" message and can resume
# with --resume after addressing the underlying issue (wait for rate
# limit, fix CLI auth, etc.). Build_spec failures (user-input errors)
# do not count toward the threshold; they're orthogonal to operational
# health.

_OPERATIONAL_FAILURE_THRESHOLD = 3


def _classify_error(error: Optional[str]) -> Optional[str]:
    """Bucket a SubprocessResult.error into a coarse error class so
    consecutive same-class failures can be detected.

    Returns:
      None      -- no error (use this on success).
      'build_spec' -- input error from _build_spec_for_slot. NOT counted
                      toward the circuit-breaker threshold.
      'timeout'    -- subprocess timed out.
      'rate_limit' -- rate-limit error message.
      'executor'   -- futures executor crash inside _run_single's belt.
      'exit_<N>'   -- subprocess exited with code N (claude CLI most
                      commonly hits this with N=1 on rate-limit).
      'other'      -- operational failure that didn't match any pattern.
    """
    if not error:
        return None
    e = str(error).lower()
    if e.startswith("build_spec"):
        return "build_spec"
    if "timeout" in e or "timed out" in e:
        return "timeout"
    if "executor crash" in e:
        return "executor"
    if ("rate" in e and "limit" in e) or "ratelimit" in e:
        return "rate_limit"
    m = re.search(r"exit\s+(-?\d+)", e)
    if m:
        return f"exit_{m.group(1)}"
    return "other"


class _CircuitBreaker:
    """Trips after N consecutive operational failures of the same class.

    Operational failures: timeout, non-zero exit, rate_limit, executor
    crash, or 'other'. Non-operational failures (build_spec) are skipped
    — they don't increment the counter and they don't reset it. A slot
    SUCCESS resets the counter and clears last_class.

    This breaker is consulted from a single thread (the as_completed
    consumer in BatchRunner.run), so it doesn't need internal locking.
    If that ever changes, wrap mutations in a Lock."""

    def __init__(self, threshold: int = _OPERATIONAL_FAILURE_THRESHOLD):
        self.threshold = max(1, int(threshold))
        self.consecutive = 0
        self.last_class: Optional[str] = None
        self.tripped = False
        self.trip_class: Optional[str] = None

    def record(self, *, success: bool, error_class: Optional[str]) -> None:
        if success:
            self.consecutive = 0
            self.last_class = None
            return
        # Failed. Non-operational classes don't move the counter at all.
        if error_class is None or error_class == "build_spec":
            return
        if error_class == self.last_class:
            self.consecutive += 1
        else:
            self.consecutive = 1
            self.last_class = error_class
        if self.consecutive >= self.threshold:
            self.tripped = True
            self.trip_class = error_class


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
    # Phase 1.5 bugfix Fix 3 telemetry. Both default to None when the
    # breaker didn't trip; populated when it did.
    circuit_breaker_tripped: bool = False
    circuit_breaker_class: Optional[str] = None
    circuit_breaker_message: Optional[str] = None

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
                 on_progress: Optional[ProgressFn] = None,
                 circuit_breaker_threshold: int = _OPERATIONAL_FAILURE_THRESHOLD):
        self.plan = list(plan)
        self.output_root = Path(output_root).resolve()
        self.concurrency = max(1, int(concurrency))
        self.timeout_per_slot = float(timeout_per_slot)
        self.client_provider = client_provider
        self.plan_path = Path(plan_path) if plan_path else Path("(in-memory)")
        self.run_smoke = bool(run_smoke)
        self.on_progress = on_progress
        # Phase 1.5 bugfix Fix 3: pause the batch after N consecutive
        # operational failures of the same class so a single upstream
        # incident (rate-limit, claude-cli auth) doesn't burn through
        # the whole plan. Tests can lower this; production keeps default.
        self.circuit_breaker_threshold = max(1, int(circuit_breaker_threshold))
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
        # the marker stuck; instead, in-memory state keeps it. The
        # helper takes the lock briefly so concurrent state.to_json()
        # iterations from other workers see a consistent dict.
        _set_slot_status_in_memory(state, slot.slot_id,
                                    {"status": STATUS_RUNNING})
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
            _update_slot_and_save(state, slot.slot_id, {
                "status": STATUS_FAILED,
                "error": error_msg,
                "duration_seconds": elapsed,
            }, self.output_root)
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

            _update_slot_and_save(state, slot.slot_id, entry,
                                   self.output_root)
            self._emit(slot.slot_id, STATUS_COMPLETED, elapsed,
                       lang_dir=res.lang_dir,
                       smoke_passed=entry.get("smoke", {}).get("passed"))
        else:
            # Trim stderr for state.json — full text lives on disk in
            # the per-slot output dir if the subprocess wrote it.
            stderr_tail = (res.stderr or "").strip().splitlines()[-5:]
            _update_slot_and_save(state, slot.slot_id, {
                "status": STATUS_FAILED,
                "error": res.error or f"exit {res.returncode}",
                "stderr_tail": "\n".join(stderr_tail),
                "duration_seconds": elapsed,
            }, self.output_root)
            self._emit(slot.slot_id, STATUS_FAILED, elapsed,
                       error=res.error)
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
        breaker = _CircuitBreaker(threshold=self.circuit_breaker_threshold)
        breaker_message: Optional[str] = None

        if total_to_run == 0:
            # Nothing to do (everything already completed, or empty plan).
            pass
        else:
            # Phase 1.5 bugfix Fix 3: lazy submission. Submitting all
            # futures up-front meant the executor's worker would grab
            # the next task BEFORE the main thread had a chance to
            # process the previous result and check the circuit
            # breaker — we'd over-shoot the threshold by `concurrency`
            # slots before cancellation took effect. Submitting only
            # `concurrency` futures at a time, and submitting the next
            # one when one finishes (unless the breaker has tripped),
            # bounds over-shoot to in-flight count.
            pending_iter = iter(pending)
            future_to_slot: dict[Future, Slot] = {}

            def _submit_next(pool: ThreadPoolExecutor) -> bool:
                """Submit the next pending slot to the pool. Returns
                True if a slot was submitted, False if the iterator
                is exhausted."""
                try:
                    nxt = next(pending_iter)
                except StopIteration:
                    return False
                fut = pool.submit(self._run_single, nxt, state)
                future_to_slot[fut] = nxt
                return True

            with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                # Prime the pool with up to `concurrency` futures.
                for _ in range(self.concurrency):
                    if not _submit_next(pool):
                        break

                while future_to_slot:
                    fut = next(as_completed(future_to_slot))
                    slot = future_to_slot.pop(fut)
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
                        _update_slot_and_save(state, slot.slot_id, {
                            "status": STATUS_FAILED, "error": res.error,
                        }, self.output_root)
                    results.append(res)

                    # Feed the result into the circuit breaker. A run
                    # of N same-class operational failures pauses the
                    # batch — we stop submitting new futures, the
                    # pool's __exit__ blocks until in-flight ones
                    # drain, and the loop exits cleanly.
                    breaker.record(
                        success=res.success,
                        error_class=_classify_error(res.error),
                    )
                    if breaker.tripped:
                        # Don't submit any more. In-flight ones will
                        # complete and be processed by subsequent
                        # iterations of this while-loop.
                        breaker_message = (
                            f"Batch paused after {breaker.threshold} "
                            f"consecutive operational failures of class "
                            f"{breaker.trip_class!r}. In-flight slots "
                            f"will drain; remaining unsubmitted slots "
                            f"stay pending. Resume with --resume after "
                            f"the underlying issue is resolved."
                        )
                        # Surface the trip both via on_progress (for
                        # programmatic clients) and stderr (for CLI users).
                        # Emit only on the first trip transition.
                        if breaker.consecutive == breaker.threshold:
                            n_in_flight = len(future_to_slot)
                            self._emit("__circuit_breaker__",
                                       "tripped", 0.0,
                                       error_class=breaker.trip_class,
                                       in_flight=n_in_flight,
                                       message=breaker_message)
                            try:
                                print(breaker_message, file=sys.stderr,
                                      flush=True)
                            except Exception:
                                pass
                            # Sentinel: bump consecutive once so we
                            # don't re-emit the message on every
                            # subsequent in-flight failure.
                            breaker.consecutive += 1
                    else:
                        # Healthy slot completion: refill the pool.
                        _submit_next(pool)

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
            circuit_breaker_tripped=breaker.tripped,
            circuit_breaker_class=breaker.trip_class,
            circuit_breaker_message=breaker_message,
        )
        return outcome
