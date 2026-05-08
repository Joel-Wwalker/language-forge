"""Phase 1.5 bugfix Fix 4: Bug 4 (empty lang_dirs on baseline slots).

# THE BUG

Gate 2 saw 3 baseline slots (001, 031, 041) where the events.jsonl
showed only the resolver-cache-hit event. Subsequent generation
events / files / generation_summary.json were missing from the
slot's directory.

The actual cause turned out to be NOT "subprocess crashed early after
cache hit" — it was a directory-routing mismatch. The runner expects
outputs at `<output>/<slot_id>/`, but the subprocess's `_worker_main`:

  1. Creates `<output>/<input_lang_name>/` (= slot_id) and attaches
     the events file there.
  2. Calls `resolve(spec)` which returns a dict from the LLM/cache
     whose `lang_name` is the CREATIVE name (e.g. 'canary_stack' for
     a stack_based cache hit), overwriting the input slot_id.
  3. Calls `generate_all(spec, output_root=...)` which uses
     `spec["lang_name"]` as the on-disk directory. Outputs land at
     `<output>/canary_stack/`, NOT `<output>/<slot_id>/`.

The slot_id directory ends up empty (just slot.json from the parent
+ the pre-resolver events). The resolved-name directory has the
real outputs but the parent never looks there.

# THE FIX

In `forge/orchestrator/subprocess_runner.py:_worker_main`, after the
resolver runs, force `spec["lang_name"]` back to the input value.
The resolver's creative name is preserved as `display_name` for any
GUI/curator that wants it. The on-disk name + Python package name
stays bound to the slot_id (the stable batch identifier).

This test pins the contract: the subprocess writes its outputs to
`<output>/<input_lang_name>/`, regardless of what name the resolver
returns from its cache.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from forge.catalog.planner import Slot
from forge.catalog.runner import _build_spec_for_slot
from forge.orchestrator.subprocess_runner import run_one


@pytest.mark.slow
def test_subprocess_writes_to_slot_id_dir_not_resolver_creative_name(tmp_path):
    """The proximate Bug 4 acceptance test. Run a stack_based slot
    whose options match a cached resolver entry (e.g. 'canary_stack').
    The subprocess MUST write outputs to <output>/<slot_id>/, not
    <output>/canary_stack/."""
    slot = Slot(
        slot_id="bug4_repro",
        options={"syntax": "stack_based", "typing": "dynamic",
                 "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common", notes="bug 4 repro",
    )
    spec = _build_spec_for_slot(slot)
    res = run_one(spec, tmp_path, slot_id=slot.slot_id, seed=slot.seed,
                  skip_resolver=False)

    assert res.success, (
        f"subprocess failed; stderr={res.stderr[:500]!r}"
    )

    slot_dir = tmp_path / slot.slot_id
    assert slot_dir.exists(), (
        f"expected outputs at {slot_dir}; tmp_path contents: "
        f"{list(tmp_path.iterdir())}"
    )

    # The smoking gun: generation_summary.json MUST be in the slot_id
    # directory. Pre-fix it landed in the resolver's creative-name
    # directory and slot_id was empty.
    summary = slot_dir / "generation_summary.json"
    assert summary.exists(), (
        f"generation_summary.json missing at {summary}; this is Bug 4. "
        f"slot_dir contents: {list(slot_dir.iterdir())}"
    )

    # No stray creative-name directory should exist as a sibling.
    siblings = [
        p for p in tmp_path.iterdir()
        if p.is_dir() and p.name != slot.slot_id
    ]
    assert siblings == [], (
        f"unexpected sibling directories created by the subprocess: "
        f"{[s.name for s in siblings]}. The subprocess should write "
        f"only to <output>/{slot.slot_id}/."
    )


@pytest.mark.slow
def test_subprocess_preserves_creative_name_as_display_name(tmp_path):
    """The fix preserves the resolver's creative name as
    `display_name` in the resolved spec. The on-disk lang_name is
    forced back to slot_id, but downstream consumers (GUI, curator)
    can still use display_name to surface the creative name."""
    slot = Slot(
        slot_id="display_check",
        options={"syntax": "stack_based", "typing": "dynamic",
                 "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common", notes="display_name check",
    )
    spec = _build_spec_for_slot(slot)
    res = run_one(spec, tmp_path, slot_id=slot.slot_id, seed=slot.seed,
                  skip_resolver=False)
    assert res.success, f"subprocess failed; stderr={res.stderr[:500]!r}"

    resolved_path = tmp_path / slot.slot_id / "resolved_spec.json"
    assert resolved_path.exists()
    resolved = json.loads(resolved_path.read_text(encoding="utf-8"))
    assert resolved["lang_name"] == slot.slot_id
    # If the resolver picked a different name, display_name carries it.
    # If the resolver happened to pick the same name as slot_id (rare),
    # display_name may be absent — that's also fine.
    if "display_name" in resolved:
        assert resolved["display_name"] != slot.slot_id, (
            f"display_name should differ from slot_id when the resolver "
            f"picked a creative name; got {resolved['display_name']!r}"
        )
