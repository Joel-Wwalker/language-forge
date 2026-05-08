"""Phase 2 Stage D: end-to-end curation pipeline.

Takes a directory of generated languages (Phase 1.5 output) and runs
all of Stage A -> B -> C in sequence:

  1. Score every language directory in `--input`.
  2. Dedup the scored set.
  3. Insert results into the catalog DB at `--db`.

Reports a summary to stdout and writes the per-language quality
reports to a JSON file under `--reports-dir` (one file per batch run
for audit trail).

# IDEMPOTENCE

Re-running `curate` against the same input + DB doesn't double-insert
languages. The DB's UNIQUE constraint on `slot_id` protects from
duplicate inserts; each `curate` call still creates a NEW row in the
`batches` table so the audit trail shows when re-curation happened.

# RESUME

The pipeline is implicitly resumable because each stage can run
independently:

  - If you Ctrl+C during scoring, re-running starts scoring from the
    beginning (cheap — Stage A is read-only and fast).
  - If you Ctrl+C between scoring and DB insert, the reports JSON
    captures progress and the DB is unchanged.
  - If you Ctrl+C during DB insert, the transaction either committed
    (you see the rows on next list_languages) or rolled back. SQLite
    handles this; we don't need a per-row resume mechanism.

For long batches Phase 4 will likely add a resume flag that uses the
reports JSON as the cache. Phase 2 keeps the implementation simple.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

from .quality import (
    QualityReport,
    score_batch,
    write_batch_report,
    _aggregate,
)
from .dedup import dedup_languages, dedup_summary, result_to_dict
from .db import init_db, insert_batch_result, list_languages


def curate(input_dir: str | Path, db_path: str | Path, *,
           slot_plan_path: Optional[str | Path] = None,
           reports_dir: Optional[str | Path] = None,
           verbose: bool = True) -> dict:
    """Run the full Phase 2 pipeline against a directory of generated
    languages. Returns a summary dict suitable for printing.

    `slot_plan_path` is recorded in the `batches` table for audit
    purposes. If not provided, defaults to `<input_dir>/state.json`
    (Phase 1.5's batch metadata) or the input dir itself.

    `reports_dir` (optional) is where the per-language JSON reports
    file gets written. Defaults to `<input_dir>/.curation/`.
    """
    t0 = time.monotonic()
    input_dir = Path(input_dir).resolve()
    db_path = Path(db_path).resolve()
    if slot_plan_path is None:
        if (input_dir / "state.json").exists():
            slot_plan_path = input_dir / "state.json"
        else:
            slot_plan_path = input_dir
    slot_plan_path = Path(slot_plan_path).resolve()

    if reports_dir is None:
        reports_dir = input_dir / ".curation"
    reports_dir = Path(reports_dir).resolve()
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Stage A: score.
    if verbose:
        print(f"[curate] scoring batch in {input_dir}", flush=True)
    reports = score_batch(input_dir)
    if verbose:
        print(f"[curate]   scored {len(reports)} language(s)", flush=True)
    score_aggregate = _aggregate(reports)

    # Persist reports for audit trail.
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    reports_path = reports_dir / f"reports-{timestamp}.json"
    write_batch_report(reports, reports_path)
    if verbose:
        print(f"[curate]   wrote per-language reports to {reports_path}",
              flush=True)

    # Stage B: dedup.
    if verbose:
        print(f"[curate] deduplicating", flush=True)
    dedup_results = dedup_languages(reports)
    dsum = dedup_summary(dedup_results)
    if verbose:
        print(
            f"[curate]   {dsum['total_reports']} reports -> "
            f"{dsum['unique_languages']} unique "
            f"({dsum['duplicates_collapsed']} collapsed)",
            flush=True,
        )

    # Stage C: persist into DB.
    if verbose:
        print(f"[curate] inserting into {db_path}", flush=True)
    init_db(db_path)
    batch_id = insert_batch_result(
        db_path, input_dir, slot_plan_path, reports, dedup_results,
    )
    if verbose:
        print(f"[curate]   batch_id = {batch_id}", flush=True)

    # Final summary.
    final_langs = list_languages(db_path)
    summary = {
        "batch_id": batch_id,
        "input_dir": str(input_dir),
        "db_path": str(db_path),
        "reports_path": str(reports_path),
        "wall_clock_seconds": round(time.monotonic() - t0, 3),
        "scored": score_aggregate,
        "dedup": dsum,
        "db_total_languages": len(final_langs),
    }
    return summary


def _print_summary(summary: dict) -> None:
    """Pretty-print the summary returned by `curate()`."""
    print("=" * 60)
    print(f"CURATION COMPLETE (batch_id = {summary['batch_id']})")
    print(f"  input_dir:      {summary['input_dir']}")
    print(f"  db_path:        {summary['db_path']}")
    print(f"  reports_path:   {summary['reports_path']}")
    print(f"  wall:           {summary['wall_clock_seconds']:.1f}s")
    sa = summary.get("scored") or {}
    if sa.get("total"):
        print(
            f"  scored:         {sa['total']} total | "
            f"{sa['overall_passed']} passed | {sa['overall_failed']} failed"
        )
        print(
            f"                  by_family: {sa['by_family']}, "
            f"mean distinctiveness {sa['mean_distinctiveness']}, "
            f"mean coherence {sa['mean_coherence']}"
        )
    ds = summary.get("dedup") or {}
    if ds.get("total_reports"):
        print(
            f"  dedup:          {ds['total_reports']} -> "
            f"{ds['unique_languages']} unique "
            f"({ds['duplicates_collapsed']} collapsed; "
            f"largest group {ds['largest_group_size']})"
        )
    print(f"  db total:       {summary['db_total_languages']} language(s) in DB")


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m forge.catalog.curate",
        description="Phase 2 Stage D: score + dedup + persist a generated "
                    "batch into the catalog DB.",
    )
    parser.add_argument(
        "--input", required=True, type=Path,
        help="directory containing one or more generated languages "
             "(each as a subdirectory with resolved_spec.json)",
    )
    parser.add_argument(
        "--db", required=True, type=Path,
        help="SQLite catalog DB. Created if missing.",
    )
    parser.add_argument(
        "--slot-plan", type=Path, default=None,
        help="path to the slot plan JSON used to drive this batch "
             "(recorded in batches.slot_plan_path for audit). "
             "Defaults to <input>/state.json if present.",
    )
    parser.add_argument(
        "--reports-dir", type=Path, default=None,
        help="directory to write per-language JSON reports into. "
             "Defaults to <input>/.curation/.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="suppress progress output (final summary still printed)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: --input directory does not exist: {args.input}",
              file=sys.stderr)
        return 2

    try:
        summary = curate(
            args.input, args.db,
            slot_plan_path=args.slot_plan,
            reports_dir=args.reports_dir,
            verbose=not args.quiet,
        )
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print()
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(_main())
