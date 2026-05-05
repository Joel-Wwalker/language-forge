"""Tests for the surprise-endpoint normalization layer.

The Claude CLI path doesn't enforce JSON Schema strictly, so the LLM
sometimes emits creative variants like `s-expression`, `gc`, or
`era_preset`. The `_normalize_surprise_picks` helper maps the common
mistakes back to canonical schema values BEFORE the orchestrator
trusts the dict.

These cases are based on actual logged failures from real surprise
attempts (see generated/lispy/.forge_log/) so we don't regress.
"""
from __future__ import annotations

from forge.gui.app import _normalize_surprise_picks


def test_normalizes_hyphenated_syntax():
    out = _normalize_surprise_picks({
        "options": {"syntax": "s-expression", "typing": "dynamic", "memory": "host_gc"},
    })
    assert out["options"]["syntax"] == "s_expression"


def test_normalizes_lisp_synonym():
    out = _normalize_surprise_picks({
        "options": {"syntax": "lisp", "typing": "dynamic", "memory": "host_gc"},
    })
    assert out["options"]["syntax"] == "s_expression"


def test_normalizes_gc_to_host_gc():
    out = _normalize_surprise_picks({
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "gc"},
    })
    assert out["options"]["memory"] == "host_gc"


def test_drops_unknown_options_keys():
    """The LLM hallucinated `paradigm` and `evaluation`. Drop them."""
    out = _normalize_surprise_picks({
        "options": {
            "syntax": "s_expression", "typing": "dynamic", "memory": "host_gc",
            "paradigm": "functional", "evaluation": "eager",
        },
    })
    assert "paradigm" not in out["options"]
    assert "evaluation" not in out["options"]
    # Canonical keys preserved
    assert out["options"]["syntax"] == "s_expression"


def test_aliases_designer_persona_to_persona():
    out = _normalize_surprise_picks({
        "designer_persona": "mccarthy",
        "options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
    })
    assert out.get("persona") == "mccarthy"
    assert "designer_persona" not in out


def test_aliases_era_preset_to_era():
    out = _normalize_surprise_picks({
        "era_preset": "1960s",
        "options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
    })
    assert out.get("era") == "1960s"


def test_drops_paradigm_and_friends_at_toplevel():
    out = _normalize_surprise_picks({
        "paradigm": "functional",
        "evaluation": "eager",
        "type_system": "dynamic",
        "syntax_style": "s-expression",
        "mutability": "immutable_default",
        "options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
    })
    for k in ("paradigm", "evaluation", "type_system", "syntax_style", "mutability"):
        assert k not in out, f"{k} should have been dropped"


def test_feature_bans_get_no_prefix():
    out = _normalize_surprise_picks({
        "feature_bans": ["loops", "mutation", "classes"],
        "options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
    })
    assert "no_loops" in out["feature_bans"]
    assert "no_mutation" in out["feature_bans"]
    assert "no_classes" in out["feature_bans"]


def test_feature_bans_passes_through_canonical_form():
    out = _normalize_surprise_picks({
        "feature_bans": ["no_mutation", "no_classes"],
        "options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
    })
    assert set(out["feature_bans"]) == {"no_mutation", "no_classes"}


def test_unknown_persona_dropped():
    out = _normalize_surprise_picks({
        "persona": "academic_minimalist",  # not a valid persona
        "options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
    })
    assert "persona" not in out


def test_unknown_era_aliased_to_nearby():
    """1990s isn't a valid era preset; map to 1980s."""
    out = _normalize_surprise_picks({
        "era": "1990s",
        "options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
    })
    assert out.get("era") == "1980s"


def test_unknown_keyword_theme_dropped():
    out = _normalize_surprise_picks({
        "keyword_theme": "philosophical",   # not a valid theme
        "options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
    })
    assert "keyword_theme" not in out


def test_real_failure_payload_from_lispy_attempt():
    """Reproduces the EXACT shape we logged from a real Surprise attempt
    in generated/lispy/.forge_log/. After normalization, the dict should
    be usable for downstream Job creation.

    Source: generated/lispy/.forge_log/20260502-222627_surprise.response.txt
    """
    raw = {
        "name": "lispy",
        "vibe": "s-expression, philosophical",
        "designer_persona": "academic_minimalist",
        "era_preset": "1990s",
        "keyword_theme": "philosophical",
        "origin_story": "Created in 1997 by a philosophy PhD dropout...",
        "design_notes": ["Pure s-expressions"],
        "options": {
            "syntax": "s-expression",
            "typing": "dynamic",
            "memory": "gc",
            "paradigm": "functional",
            "evaluation": "eager",
        },
        "feature_bans": ["loops", "mutation"],
    }
    out = _normalize_surprise_picks(raw)
    # syntax and memory canonicalized
    assert out["options"]["syntax"] == "s_expression"
    assert out["options"]["memory"] == "host_gc"
    # invented options dropped
    assert "paradigm" not in out["options"]
    assert "evaluation" not in out["options"]
    # designer_persona aliased; not a valid persona, so dropped
    assert "designer_persona" not in out
    assert "persona" not in out
    # era aliased then mapped (1990s -> 1980s)
    assert out["era"] == "1980s"
    # feature_bans get no_ prefix
    assert "no_loops" in out["feature_bans"]
    assert "no_mutation" in out["feature_bans"]
    # invented theme dropped
    assert "keyword_theme" not in out


def test_handles_empty_input():
    """Don't crash on edge-case inputs."""
    assert _normalize_surprise_picks({}) == {}
    assert _normalize_surprise_picks({"options": None})["options"] is None
