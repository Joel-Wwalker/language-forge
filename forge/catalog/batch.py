"""CLI entry point for batch generation.

Usage:
    python -m forge.catalog.batch --plan slots/v1_phase1.json --output catalog_raw/
    python -m forge.catalog.batch --plan ... --output ... --resume
    python -m forge.catalog.batch --plan ... --output ... --concurrency 8 --timeout-per-slot 900

This is intentionally a thin wrapper around `runner.BatchRunner`. The
runner has the testable behavior; this module just parses argv,
configures progress logging, and surfaces the outcome to stdout.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from forge.catalog.planner import make_slot_plan, SlotPlanError
from forge.catalog.runner import (
    BatchRunner, BatchOutcome,
    STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED,
)


def _format_progress(slot_id: str, status: str, elapsed: float,
                     extra: dict[str, Any]) -> str:
    """One log line per status change. Format chosen so a tail-of-log
    pipe gives a readable progress feed."""
    ts = time.strftime("%H:%M:%S")
    if status == STATUS_RUNNING:
        return f"[{ts}] START   {slot_id}"
    if status == STATUS_COMPLETED:
        lang_dir = extra.get("lang_dir") or "?"
        return f"[{ts}] OK      {slot_id} ({elapsed:.1f}s) -> {lang_dir}"
    if status == STATUS_FAILED:
        err = (extra.get("error") or "?")[:120]
        return f"[{ts}] FAILED  {slot_id} ({elapsed:.1f}s) {err}"
    return f"[{ts}] {status}  {slot_id} ({elapsed:.1f}s)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m forge.catalog.batch",
        description="Run a slot plan: generate every slot to <output>/<slot_id>/.",
    )
    parser.add_argument(
        "--plan", required=True, type=Path,
        help="path to a slot plan JSON file (see forge/catalog/slots/)",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="output directory; per-slot dirs land at <output>/<slot_id>/",
    )
    parser.add_argument(
        "--concurrency", type=int, default=4,
        help="parallel slot count (default: 4)",
    )
    parser.add_argument(
        "--timeout-per-slot", type=float, default=600.0,
        help="per-subprocess wall-clock cap, seconds (default: 600 = 10 min)",
    )
    parser.add_argument(
        "--client-provider", choices=["api", "claude_cli"], default=None,
        help="LLM provider override (default: auto-detect)",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="skip slots already marked completed/failed in state.json. "
             "Use this after Ctrl+C or a crash to pick up where you left off.",
    )
    args = parser.parse_args(argv)

    # Load plan first so a malformed plan fails fast before we spin up
    # any subprocesses.
    try:
        plan = make_slot_plan(args.plan)
    except SlotPlanError as e:
        print(f"ERROR: invalid slot plan:\n{e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"loaded {len(plan)} slot(s) from {args.plan}")

    runner = BatchRunner(
        plan=plan,
        output_root=args.output,
        concurrency=args.concurrency,
        timeout_per_slot=args.timeout_per_slot,
        client_provider=args.client_provider,
        plan_path=args.plan,
        on_progress=lambda *a: print(_format_progress(*a), flush=True),
    )

    print(f"output_root: {args.output.resolve()}")
    print(f"concurrency: {args.concurrency}, timeout/slot: "
          f"{args.timeout_per_slot:.0f}s, resume: {args.resume}")
    print()

    outcome = runner.run(resume=args.resume)

    print()
    print("=" * 60)
    print(f"BATCH COMPLETE")
    print(f"  total slots:        {outcome.total}")
    print(f"  completed:          {outcome.completed}")
    print(f"  failed:             {outcome.failed}")
    print(f"  skipped (resumed):  {outcome.skipped_resumed}")
    print(f"  pass rate:          {outcome.pass_rate:.1%}")
    print(f"  wall clock:         {outcome.wall_clock_seconds:.1f}s")
    print(f"  state:              {outcome.state_path}")
    print(f"  summary:            {outcome.summary_path}")

    # Exit code: 0 if everything succeeded, 1 if any failures, 2 for
    # config/plan errors (handled above).
    return 0 if outcome.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
