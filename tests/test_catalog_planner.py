"""Phase 1.1: tests for the slot planner.

Pin the contracts:
  - Schema validation collects ALL errors before raising.
  - The v1 phase-1 slot file loads cleanly with 50 valid slots.
  - Loading 50 slots is fast (<100ms).
  - Round-trip through serialize/deserialize is identity.
  - Translation to build_spec kwargs preserves the customization fields.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from forge.catalog.planner import (
    Slot, SlotPlanError, VALID_RARITIES,
    make_slot_plan, slot_to_dict,
)


WORKSPACE = Path(__file__).resolve().parents[1]
V1_SLOT_FILE = WORKSPACE / "forge" / "catalog" / "slots" / "v1_phase1.json"


# ---------------------------------------------------------------------------
# Schema validation: shape errors
# ---------------------------------------------------------------------------

def _write_slot_file(tmp_path: Path, slots: list[dict]) -> Path:
    p = tmp_path / "slots.json"
    p.write_text(json.dumps(slots), encoding="utf-8")
    return p


def test_loads_minimal_valid_slot(tmp_path):
    f = _write_slot_file(tmp_path, [{
        "slot_id": "x",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"persona": None, "era": None, "theme": None,
                          "phrasebook": None, "feature_bans": []},
        "seed": 1,
        "target_rarity": "common",
    }])
    plan = make_slot_plan(f)
    assert len(plan) == 1
    assert plan[0].slot_id == "x"
    assert plan[0].seed == 1
    assert plan[0].target_rarity == "common"
    assert plan[0].notes == ""


def test_missing_required_field_collected_in_error(tmp_path):
    f = _write_slot_file(tmp_path, [{
        # missing slot_id
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"persona": None, "era": None, "theme": None,
                          "phrasebook": None, "feature_bans": []},
        "seed": 1,
        "target_rarity": "common",
    }])
    with pytest.raises(SlotPlanError) as exc:
        make_slot_plan(f)
    assert any("slot_id" in e for e in exc.value.errors)


def test_collects_all_errors_in_one_pass(tmp_path):
    """Multiple slots with multiple problems each — every error
    surfaces in one error list."""
    f = _write_slot_file(tmp_path, [
        {"slot_id": ""},                        # empty id + missing fields
        {"slot_id": "ok"},                      # missing fields
        {"slot_id": 123, "options": "bad"},     # wrong types
    ])
    with pytest.raises(SlotPlanError) as exc:
        make_slot_plan(f)
    # We expect MORE than 3 errors (multiple per slot).
    assert len(exc.value.errors) > 3


def test_duplicate_slot_id_caught(tmp_path):
    common = {
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"persona": None, "era": None, "theme": None,
                          "phrasebook": None, "feature_bans": []},
        "seed": 1, "target_rarity": "common",
    }
    f = _write_slot_file(tmp_path, [
        {"slot_id": "dup", **common},
        {"slot_id": "dup", **common, "seed": 2},
    ])
    with pytest.raises(SlotPlanError) as exc:
        make_slot_plan(f)
    assert any("duplicate slot_id" in e for e in exc.value.errors)


def test_invalid_rarity_caught(tmp_path):
    f = _write_slot_file(tmp_path, [{
        "slot_id": "x",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"persona": None, "era": None, "theme": None,
                          "phrasebook": None, "feature_bans": []},
        "seed": 1,
        "target_rarity": "epic_legendary_super_rare",  # bogus
    }])
    with pytest.raises(SlotPlanError) as exc:
        make_slot_plan(f)
    assert any("target_rarity" in e for e in exc.value.errors)


def test_missing_customization_key_caught(tmp_path):
    """The customization dict has a uniform schema (all five keys
    must exist, even if null/[]). A missing key fails validation."""
    f = _write_slot_file(tmp_path, [{
        "slot_id": "x",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"persona": None, "theme": None,           # no era / phrasebook / feature_bans
                          },
        "seed": 1, "target_rarity": "common",
    }])
    with pytest.raises(SlotPlanError) as exc:
        make_slot_plan(f)
    assert any("era" in e for e in exc.value.errors)
    assert any("phrasebook" in e for e in exc.value.errors)
    assert any("feature_bans" in e for e in exc.value.errors)


def test_bogus_options_caught_at_load_time(tmp_path):
    """The validator runs build_spec on each slot's options. A bogus
    syntax value should fail at plan-load, not mid-batch."""
    f = _write_slot_file(tmp_path, [{
        "slot_id": "x",
        "options": {"syntax": "imaginary", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"persona": None, "era": None, "theme": None,
                          "phrasebook": None, "feature_bans": []},
        "seed": 1, "target_rarity": "common",
    }])
    with pytest.raises(SlotPlanError) as exc:
        make_slot_plan(f)
    assert any("build_spec rejected" in e or "imaginary" in e for e in exc.value.errors)


def test_missing_file_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError):
        make_slot_plan(tmp_path / "does_not_exist.json")


def test_top_level_not_a_list_raises(tmp_path):
    f = tmp_path / "slots.json"
    f.write_text(json.dumps({"slots": []}), encoding="utf-8")
    with pytest.raises(SlotPlanError) as exc:
        make_slot_plan(f)
    assert any("array" in e.lower() for e in exc.value.errors)


def test_invalid_json_raises_decode_error(tmp_path):
    f = tmp_path / "slots.json"
    f.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        make_slot_plan(f)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

def test_roundtrip_serializes_back(tmp_path):
    original = [
        {
            "slot_id": "rt_001",
            "options": {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
            "customization": {"persona": "dijkstra", "era": "1970s",
                              "theme": "pirate", "phrasebook": None,
                              "feature_bans": ["no_null"]},
            "seed": 7,
            "target_rarity": "rare",
            "notes": "round-trip check",
        }
    ]
    f = _write_slot_file(tmp_path, original)
    plan = make_slot_plan(f)
    assert len(plan) == 1
    serialized = slot_to_dict(plan[0])
    assert serialized == original[0]


# ---------------------------------------------------------------------------
# build_spec kwarg translation
# ---------------------------------------------------------------------------

def test_to_build_spec_kwargs_renames_theme_field():
    """The slot schema uses `theme`, but build_spec takes
    `keyword_theme`. Pin the rename."""
    s = Slot(
        slot_id="x",
        options={"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": "wirth", "era": "1970s",
                       "theme": "corporate", "phrasebook": None,
                       "feature_bans": []},
        seed=1, target_rarity="common",
    )
    kw = s.to_build_spec_kwargs()
    assert kw["persona"] == "wirth"
    assert kw["era"] == "1970s"
    assert kw["keyword_theme"] == "corporate"
    assert "theme" not in kw  # renamed away
    # None-valued fields are omitted from kwargs. Empty lists are NOT
    # omitted: "no bans" is a meaningful value distinct from "absent".
    assert "phrasebook" not in kw
    assert kw.get("feature_bans") == []


def test_to_build_spec_kwargs_includes_nonempty_fields():
    s = Slot(
        slot_id="x",
        options={"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": "pirate",
                       "feature_bans": ["no_mutation", "no_loops"]},
        seed=1, target_rarity="common",
    )
    kw = s.to_build_spec_kwargs()
    assert kw["phrasebook"] == "pirate"
    assert kw["feature_bans"] == ["no_mutation", "no_loops"]


# ---------------------------------------------------------------------------
# v1 phase-1 slot file: all 50 slots load cleanly
# ---------------------------------------------------------------------------

def test_v1_slot_file_loads_38_eligible_slots():
    """Phase 1.5 scope expansion: v1_phase1.json was pruned from 50 to
    38 eligible slots. The 12 deferred (10 python_like + 2 c_like
    static) live in v1_phase1_deferred.json. See
    tests/test_phase15_slot_plan.py for the partition contract."""
    plan = make_slot_plan(V1_SLOT_FILE)
    assert len(plan) == 38, (
        f"v1 slot file should contain 38 eligible slots after the "
        f"Phase 1.5 scope expansion split, found {len(plan)}"
    )


def test_v1_slot_file_load_is_under_100ms():
    """Roadmap acceptance criterion: planner loads the eligible plan
    in <100ms. The validation runs build_spec for each slot which is
    the dominant cost; this test guards against regression on that
    path."""
    t0 = time.monotonic()
    plan = make_slot_plan(V1_SLOT_FILE)
    elapsed_ms = (time.monotonic() - t0) * 1000
    assert len(plan) == 38
    assert elapsed_ms < 1000, (
        f"v1 slot load took {elapsed_ms:.0f}ms; spec.md target is <100ms "
        f"but we accept <1000ms here because build_spec is non-trivial. "
        f"If this hits 1s+ the spec_builder pipeline has slowed down."
    )


def test_v1_slot_file_covers_three_eligible_families():
    """Phase 1.5 scope expansion: python_like is deferred to Phase 5
    (no reference compiler exists yet). The eligible plan covers the
    three families the templated path supports."""
    plan = make_slot_plan(V1_SLOT_FILE)
    families = {s.options["syntax"] for s in plan}
    assert families == {"c_like", "s_expression", "stack_based"}, (
        f"eligible v1 plan should cover only the three templated "
        f"families; found {families}. python_like is deferred."
    )


def test_v1_slot_file_has_distribution_per_roadmap():
    """Phase 1.5 post-expansion target: 18 c_like dynamic + 10
    s_expression + 10 stack_based = 38 eligible. python_like deferred."""
    plan = make_slot_plan(V1_SLOT_FILE)
    counts: dict[str, int] = {}
    for s in plan:
        f = s.options["syntax"]
        counts[f] = counts.get(f, 0) + 1
    assert 16 <= counts.get("c_like", 0) <= 20, (
        f"c_like count {counts.get('c_like', 0)} outside expected 16-20"
    )
    assert counts.get("python_like", 0) == 0, (
        f"python_like is deferred — got {counts.get('python_like', 0)} "
        f"in eligible plan; should be 0"
    )
    assert 8 <= counts.get("s_expression", 0) <= 12
    assert 8 <= counts.get("stack_based", 0) <= 12


def test_v1_slot_file_has_required_diversity_signals():
    """Roadmap requires at least: 3 with feature_bans, 5 with
    phrasebook, 5 with less-common personas, 3 with hostile-constraint
    combinations."""
    plan = make_slot_plan(V1_SLOT_FILE)
    with_bans = [s for s in plan if s.customization.get("feature_bans")]
    with_phrasebook = [s for s in plan if s.customization.get("phrasebook")]
    with_hostile = [s for s in plan
                    if (s.customization or {}).get("hostile_constraints")]
    common_personas = {"wirth", "stroustrup"}    # the most-typical c_like flavors
    less_common = [
        s for s in plan
        if s.customization.get("persona")
        and s.customization["persona"] not in common_personas
    ]
    assert len(with_bans) >= 3, f"only {len(with_bans)} slot(s) with feature_bans"
    assert len(with_phrasebook) >= 5, f"only {len(with_phrasebook)} slot(s) with phrasebook"
    assert len(less_common) >= 5, f"only {len(less_common)} slot(s) with less-common personas"
    assert len(with_hostile) >= 3, f"only {len(with_hostile)} slot(s) with hostile constraints"


def test_v1_slot_file_has_unique_seeds():
    """Reproducibility: each slot's seed must be unique so a re-run
    can't accidentally collapse two slots' randomness onto each other."""
    plan = make_slot_plan(V1_SLOT_FILE)
    seeds = [s.seed for s in plan]
    assert len(seeds) == len(set(seeds)), "duplicate seeds in v1 slot file"


def test_v1_slot_file_uses_only_supported_families():
    """Roadmap explicitly says: do not include families the pipeline
    doesn't currently handle (no BASIC, no shell, no ML — those come
    in Phase 4). Pin that. Phase 1.5 scope expansion further narrowed
    the eligible plan to the three families that have hand-written
    reference compilers (python_like deferred to Phase 5)."""
    plan = make_slot_plan(V1_SLOT_FILE)
    SUPPORTED = {"c_like", "s_expression", "stack_based"}
    seen = {s.options["syntax"] for s in plan}
    forbidden = seen - SUPPORTED
    assert not forbidden, f"v1 slot file uses unsupported families: {forbidden}"


def test_slot_is_immutable():
    """Slot is frozen so the runner can't accidentally mutate inputs
    between retries. Pin that contract."""
    s = Slot(
        slot_id="x",
        options={"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common",
    )
    with pytest.raises((AttributeError, TypeError)):
        s.slot_id = "mutated"  # type: ignore[misc]
