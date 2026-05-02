"""Tests for speculative-features layer (persona / era / theme / bans / hostile_constraints)."""
from __future__ import annotations

import pytest

from forge.orchestrator.spec_builder import build_spec, validate_spec
from forge.orchestrator.personas import PERSONAS, persona_block, list_personas
from forge.orchestrator.presets import ERAS, apply_era, list_eras
from forge.orchestrator.themes import THEMES, get_theme, list_themes
from forge.orchestrator.bans import BAN_DEFS, apply_bans, bans_prompt_block, list_bans


BASE = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}


# ---------- modules in isolation ----------

def test_personas_list_complete():
    keys = {p["key"] for p in list_personas()}
    assert "dijkstra" in keys
    assert "wadler" in keys
    assert len(keys) >= 7


def test_persona_block_returns_empty_for_unknown():
    assert persona_block(None) == ""
    assert persona_block("nobody") == ""


def test_persona_block_includes_persona_text():
    block = persona_block("dijkstra")
    assert "Dijkstra" in block
    assert "Designer persona" in block


def test_eras_have_blurbs():
    eras = list_eras()
    assert {"1960s", "1970s", "1980s", "2000s", "2020s"}.issubset({e["key"] for e in eras})
    for e in eras:
        assert e["blurb"]


def test_apply_era_user_wins():
    """User options must override era defaults on the same axis."""
    out = apply_era("1960s", {"syntax": "python_like", "memory": "refcount"})
    assert out["syntax"] == "python_like"           # user override beats era
    assert out["memory"] == "refcount"              # user override beats era
    assert out["typing"] == ERAS["1960s"]["typing"]  # era fills the gap


def test_themes_have_keyword_maps():
    for k in ("pirate", "shakespearean", "corporate", "latin", "cozy"):
        t = get_theme(k)
        assert "func" in t and "var" in t


def test_bans_apply_axis_overrides():
    out = apply_bans(["no_loops"], {"syntax": "c_like"})
    assert out["loop_forms"] == []


def test_bans_lose_to_explicit_user_choice():
    """If user explicitly set the axis, ban should NOT override it."""
    out = apply_bans(["no_loops"], {"loop_forms": ["while", "c_for"]})
    assert out["loop_forms"] == ["while", "c_for"]


def test_bans_prompt_block_includes_each_ban():
    block = bans_prompt_block(["no_null", "no_mutation"])
    assert "no_null" in block
    assert "no_mutation" in block
    assert "HIGH PRIORITY" in block


# ---------- integration with build_spec ----------

def test_build_spec_with_persona():
    spec = build_spec(BASE, "demo", persona="dijkstra")
    assert spec["customization"]["persona"] == "dijkstra"


def test_build_spec_with_era_fills_extended_options():
    spec = build_spec({"syntax": "c_like", "typing": "static", "memory": "host_gc"},
                      "demo", era="1960s")
    # Era preset filled in extended axes
    assert spec["options"]["error_handling"] == "panic_only"
    assert spec["options"]["boolean_evaluation"] == "eager"
    assert spec["customization"]["era"] == "1960s"


def test_build_spec_with_keyword_theme_pirate():
    spec = build_spec(BASE, "demo", keyword_theme="pirate")
    # `func` should have been renamed to the theme's choice
    assert spec["function_definition"]["keyword"] == THEMES["pirate"]["func"]
    assert spec["variable_declaration"]["keyword"] == THEMES["pirate"]["var"]
    assert spec["customization"]["keyword_theme"] == "pirate"


def test_build_spec_user_keyword_overrides_beat_theme():
    spec = build_spec(BASE, "demo",
                      keyword_theme="pirate",
                      customization={"keyword_overrides": {"func": "fn"}})
    assert spec["function_definition"]["keyword"] == "fn"  # user wins
    # But other theme keywords still apply
    assert spec["variable_declaration"]["keyword"] == THEMES["pirate"]["var"]


def test_build_spec_with_feature_bans_no_loops():
    spec = build_spec(BASE, "demo", feature_bans=["no_loops"])
    assert spec["options"]["loop_forms"] == []
    assert spec["customization"]["feature_bans"] == ["no_loops"]
    # Ban prompt notes injected into per-component extra_prompt_notes
    assert "no_loops" in spec["customization"]["extra_prompt_notes"]["parser"]


def test_build_spec_with_feature_bans_no_mutation():
    spec = build_spec(BASE, "demo", feature_bans=["no_mutation"])
    assert spec["options"]["default_mutability"] == "immutable"
    # Ban gets recorded in design notes too
    notes = spec["customization"]["extra_design_notes"]
    assert any("no_mutation" in n for n in notes)


def test_build_spec_with_hostile_constraints():
    spec = build_spec(BASE, "demo",
                      hostile_constraints="every program must contain a recursive function")
    assert "recursive" in spec["customization"]["hostile_constraints"]


def test_build_spec_kitchen_sink():
    """All speculative metadata together still validates."""
    spec = build_spec(
        BASE, "demo",
        persona="hickey",
        era="2020s",
        keyword_theme="cozy",
        feature_bans=["no_mutation", "no_exceptions"],
        hostile_constraints="all keywords must be alphabetized",
        customization={
            "extra_design_notes": ["pre-existing"],
            "additional_tests": [{"name": "feature_x", "source": "x;", "expected": "y"}],
        },
    )
    validate_spec(spec)
    c = spec["customization"]
    assert c["persona"] == "hickey"
    assert c["era"] == "2020s"
    assert c["keyword_theme"] == "cozy"
    assert "no_mutation" in c["feature_bans"]
    assert "no_exceptions" in c["feature_bans"]
    assert "alphabetized" in c["hostile_constraints"]
    assert any("pre-existing" in n for n in c["extra_design_notes"])
    # Ban-derived axis overrides applied
    assert spec["options"]["default_mutability"] == "immutable"
    # no_exceptions forced result_type, but era=2020s also chose result_type, so no conflict
    assert spec["options"]["error_handling"] == "result_type"
