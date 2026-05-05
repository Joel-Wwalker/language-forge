"""Subprocess isolation for batch generation.

Phase 0.1 (production roadmap): when generating many languages back-to-back
in a single Python process, the in-process generator caches generated
language modules in `sys.modules`. Two languages with the same module
name (or even with overlapping helper names that touch the runtime) can
silently corrupt each other's outputs.

The fix is to run each generation in a clean Python subprocess. The
subprocess imports `forge.orchestrator.generator`, runs `generate_all`,
writes outputs to disk, and exits — taking its dirty `sys.modules` with
it. The parent process orchestrates many of these.

This module exposes:
    run_one(spec, output_root, *, seed=None, timeout=None, env=None)
        -> SubprocessResult

    run_batch(specs, output_root, *, max_workers=5, ...)
        -> list[SubprocessResult]

Each result records: success/fail, stdout/stderr captured from the child,
the language directory, the path to its generation_summary.json (if it
got written), and wall-clock duration.

The acceptance criterion from the roadmap: generate 10 languages in a
single Python session. Modules don't bleed; no module-name collisions.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SubprocessResult:
    slot_id: str
    lang_name: str
    success: bool
    duration_seconds: float
    lang_dir: Optional[str] = None
    summary_path: Optional[str] = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error: Optional[str] = None  # one-line summary if subprocess crashed


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------

# This module is invokable as `python -m forge.orchestrator.subprocess_runner
# --slot <slot.json>` so the parent can spawn it directly. The slot JSON
# carries everything the worker needs:
#   { "spec": { ... resolved_spec ... },
#     "output_root": "<path>",
#     "seed": <int|null>,
#     "skip_resolver": true (if spec is already resolved),
#     "client_provider": "api" | "claude_cli" | null }
class _LazyLLMClient:
    """Defers `make_client()` until the first `call_*` method is used.

    Phase 0 closeout #6: templated language families (s_expression,
    stack_based) don't make any LLM calls — but the subprocess worker
    used to instantiate `LLMClient(...)` at startup, which blows up
    without `ANTHROPIC_API_KEY` even for runs that would never have
    called the API. Lazy instantiation lets templated batches run
    without API credentials.

    The proxy mimics the surface `_LLMLike` protocol: log_dir, model,
    telemetry, plus call_code / call_json / call_chat. Anything else
    (e.g. an inner `client.client` attribute on the API path) falls
    back to lazy resolution via __getattr__.
    """
    def __init__(self, provider: Optional[str] = None,
                 log_dir: Optional[str | os.PathLike] = None):
        self._provider = provider
        self._log_dir = log_dir
        self._real = None
        # These two are read frequently by callers without forcing
        # instantiation; pre-populate plausibly-true values.
        self.telemetry = None     # set later by generate_all via attach()

    @property
    def log_dir(self):
        return self._log_dir

    @log_dir.setter
    def log_dir(self, v):
        # generate_all sometimes back-fills log_dir; mirror that.
        self._log_dir = v
        if self._real is not None:
            self._real.log_dir = v

    @property
    def model(self):
        # Real clients expose a `.model` attribute (e.g. "claude-sonnet-4-5").
        # Resolve lazily; some telemetry code reads this without making a call.
        if self._real is not None:
            return getattr(self._real, "model", "unknown")
        return "lazy:unresolved"

    def _materialize(self):
        if self._real is None:
            from .providers import make_client
            self._real = make_client(self._provider, log_dir=self._log_dir)
            # Forward any telemetry that was attached BEFORE materialization.
            if self.telemetry is not None:
                self._real.telemetry = self.telemetry
        return self._real

    def call_code(self, *a, **kw):
        return self._materialize().call_code(*a, **kw)

    def call_json(self, *a, **kw):
        return self._materialize().call_json(*a, **kw)

    def call_chat(self, *a, **kw):
        return self._materialize().call_chat(*a, **kw)

    def __getattr__(self, name):
        # Catch-all for anything else the generator might poke at.
        # Avoid infinite recursion on the underscore-prefixed internals.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._materialize(), name)


def _worker_main(slot_path: str) -> int:
    """Subprocess entry. Reads a slot JSON, runs `generate_all`, writes
    outputs to disk, returns 0 on success. Any exception is caught,
    serialized to JSON on stdout, and a nonzero exit code is returned
    so the parent can attribute the failure correctly."""
    try:
        slot = json.loads(Path(slot_path).read_text(encoding="utf-8"))
        spec = slot["spec"]
        output_root = slot["output_root"]
        seed = slot.get("seed")
        client_provider = slot.get("client_provider")
        skip_resolver = slot.get("skip_resolver", True)

        # Phase 0 closeout #6: lazy client instantiation. Templated
        # families never call .call_* and therefore never materialize
        # the real client — runs without ANTHROPIC_API_KEY in those
        # cases, instead of failing at startup.
        client = _LazyLLMClient(client_provider)

        # If the slot says skip_resolver=False, run the resolver first so
        # batch tooling that has only options (not a resolved spec) can
        # still drive this worker. Today's batch path passes resolved
        # specs, so this is mostly future-proofing.
        if not skip_resolver:
            from forge.orchestrator.resolver import resolve
            spec = resolve(spec, client=client)

        from forge.orchestrator.generator import generate_all
        out_dir = generate_all(spec, output_root=output_root,
                               client=client, seed=seed)
        # Echo the result location on stdout for the parent to parse.
        # The parent ALSO reads files from out_dir directly; this is just
        # an extra signal.
        print(json.dumps({
            "ok": True,
            "lang_dir": str(out_dir),
            "summary_path": str(out_dir / "generation_summary.json"),
        }))
        return 0
    except Exception as e:
        # Surface the failure on stderr so the parent can attribute it.
        import traceback
        traceback.print_exc()
        print(json.dumps({
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }))
        return 1


# ---------------------------------------------------------------------------
# Parent-side API
# ---------------------------------------------------------------------------

def run_one(spec: dict, output_root: str | Path, *,
            slot_id: Optional[str] = None,
            seed: Optional[int] = None,
            timeout: Optional[float] = None,
            client_provider: Optional[str] = None,
            skip_resolver: bool = True,
            env: Optional[dict] = None) -> SubprocessResult:
    """Run a single generation in an isolated subprocess.

    Returns a `SubprocessResult` whether the run succeeded or not. The
    parent never raises on subprocess failure — it records the error
    so callers can iterate over a batch's results and decide which
    slots to retry."""
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    lang_name = spec.get("lang_name", "unknown")
    slot_id = slot_id or lang_name

    # Write the slot to a temp JSON file the subprocess will read. This
    # avoids command-line-length issues on Windows for big specs.
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".slot.json", delete=False, encoding="utf-8",
    ) as f:
        json.dump({
            "spec": spec,
            "output_root": str(output_root),
            "seed": seed,
            "client_provider": client_provider,
            "skip_resolver": skip_resolver,
        }, f)
        slot_path = f.name

    cmd = [
        sys.executable, "-m", "forge.orchestrator.subprocess_runner",
        "--slot", slot_path,
    ]

    # Inherit env but allow overrides; PYTHONPATH must include the
    # workspace root so `forge` resolves.
    sub_env = dict(os.environ)
    sub_env["PYTHONPATH"] = (
        str(WORKSPACE_ROOT) + os.pathsep + sub_env.get("PYTHONPATH", "")
    )
    if env:
        sub_env.update(env)

    t0 = time.monotonic()
    try:
        cp = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, encoding="utf-8", errors="replace",
            env=sub_env, cwd=str(WORKSPACE_ROOT),
        )
    except subprocess.TimeoutExpired:
        return SubprocessResult(
            slot_id=slot_id, lang_name=lang_name, success=False,
            duration_seconds=time.monotonic() - t0,
            error=f"timeout after {timeout}s",
            returncode=-1,
        )
    finally:
        try:
            Path(slot_path).unlink(missing_ok=True)
        except Exception:
            pass

    duration = time.monotonic() - t0
    success = cp.returncode == 0
    lang_dir = output_root / lang_name
    summary = lang_dir / "generation_summary.json"
    return SubprocessResult(
        slot_id=slot_id,
        lang_name=lang_name,
        success=success,
        duration_seconds=duration,
        lang_dir=str(lang_dir) if lang_dir.exists() else None,
        summary_path=str(summary) if summary.exists() else None,
        stdout=cp.stdout,
        stderr=cp.stderr,
        returncode=cp.returncode,
        error=None if success else (cp.stderr.strip().splitlines()[-1] if cp.stderr.strip() else f"exit {cp.returncode}"),
    )


def run_batch(specs: list[dict], output_root: str | Path, *,
              max_workers: int = 5,
              seeds: Optional[list[int]] = None,
              timeout: Optional[float] = None,
              client_provider: Optional[str] = None,
              skip_resolver: bool = True,
              on_progress=None) -> list[SubprocessResult]:
    """Run multiple generations in parallel subprocesses.

    Args:
      specs: list of resolved spec dicts (each must include `lang_name`).
      output_root: parent dir for all generated languages.
      max_workers: how many subprocesses to run in parallel. Default 5
                   keeps API rate limits manageable.
      seeds: optional per-spec seed list (must match length of `specs`).
      timeout: per-subprocess timeout in seconds.
      on_progress: optional callback(slot_id, status, elapsed_seconds)
                   where status is "started" / "ok" / "failed".

    Returns one `SubprocessResult` per input spec, in the same order
    as `specs`."""
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if seeds is None:
        seeds = [None] * len(specs)
    if len(seeds) != len(specs):
        raise ValueError("len(seeds) must equal len(specs)")

    results: list[Optional[SubprocessResult]] = [None] * len(specs)

    def _do_one(idx: int) -> SubprocessResult:
        spec = specs[idx]
        seed = seeds[idx]
        slot_id = spec.get("lang_name", f"slot_{idx}")
        if on_progress:
            try: on_progress(slot_id, "started", 0.0)
            except Exception: pass
        t0 = time.monotonic()
        res = run_one(
            spec, output_root, slot_id=slot_id, seed=seed,
            timeout=timeout, client_provider=client_provider,
            skip_resolver=skip_resolver,
        )
        if on_progress:
            try:
                on_progress(slot_id, "ok" if res.success else "failed",
                            time.monotonic() - t0)
            except Exception:
                pass
        return res

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_idx = {pool.submit(_do_one, i): i for i in range(len(specs))}
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            try:
                results[idx] = fut.result()
            except Exception as e:
                results[idx] = SubprocessResult(
                    slot_id=specs[idx].get("lang_name", f"slot_{idx}"),
                    lang_name=specs[idx].get("lang_name", "unknown"),
                    success=False,
                    duration_seconds=0.0,
                    error=f"{type(e).__name__}: {e}",
                )

    # Type narrowing: every entry has been written.
    return [r for r in results if r is not None]   # type: ignore[return-value]


def write_batch_summary(results: list[SubprocessResult],
                        output_root: str | Path) -> Path:
    """Write a `batch_summary.json` aggregating per-slot results.

    Format:
      {
        "total": N, "succeeded": K, "failed": N-K,
        "wall_clock_seconds": float,
        "results": [ ...one dict per slot... ],
      }
    """
    output_root = Path(output_root).resolve()
    succ = sum(1 for r in results if r.success)
    blob = {
        "total": len(results),
        "succeeded": succ,
        "failed": len(results) - succ,
        "wall_clock_seconds": round(sum(r.duration_seconds for r in results), 3),
        "results": [asdict(r) for r in results],
    }
    out = output_root / "batch_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    os.replace(tmp, out)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--slot", required=True,
                   help="path to slot.json with spec/output_root/seed")
    args = p.parse_args()
    return _worker_main(args.slot)


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(_main())
