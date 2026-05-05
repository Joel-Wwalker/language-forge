"""Tests for the §3.3 crossbreeding module.

The crossbreed() function takes two languages' creation metadata and
produces a child spec dict + lineage block. We verify:
  - merge strategies (random / dominant / union) all produce valid output
  - lineage block carries the parents + generation
  - the resulting kwargs round-trip through build_spec without crashing
  - the child's spec.lineage actually lands in the spec
  - feature_bans are unioned across parents
"""
from __future__ import annotations

import json

import pytest

from forge.orchestrator.crossbreeding import (
    crossbreed, merge_options, merge_extras, _OPTION_AXES,
)
from forge.orchestrator.spec_builder import build_spec


def _opts(**kw):
    """Tiny helper: build a sane options dict, then patch."""
    base = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}
    base.update(kw)
    return base


# ---------- merge_options ----------

def test_merge_options_no_conflicts():
    a = _opts(error_handling="exceptions")
    b = _opts(comment_style="block")
    out = merge_options(a, b, strategy="random")
    assert out["syntax"] == "c_like"
    assert out["error_handling"] == "exceptions"
    assert out["comment_style"] == "block"


def test_merge_options_dominant_picks_a():
    a = _opts(typing="static", error_handling="exceptions")
    b = _opts(typing="dynamic", error_handling="result_type")
    out = merge_options(a, b, strategy="dominant")
    assert out["typing"] == "static"
    assert out["error_handling"] == "exceptions"


def test_merge_options_union_for_lists():
    a = _opts(loop_forms=["while", "c_for"])
    b = _opts(loop_forms=["while", "foreach"])
    out = merge_options(a, b, strategy="union")
    # Order preserved (a first, dedup), so c_for stays before foreach.
    assert out["loop_forms"] == ["while", "c_for", "foreach"]


def test_merge_options_random_is_seeded():
    a = _opts(typing="static")
    b = _opts(typing="dynamic")
    import random
    rng_seeded_1 = random.Random(7)
    rng_seeded_2 = random.Random(7)
    out1 = merge_options(a, b, strategy="random", rng=rng_seeded_1)
    out2 = merge_options(a, b, strategy="random", rng=rng_seeded_2)
    assert out1["typing"] == out2["typing"]


# ---------- merge_extras ----------

def test_merge_extras_unions_feature_bans():
    a = {"feature_bans": ["no_loops"]}
    b = {"feature_bans": ["no_null"]}
    out = merge_extras(a, b, strategy="random")
    assert set(out["feature_bans"]) == {"no_loops", "no_null"}


def test_merge_extras_merges_design_notes():
    a = {"customization": {"extra_design_notes": ["A1", "A2"]}}
    b = {"customization": {"extra_design_notes": ["B1"]}}
    out = merge_extras(a, b, strategy="random")
    notes = out["customization"]["extra_design_notes"]
    # B notes first (cust_b), then A notes layered over (cust_a wins ties)
    assert "A1" in notes and "A2" in notes and "B1" in notes


# ---------- crossbreed (high-level) ----------

def test_crossbreed_lineage_block():
    a = {"name": "alpha", "options": _opts()}
    b = {"name": "beta", "options": _opts(typing="static")}
    child = crossbreed(a, b, child_name="gamma", strategy="dominant")
    assert child["name"] == "gamma"
    assert child["lineage"]["parents"] == ["alpha", "beta"]
    assert child["lineage"]["strategy"] == "dominant"
    assert child["lineage"]["generation"] == 1


def test_crossbreed_generation_increments():
    a = {"name": "a", "options": _opts(), "lineage": {"generation": 2}}
    b = {"name": "b", "options": _opts(), "lineage": {"generation": 3}}
    child = crossbreed(a, b, child_name="c", strategy="dominant")
    assert child["lineage"]["generation"] == 4   # max(2, 3) + 1


def test_crossbreed_round_trips_through_build_spec():
    """The child's kwargs must be acceptable to build_spec, including the
    new `lineage` parameter, and the lineage must survive on spec."""
    a = {"name": "alpha", "options": _opts(),
         "persona": "wirth", "era": "1970s"}
    b = {"name": "beta",
         "options": _opts(typing="static", error_handling="exceptions"),
         "persona": "stroustrup"}
    child = crossbreed(a, b, child_name="gamma", strategy="dominant")
    spec = build_spec(
        child["options"], child["name"],
        customization=child.get("customization") or {},
        persona=child.get("persona"),
        era=child.get("era"),
        keyword_theme=child.get("keyword_theme"),
        feature_bans=child.get("feature_bans") or [],
        lineage=child["lineage"],
    )
    assert spec["lineage"]["parents"] == ["alpha", "beta"]
    assert spec["lineage"]["generation"] == 1
    assert spec["lineage"]["strategy"] == "dominant"
    # Persona under dominant strategy follows parent_a.
    assert spec["customization"]["persona"] == "wirth"
    # Lineage shows up in design_notes too (so the resolver can mention it).
    assert any("lineage" in n.lower() for n in spec["design_notes"])


def test_crossbreed_seed_is_reproducible():
    a = {"name": "a", "options": _opts(typing="static",
                                        error_handling="exceptions")}
    b = {"name": "b", "options": _opts(typing="dynamic",
                                        error_handling="result_type")}
    c1 = crossbreed(a, b, child_name="kid", strategy="random", seed=99)
    c2 = crossbreed(a, b, child_name="kid", strategy="random", seed=99)
    assert c1["options"] == c2["options"]


def test_crossbreed_handles_empty_options_gracefully():
    a = {"name": "a", "options": {}}
    b = {"name": "b", "options": {"syntax": "python_like"}}
    child = crossbreed(a, b, child_name="kid", strategy="random", seed=1)
    # syntax came from b; nothing crashed
    assert child["options"]["syntax"] == "python_like"


def test_option_axes_match_schema_supported_axes():
    """If someone adds an option to the schema we want crossbreeding to
    cover it. Failing this test means: add the new key to _OPTION_AXES."""
    import json, pathlib
    schema_path = pathlib.Path(__file__).resolve().parents[1] / "schemas" / "language_spec.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_opts = set(schema["properties"]["options"]["properties"].keys())
    crossbreed_axes = set(_OPTION_AXES)
    missing = schema_opts - crossbreed_axes
    assert not missing, (
        f"crossbreeding._OPTION_AXES is missing schema option(s): {missing}. "
        "Add them so cross-breed merges those axes too."
    )
