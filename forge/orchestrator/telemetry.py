"""Per-generation telemetry recorder.

Captures: every LLM call's tokens + duration, every repair attempt, total
wall-clock time, final canonical/kata pass rates, errors, and the seed
used. Writes a `generation_summary.json` to the language directory at the
end of `generate_all` so batch runs are debuggable without grep-ing 500
log directories.

Roadmap reference: forge-production-roadmap.md Phase 0.4.

Design choices:
  - Recorder is THREAD-SAFE because `generate_all` runs components on a
    ThreadPoolExecutor. A simple `threading.Lock` around the append paths
    is enough — we never iterate concurrently with appends.
  - LLM clients RECORD INTO the active recorder via a `telemetry` attribute
    that's set by `generate_all`. If the attribute is None, calls are
    free-running (no overhead, no recording). This keeps the test paths
    that don't care about telemetry uncontaminated.
  - The summary dict is JSON-safe by construction: all fields are int /
    float / str / list-of-dict-of-primitives.

The contract surfaced to consumers:
    generation_summary.json = {
        "lang_name": str,
        "seed": int | None,
        "started_at": ISO8601 str,
        "wall_clock_seconds": float,
        "llm": {
            "total_calls": int,
            "total_input_tokens": int,
            "total_output_tokens": int,
            "by_tag": { tag: { calls, input_tokens, output_tokens, duration } },
            "calls": [ { tag, model, input_tokens, output_tokens, duration,
                         attempts, success, error } ],
        },
        "repair": {
            "total_attempts": int,
            "by_component": { component: attempts },
            "attempts": [ { component, attempt, success } ],
        },
        "canonical_tests": { "passed": int, "total": int, "pass_rate": float } | null,
        "kata_pack": { "passed": int, "total": int, "pass_rate": float } | null,
        "errors": [ { stage, message } ],
        "generator_version": str,
    }
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


# Bumped manually when we change the generation pipeline in a way that
# would invalidate prior catalog entries. Stamped into every summary so
# downstream tools can identify and regenerate stale entries.
GENERATOR_VERSION = "0.4.0"


@dataclass
class LLMCallRecord:
    """One LLM round-trip. Captured inside `LLMClient.call_*`."""
    tag: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0.0
    attempts: int = 1               # how many retries it took
    success: bool = True
    error: Optional[str] = None     # one-line summary of last exception


@dataclass
class RepairAttemptRecord:
    """One repair retry. Captured inside `repair_run`."""
    component: str
    attempt: int
    success: bool = False
    duration_seconds: float = 0.0


@dataclass
class ErrorRecord:
    """A non-fatal error caught and continued past, OR the fatal error
    that ended the run. `stage` is "resolver" / "generator:tests" /
    "verifier" / etc."""
    stage: str
    message: str


@dataclass
class TelemetryRecorder:
    """Mutable, thread-safe sink. Created at the start of `generate_all`,
    attached to the LLM client, and read at the end to write the summary.

    Phase 0 closeout #2 (incremental writes): if `events_path` is set,
    every record_*  call also appends a JSON line to that path AS IT
    HAPPENS. If `generate_all` crashes mid-run, the events file is the
    survival record — it captures everything that completed before the
    crash, so batch-mode debugging has diagnostic data even when no
    `generation_summary.json` ever gets written.

    The events file format is one JSON object per line, each shaped as:
        {"event": "llm_call",  "timestamp": <iso>, ...rec_fields...}
        {"event": "repair",    "timestamp": <iso>, ...rec_fields...}
        {"event": "error",     "timestamp": <iso>, ...rec_fields...}
        {"event": "canonical", "timestamp": <iso>, "passed": ..., "total": ...}
        {"event": "kata",      "timestamp": <iso>, "passed": ..., "total": ...}

    Reading back: aggregate the file with `events_to_summary(path)`."""
    lang_name: str
    seed: Optional[int] = None
    started_at_monotonic: float = field(default_factory=time.monotonic)
    started_at_iso: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    llm_calls: list[LLMCallRecord] = field(default_factory=list)
    repair_attempts: list[RepairAttemptRecord] = field(default_factory=list)
    errors: list[ErrorRecord] = field(default_factory=list)
    canonical_tests: Optional[dict] = None
    kata_pack: Optional[dict] = None
    components: dict = field(default_factory=dict)        # name -> {duration, llm_calls, success}
    cache_hits: int = 0
    events_path: Optional[Path] = None                    # set by generate_all
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ---- internal: append a JSON event line (atomic per-line on POSIX
    # and Windows because each `write` of <PIPE_BUF bytes is atomic and
    # a JSON line easily fits in 4 KiB). Holds the lock while writing
    # so concurrent recorders don't interleave half-lines. ----

    def _emit_event(self, event_type: str, payload: dict) -> None:
        if self.events_path is None:
            return
        record = {"event": event_type,
                  "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  **payload}
        try:
            with open(self.events_path, "a", encoding="utf-8") as fp:
                fp.write(json.dumps(record, default=str) + "\n")
        except Exception:
            # Telemetry must NEVER break generation. Silently drop on
            # I/O error (e.g. disk full); the in-memory recorder still
            # has the data and end-of-run summary write will surface it.
            pass

    def attach_events_file(self, path: str | os.PathLike) -> None:
        """Begin streaming events to `path` (one JSON line per record).

        Truncates any existing file at this path so a re-run from the
        same lang_dir starts fresh — the old events were for a previous
        attempt and would confuse aggregators."""
        self.events_path = Path(path)
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        self.events_path.write_text("", encoding="utf-8")
        # First event records the run's metadata so a partial events
        # file is self-describing without the summary.
        self._emit_event("run_started", {
            "lang_name": self.lang_name,
            "seed": self.seed,
            "started_at": self.started_at_iso,
            "generator_version": GENERATOR_VERSION,
        })

    # ---- public append-only API (thread-safe) ----

    def record_llm_call(self, rec: LLMCallRecord) -> None:
        with self._lock:
            self.llm_calls.append(rec)
            if rec.tag == "resolver-cache-hit":
                self.cache_hits += 1
        # Emit AFTER releasing the lock to keep critical sections short.
        self._emit_event("llm_call", asdict(rec))

    def record_repair(self, rec: RepairAttemptRecord) -> None:
        with self._lock:
            self.repair_attempts.append(rec)
        self._emit_event("repair", asdict(rec))

    def record_error(self, stage: str, message: str) -> None:
        line = str(message).splitlines()[0][:500] if message else ""
        with self._lock:
            self.errors.append(ErrorRecord(stage=stage, message=line))
        self._emit_event("error", {"stage": stage, "message": line})

    def record_component(self, name: str, duration_seconds: float, *,
                         success: bool = True, llm_calls_made: int = 0) -> None:
        """Record a per-component breakdown (Phase 0 closeout #4).

        Called by `generate_all` after each component finishes so the
        summary can answer 'which components took how long' / 'which
        component spent the most LLM tokens'."""
        entry = {
            "duration_seconds": round(float(duration_seconds), 3),
            "success": bool(success),
            "llm_calls": int(llm_calls_made),
        }
        with self._lock:
            self.components[name] = entry
        self._emit_event("component", {"name": name, **entry})

    def set_canonical_results(self, passed: int, total: int) -> None:
        result = {
            "passed": int(passed),
            "total": int(total),
            "pass_rate": (float(passed) / total) if total else 0.0,
        }
        with self._lock:
            self.canonical_tests = result
        self._emit_event("canonical", result)

    def set_kata_results(self, passed: int, total: int) -> None:
        result = {
            "passed": int(passed),
            "total": int(total),
            "pass_rate": (float(passed) / total) if total else 0.0,
        }
        with self._lock:
            self.kata_pack = result
        self._emit_event("kata", result)

    # ---- summary serialization ----

    def to_summary_dict(self) -> dict:
        """Build the JSON-safe summary dict. Pure function of the
        recorder's state at call time; cheap enough to call repeatedly."""
        with self._lock:
            wall = time.monotonic() - self.started_at_monotonic
            by_tag: dict[str, dict] = {}
            for c in self.llm_calls:
                slot = by_tag.setdefault(c.tag, {
                    "calls": 0, "input_tokens": 0, "output_tokens": 0,
                    "duration_seconds": 0.0,
                })
                slot["calls"] += 1
                slot["input_tokens"] += c.input_tokens
                slot["output_tokens"] += c.output_tokens
                slot["duration_seconds"] += c.duration_seconds

            by_component: dict[str, int] = {}
            for r in self.repair_attempts:
                by_component[r.component] = by_component.get(r.component, 0) + 1

            # Cost-saved estimate: cache hits avoided one LLM round-trip
            # each. We don't know the actual saved tokens (would need
            # before/after baselining), so just expose the count.
            return {
                "lang_name": self.lang_name,
                "seed": self.seed,
                "started_at": self.started_at_iso,
                "wall_clock_seconds": round(wall, 3),
                "generator_version": GENERATOR_VERSION,
                "llm": {
                    "total_calls": len(self.llm_calls),
                    "total_input_tokens": sum(c.input_tokens for c in self.llm_calls),
                    "total_output_tokens": sum(c.output_tokens for c in self.llm_calls),
                    "by_tag": by_tag,
                    "calls": [asdict(c) for c in self.llm_calls],
                },
                "repair": {
                    "total_attempts": len(self.repair_attempts),
                    "by_component": by_component,
                    "attempts": [asdict(r) for r in self.repair_attempts],
                },
                "components": dict(self.components),
                "cache_hits": self.cache_hits,
                "canonical_tests": self.canonical_tests,
                "kata_pack": self.kata_pack,
                "errors": [asdict(e) for e in self.errors],
            }

    def write_summary(self, lang_dir: str | os.PathLike) -> Path:
        """Write `generation_summary.json` to `lang_dir`. Returns the path.

        Atomic via .tmp + os.replace so a partial write never corrupts a
        prior summary that batch tooling might be reading concurrently.
        """
        path = Path(lang_dir) / "generation_summary.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.to_summary_dict(), indent=2),
                       encoding="utf-8")
        os.replace(tmp, path)
        return path


# ---------------------------------------------------------------------------
# Helper: attach telemetry to a client (used by generate_all + tests)
# ---------------------------------------------------------------------------

def attach(client, recorder: TelemetryRecorder) -> None:
    """Attach a recorder to any LLM client. Idempotent.

    The client's `call_code` / `call_json` / `call_chat` methods check
    `getattr(self, "telemetry", None)` and append into it. This stays
    out of the way for clients that don't care (default: None)."""
    client.telemetry = recorder


def detach(client) -> None:
    """Remove the recorder. Useful for tests that share a client."""
    if hasattr(client, "telemetry"):
        client.telemetry = None


# ---------------------------------------------------------------------------
# Events-file recovery (Phase 0 closeout #2)
# ---------------------------------------------------------------------------

def events_to_summary(events_path: str | os.PathLike) -> dict:
    """Aggregate a `generation_events.jsonl` into a partial summary dict.

    Used for crash recovery: if `generate_all` died mid-flight, the
    summary on disk may be missing or stale, but the events file has
    every record that was emitted before the crash. This function
    reconstructs the summary shape from those events so batch tooling
    can still answer "what completed before the crash?".

    Tolerates malformed lines (skips them with a counter)."""
    path = Path(events_path)
    if not path.exists():
        return {}

    llm_calls: list[dict] = []
    repair_attempts: list[dict] = []
    components: dict = {}
    errors: list[dict] = []
    canonical = None
    kata = None
    cache_hits = 0
    meta: dict = {}
    malformed_count = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except Exception:
            malformed_count += 1
            continue
        kind = ev.get("event")
        if kind == "run_started":
            meta = {k: ev.get(k) for k in
                    ("lang_name", "seed", "started_at", "generator_version")}
        elif kind == "llm_call":
            llm_calls.append({k: v for k, v in ev.items()
                              if k not in ("event", "timestamp")})
            if ev.get("tag") == "resolver-cache-hit":
                cache_hits += 1
        elif kind == "repair":
            repair_attempts.append({k: v for k, v in ev.items()
                                    if k not in ("event", "timestamp")})
        elif kind == "component":
            name = ev.get("name")
            if name:
                components[name] = {k: ev[k] for k in
                                    ("duration_seconds", "success", "llm_calls")
                                    if k in ev}
        elif kind == "error":
            errors.append({k: v for k, v in ev.items()
                           if k not in ("event", "timestamp")})
        elif kind == "canonical":
            canonical = {k: ev[k] for k in ("passed", "total", "pass_rate")
                         if k in ev}
        elif kind == "kata":
            kata = {k: ev[k] for k in ("passed", "total", "pass_rate")
                    if k in ev}

    by_tag: dict[str, dict] = {}
    for c in llm_calls:
        slot = by_tag.setdefault(c.get("tag", "?"), {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "duration_seconds": 0.0,
        })
        slot["calls"] += 1
        slot["input_tokens"] += int(c.get("input_tokens") or 0)
        slot["output_tokens"] += int(c.get("output_tokens") or 0)
        slot["duration_seconds"] += float(c.get("duration_seconds") or 0.0)

    by_component: dict[str, int] = {}
    for r in repair_attempts:
        by_component[r["component"]] = by_component.get(r["component"], 0) + 1

    return {
        "lang_name": meta.get("lang_name"),
        "seed": meta.get("seed"),
        "started_at": meta.get("started_at"),
        "generator_version": meta.get("generator_version", GENERATOR_VERSION),
        "recovered_from_events": True,
        "malformed_event_lines": malformed_count,
        "llm": {
            "total_calls": len(llm_calls),
            "total_input_tokens": sum(int(c.get("input_tokens") or 0) for c in llm_calls),
            "total_output_tokens": sum(int(c.get("output_tokens") or 0) for c in llm_calls),
            "by_tag": by_tag,
            "calls": llm_calls,
        },
        "repair": {
            "total_attempts": len(repair_attempts),
            "by_component": by_component,
            "attempts": repair_attempts,
        },
        "components": components,
        "cache_hits": cache_hits,
        "canonical_tests": canonical,
        "kata_pack": kata,
        "errors": errors,
    }
