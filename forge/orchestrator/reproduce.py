"""Reproduce a prior generation from its `generation_summary.json`.

Phase 0.5 (production roadmap): every generation records a seed in its
summary file. `reproduce_from_summary(path)` reads that summary plus the
sibling `resolved_spec.json` and re-runs `generate_all` with the same
seed and spec so a flaky failure can be replayed.

The Anthropic API doesn't expose a seed parameter, so reproductions are
NOT byte-identical to the original — but the structural choices (which
features got picked, which themes got applied, what kata pack got
loaded) are deterministic given the spec, and our local randomness
(crossbreeding, future planners) honors the seed.

Used as a library and as a CLI:

    from forge.orchestrator.reproduce import reproduce_from_summary
    reproduce_from_summary("generated/oldlang/generation_summary.json")

    # or
    python -m forge.orchestrator.reproduce generated/oldlang/generation_summary.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional


def reproduce_from_summary(summary_path: str | Path,
                           output_root: Optional[str | Path] = None,
                           *,
                           client=None) -> Path:
    """Re-run a generation from a saved summary.

    Args:
      summary_path: path to a `generation_summary.json` file. Must have
                    a sibling `resolved_spec.json` (always emitted by
                    `generate_all`).
      output_root:  where to write the regenerated language. Defaults
                    to a sibling directory `<original>.reproduce` so the
                    original isn't overwritten (mostly relevant when the
                    user is comparing the two for debugging).
      client:       LLM client to use. Defaults to `make_client()`.

    Returns the path of the regenerated language directory.
    """
    summary_path = Path(summary_path).resolve()
    if not summary_path.exists():
        raise FileNotFoundError(f"no summary at {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    spec_path = summary_path.parent / "resolved_spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(
            f"no resolved_spec.json sibling of {summary_path} — can't reproduce"
        )
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    seed = summary.get("seed")

    # Default output to a `.reproduce` sibling directory so the original
    # generation isn't clobbered. Caller can override.
    if output_root is None:
        original_lang_dir = summary_path.parent
        output_root = original_lang_dir.parent
        # Tweak the lang_name so generate_all writes to a fresh dir.
        spec = dict(spec)
        spec["lang_name"] = f"{spec['lang_name']}.reproduce"

    if client is None:
        from .providers import make_client
        client = make_client()

    from .generator import generate_all
    return generate_all(spec, output_root=output_root, client=client, seed=seed)


def _cli_main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="forge.reproduce",
        description="Re-run a generation from its generation_summary.json.",
    )
    p.add_argument("summary",
                   help="path to generation_summary.json (or its parent dir)")
    p.add_argument("--output-root", default=None,
                   help="override output directory (default: <orig>.reproduce)")
    args = p.parse_args(argv)
    summary = Path(args.summary)
    if summary.is_dir():
        summary = summary / "generation_summary.json"
    try:
        out = reproduce_from_summary(summary, output_root=args.output_root)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"reproduced -> {out}")
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(_cli_main())
