"""Tests for the option layering order.

The spec_builder applies options in a specific order:
  1. era_preset fills option gaps.
  2. user options always win.
  3. feature_bans add option overrides where the user hasn't set them.
  4. customization keyword/operator overrides apply.
  5. keyword_theme folds into customization.keyword_overrides (user wins).

These tests verify the order and the user-wins-on-conflict invariant.
"""
from __future__ import annotations

from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.themes import THEMES


BASE = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}


def test_era_fills_unset_axes_only():
    """An era preset only fills extended axes that the user didn't supply."""
    spec = build_spec(
        {**BASE, "loop_forms": ["c_for"]},
        "demo",
        era="1960s",
    )
    # User explicitly chose c_for. Era's default loop_forms must not override.
    assert spec["options"]["loop_forms"] == ["c_for"]
    # Boolean evaluation wasn't user-set, so era's value (eager for 1960s) wins.
    assert spec["options"]["boolean_evaluation"] == "eager"


def test_user_option_beats_era():
    """User explicit choice always wins over era preset."""
    # Era 2020s defaults default_mutability=immutable. User picks mutable.
    spec = build_spec(
        {**BASE, "default_mutability": "mutable"},
        "demo",
        era="2020s",
    )
    assert spec["options"]["default_mutability"] == "mutable"


def test_ban_loses_to_user_explicit_option():
    """no_loops would empty loop_forms. If user explicitly set loop_forms, user wins."""
    spec = build_spec(
        {**BASE, "loop_forms": ["while", "foreach"]},
        "demo",
        feature_bans=["no_loops"],
    )
    assert spec["options"]["loop_forms"] == ["while", "foreach"]


def test_ban_applies_when_user_silent():
    spec = build_spec(BASE, "demo", feature_bans=["no_loops"])
    assert spec["options"]["loop_forms"] == []


def test_ban_axis_override_loses_to_era():
    """Both era and ban set the same axis. User's silence means BOTH are
    contenders. The ordering: era runs first, then bans `setdefault` (which
    only fills if not set). Here the era fills loop_forms, then bans see
    it's already filled and don't override."""
    spec = build_spec(BASE, "demo", era="2000s", feature_bans=["no_loops"])
    # era 2000s sets loop_forms = ["while", "foreach"]; ban no_loops would
    # have wanted []. Era's value persists because apply_bans uses setdefault.
    assert spec["options"]["loop_forms"] == ["while", "foreach"]


def test_user_keyword_override_beats_theme():
    """If user supplies keyword_overrides, those win over the theme map."""
    spec = build_spec(
        BASE, "demo",
        keyword_theme="pirate",
        customization={"keyword_overrides": {"func": "fn"}},
    )
    assert spec["function_definition"]["keyword"] == "fn"
    # Other theme keywords still apply
    assert spec["variable_declaration"]["keyword"] == THEMES["pirate"]["var"]


def test_theme_applies_when_user_silent():
    spec = build_spec(BASE, "demo", keyword_theme="cozy")
    assert spec["function_definition"]["keyword"] == THEMES["cozy"]["func"]
    assert spec["variable_declaration"]["keyword"] == THEMES["cozy"]["var"]


def test_persona_recorded_in_customization():
    spec = build_spec(BASE, "demo", persona="dijkstra")
    assert spec["customization"]["persona"] == "dijkstra"


def test_unknown_persona_silently_ignored():
    """Unknown persona doesn't blow up; it just isn't recorded."""
    spec = build_spec(BASE, "demo", persona="not_a_persona")
    cust = spec.get("customization") or {}
    assert "persona" not in cust


def test_hostile_constraints_stored_verbatim():
    spec = build_spec(BASE, "demo",
                      hostile_constraints="every program must contain a comment")
    assert "every program" in spec["customization"]["hostile_constraints"]


def test_kitchen_sink_does_not_lose_user_data():
    """Persona + era + theme + bans + customization all present.
    User explicit options must survive."""
    spec = build_spec(
        {**BASE, "default_mutability": "mutable", "loop_forms": ["c_for"]},
        "demo",
        persona="hickey",
        era="2020s",                       # era sets default_mutability=immutable, loop_forms=...
        keyword_theme="cozy",              # theme renames keywords
        feature_bans=["no_exceptions"],    # ban sets error_handling=result_type
        hostile_constraints="palindrome names only",
        customization={
            "extra_design_notes": ["lispy"],
            "additional_tests": [{"name": "pal", "source": "x;", "expected": "y\n"}],
        },
    )
    # User options preserved against era
    assert spec["options"]["default_mutability"] == "mutable"
    assert spec["options"]["loop_forms"] == ["c_for"]
    # Theme applied (no user override on these keywords)
    assert spec["function_definition"]["keyword"] == THEMES["cozy"]["func"]
    # Ban metadata recorded
    assert "no_exceptions" in spec["customization"]["feature_bans"]
    # Persona, era, theme, hostile constraints all on the spec
    c = spec["customization"]
    assert c["persona"] == "hickey"
    assert c["era"] == "2020s"
    assert c["keyword_theme"] == "cozy"
    assert "palindrome" in c["hostile_constraints"]
    # User additional_tests survived
    assert c["additional_tests"][0]["name"] == "pal"
    # User extra_design_notes survived (plus ban-derived note appended)
    assert any("lispy" in n for n in c["extra_design_notes"])
    assert any("no_exceptions" in n for n in c["extra_design_notes"])
