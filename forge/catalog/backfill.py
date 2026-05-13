"""Phase 3 follow-up: one-time CLI to rehydrate customization
columns on existing catalog rows from the original slot plan.

# WHY THIS EXISTS

Phase 1.5's resolver consumes the spec's `theme` / `phrasebook`
fields into concrete `keyword_overrides` + creative content. The
resolver returns a spec where `theme` and `phrasebook` are absent;
the runner inserts that into the DB; result: those columns are NULL
even when the original slot plan had them set.

The runner SHOULD also write a `slot.json` next to each generated
language preserving the original input. The Phase 1.5 final batch
(`catalog_raw_gate2_v2/`) doesn't contain `slot.json` files, which
suggests a runner bug worth hardening in Phase 4.

This CLI fills the historical gap. It reads the slot plan file and
updates DB rows whose customization columns are NULL.

# USAGE

    python -m forge.catalog.backfill \
        --db catalog.db \
        --plan forge/catalog/slots/v1_phase1.json

    # To overwrite even non-NULL columns (use with care):
    python -m forge.catalog.backfill \
        --db catalog.db \
        --plan forge/catalog/slots/v1_phase1.json \
        --overwrite
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from .db import backfill_customization_from_plan


def _main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m forge.catalog.backfill",
        description="Rehydrate persona/era/theme/phrasebook columns "
                    "on catalog rows from the original slot plan.",
    )
    parser.add_argument("--db", required=True, type=Path,
                        help="catalog SQLite DB to update")
    parser.add_argument("--plan", required=True, type=Path,
                        help="slot plan JSON whose entries supply the "
                             "original customization values")
    parser.add_argument("--overwrite", action="store_true",
                        help="overwrite non-NULL columns too "
                             "(default: only fill NULLs)")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"ERROR: --db does not exist: {args.db}", file=sys.stderr)
        return 2
    if not args.plan.exists():
        print(f"ERROR: --plan does not exist: {args.plan}", file=sys.stderr)
        return 2

    result = backfill_customization_from_plan(
        args.db, args.plan, overwrite=args.overwrite,
    )
    print(f"backfill complete:")
    print(f"  updated rows:           {result['updated']}")
    print(f"  skipped (already set):  {result['skipped_already_set']}")
    print(f"  skipped (no plan match): {result['skipped_no_match']}")
    print(f"  plan slots seen:        {result['plan_slots']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
