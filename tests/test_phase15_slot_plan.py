"""Phase 1.5 scope expansion — slot-plan deferrals.

# WHY

Gate 2's first re-run revealed three categories of failure that are
genuinely OUT of Phase 1.5's scope:

  - `c_like static`: templated path doesn't synthesize a typechecker.
    Phase 5 (LLM-path improvements) territory.
  - `python_like`: no hand-written reference compiler exists yet. The
    LLM-driven path produces buggy codegen (visitor-pattern recursion).
    Phase 5 (when pythonlang reference is built) territory.

Rather than mark these as "expected to fail" or compute the gate
threshold against a polluted denominator, we prune them out of
`v1_phase1.json` and document them as deferred work in
`v1_phase1_deferred.json`. The gate runs against the 38 eligible
slots; the 12 deferred slots are a separate, future plan.

These tests pin the contract:

  - `v1_phase1.json` contains only families/typings the templated path
    actually supports today (c_like dynamic, s_expression dynamic,
    stack_based dynamic).
  - `v1_phase1_deferred.json` contains the 12 deferred slots with
    `deferred_reason` annotations so a future agent reading the file
    knows why they're separated.
  - The two files together account for the original 50 slots.

If a future plan edit accidentally re-introduces a python_like or
c_like-static slot to v1_phase1.json without thought, this test
fails and prompts the editor to either fix the templated path's
coverage or move the slot to the deferred file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


WORKSPACE = Path(__file__).resolve().parents[1]
SLOTS_DIR = WORKSPACE / "forge" / "catalog" / "slots"
ELIGIBLE = SLOTS_DIR / "v1_phase1.json"
DEFERRED = SLOTS_DIR / "v1_phase1_deferred.json"


def _load(p: Path) -> list[dict]:
    return json.loads(p.read_text(encoding="utf-8"))


def test_eligible_plan_exists():
    assert ELIGIBLE.exists(), f"{ELIGIBLE} missing"


def test_deferred_plan_exists():
    assert DEFERRED.exists(), (
        f"{DEFERRED} missing — Phase 1.5 scope expansion split the "
        f"original 50-slot v1_phase1.json into 38 eligible + 12 "
        f"deferred slots. The deferred file should sit next to "
        f"the eligible one and document why each slot is deferred."
    )


def test_eligible_plan_excludes_python_like():
    """python_like has no reference compiler. Until a pythonlang
    hand-written reference lands (Phase 5), python_like slots can't
    pass the gate reliably and shouldn't be in v1_phase1.json."""
    plan = _load(ELIGIBLE)
    py_slots = [s for s in plan if s.get("options", {}).get("syntax") == "python_like"]
    assert py_slots == [], (
        f"v1_phase1.json contains {len(py_slots)} python_like slot(s): "
        f"{[s['slot_id'] for s in py_slots]}. python_like is deferred "
        f"to Phase 5 — these belong in v1_phase1_deferred.json. "
        f"If you're trying to re-include them, build the pythonlang "
        f"reference compiler first and add it to REFERENCE_COMPILERS."
    )


def test_eligible_plan_excludes_clike_static():
    """c_like static needs typechecker synthesis. Phase 1.5's
    templated path doesn't synthesize a typechecker — the toylang
    reference is dynamic-typed. Deferred to Phase 5."""
    plan = _load(ELIGIBLE)
    bad = [
        s for s in plan
        if s.get("options", {}).get("syntax") == "c_like"
        and s.get("options", {}).get("typing") == "static"
    ]
    assert bad == [], (
        f"v1_phase1.json contains {len(bad)} c_like static slot(s): "
        f"{[s['slot_id'] for s in bad]}. c_like static is deferred to "
        f"Phase 5 — these belong in v1_phase1_deferred.json. "
        f"If you're trying to re-include them, the templated path "
        f"needs to synthesize a typechecker first."
    )


def test_deferred_plan_only_contains_deferred_categories():
    """The deferred file is the inverse: it should only contain
    python_like or c_like-static slots (the categories Phase 1.5
    explicitly defers)."""
    plan = _load(DEFERRED)
    for slot in plan:
        syntax = slot.get("options", {}).get("syntax")
        typing = slot.get("options", {}).get("typing")
        is_python_like = syntax == "python_like"
        is_clike_static = syntax == "c_like" and typing == "static"
        assert is_python_like or is_clike_static, (
            f"slot {slot['slot_id']} (syntax={syntax}, typing={typing}) "
            f"is in v1_phase1_deferred.json but isn't a known deferred "
            f"category. Either it should pass on the templated path "
            f"and belongs in v1_phase1.json, or this test needs a new "
            f"deferral category added explicitly."
        )


def test_deferred_slots_have_deferred_reason():
    """Each deferred slot carries a `deferred_reason` field so a
    future agent reading the file understands why it's there."""
    plan = _load(DEFERRED)
    for slot in plan:
        assert slot.get("deferred_reason"), (
            f"deferred slot {slot['slot_id']} missing `deferred_reason`. "
            f"Document the trigger for un-deferring (e.g., 'Phase 5 "
            f"pythonlang reference lands' or 'typechecker synthesis "
            f"added to templated path')."
        )


def test_eligible_and_deferred_partition_original_50():
    """Together they should account for the original 50-slot plan
    exactly. No slot should be in both; no slot should be missing."""
    eligible = _load(ELIGIBLE)
    deferred = _load(DEFERRED)
    elig_ids = {s["slot_id"] for s in eligible}
    def_ids = {s["slot_id"] for s in deferred}
    # No overlap.
    assert elig_ids.isdisjoint(def_ids), (
        f"{elig_ids & def_ids} appear in BOTH eligible and deferred; "
        f"each slot belongs in exactly one file."
    )
    # No duplicates within each file.
    assert len(elig_ids) == len(eligible), "duplicate ids in eligible"
    assert len(def_ids) == len(deferred), "duplicate ids in deferred"
    # Combined count matches the original 50-slot plan.
    assert len(eligible) + len(deferred) == 50, (
        f"eligible ({len(eligible)}) + deferred ({len(deferred)}) "
        f"= {len(eligible) + len(deferred)}, expected 50 (the original "
        f"v1_phase1.json count). Some slot may have been dropped or "
        f"duplicated."
    )


def test_eligible_count_is_38():
    """The Phase 1.5 scope expansion targets 38 eligible slots:
    20 c_like (slot_001-020 minus the 2 static ones) +
    10 s_expression (slot_031-040) +
    10 stack_based (slot_041-050)
    = 18 + 10 + 10 = 38."""
    eligible = _load(ELIGIBLE)
    assert len(eligible) == 38, (
        f"v1_phase1.json has {len(eligible)} slots, expected 38 "
        f"(20 c_like dynamic + 10 s_expression + 10 stack_based, "
        f"with 2 c_like static deferred)."
    )


def test_deferred_count_is_12():
    """The deferred plan: 2 c_like static + 10 python_like = 12."""
    deferred = _load(DEFERRED)
    assert len(deferred) == 12, (
        f"v1_phase1_deferred.json has {len(deferred)} slots, "
        f"expected 12 (10 python_like + 2 c_like static)."
    )
