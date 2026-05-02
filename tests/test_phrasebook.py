"""Tests for the natural-language phrasebook layer."""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.orchestrator.spec_builder import build_spec, validate_spec
from forge.orchestrator.phrasebooks import (
    PHRASEBOOKS, list_phrasebooks, get_phrasebook,
)


BASE = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}


# ---------------------------------------------------------------------------
# Phrasebook module
# ---------------------------------------------------------------------------

def test_phrasebooks_module_exposes_known_presets():
    keys = {p["key"] for p in list_phrasebooks()}
    assert "english_storybook" in keys
    assert "shakespeare" in keys
    assert "child_speak" in keys
    assert "ritual" in keys


def test_get_phrasebook_returns_dict():
    p = get_phrasebook("english_storybook")
    assert isinstance(p, dict)
    assert "var_decl" in p
    assert "<name>" in p["var_decl"]


def test_get_phrasebook_unknown_returns_empty():
    assert get_phrasebook("not_a_preset") == {}
    assert get_phrasebook(None) == {}


def test_every_phrasebook_has_core_templates():
    """Every preset must have the core sentence templates and word entries."""
    required = {"var_decl", "func_def", "if_stmt", "while_stmt",
                "return_stmt", "true_word", "false_word", "null_word"}
    for key, book in PHRASEBOOKS.items():
        missing = required - set(book.keys())
        assert not missing, f"{key} is missing {missing}"


def test_every_template_has_required_slots():
    """Templates must use the canonical placeholders so the parser can plug
    grammar non-terminals into them."""
    slot_required = {
        "var_decl":    {"<name>", "<value>"},
        "func_def":    {"<name>", "<params>", "<body>"},
        "if_stmt":     {"<cond>", "<body>"},
        "while_stmt":  {"<cond>", "<body>"},
        "return_stmt": {"<value>"},
    }
    for book_name, book in PHRASEBOOKS.items():
        for template, needed_slots in slot_required.items():
            tpl = book.get(template, "")
            for slot in needed_slots:
                assert slot in tpl, f"{book_name}/{template} missing slot {slot}: {tpl!r}"


# ---------------------------------------------------------------------------
# build_spec integration
# ---------------------------------------------------------------------------

def test_no_phrasebook_means_no_natural_language_field():
    spec = build_spec(BASE, "demo")
    cust = spec.get("customization") or {}
    assert "natural_language" not in cust


def test_phrasebook_preset_lands_on_spec():
    spec = build_spec(BASE, "demo", phrasebook="english_storybook")
    nl = spec["customization"]["natural_language"]
    assert "<name>" in nl["var_decl"]
    assert "set" in nl["var_decl"]


def test_user_overrides_beat_preset():
    """Per-template overrides win over the preset's value."""
    spec = build_spec(
        BASE, "demo",
        phrasebook="english_storybook",
        natural_language={"while_stmt": "loop while <cond> do <body>."},
    )
    assert spec["customization"]["natural_language"]["while_stmt"] == "loop while <cond> do <body>."
    # Other entries from the preset are still present
    assert "<name>" in spec["customization"]["natural_language"]["var_decl"]


def test_overrides_alone_without_preset():
    """User can supply just templates, no preset."""
    spec = build_spec(
        BASE, "demo",
        natural_language={"var_decl": "be it known that <name> is <value>."},
    )
    nl = spec["customization"]["natural_language"]
    assert "be it known" in nl["var_decl"]


def test_word_overrides_propagate_to_spec_fields():
    """Phrasebook's true_word/false_word/null_word should update the spec's
    boolean_keywords and null_keyword so codegen and runtime stay consistent."""
    spec = build_spec(BASE, "demo", phrasebook="shakespeare")
    assert spec["boolean_keywords"]["true"] == "verily"
    assert spec["boolean_keywords"]["false"] == "naught"
    assert spec["null_keyword"] == "nothing"


def test_phrasebook_spec_validates_against_schema():
    spec = build_spec(BASE, "demo", phrasebook="english_storybook")
    validate_spec(spec)


def test_phrasebook_via_gui_endpoint(tmp_path):
    """The /api/phrasebooks endpoint returns the listing + full templates."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/api/phrasebooks")
    assert r.status_code == 200
    payload = r.get_json()
    assert "phrasebooks" in payload
    assert "templates" in payload
    assert "english_storybook" in payload["templates"]
    assert "<name>" in payload["templates"]["english_storybook"]["var_decl"]


def test_phrasebook_combines_with_other_customization():
    """Phrasebook + persona + era + bans all apply on the same spec."""
    spec = build_spec(
        BASE, "demo",
        phrasebook="child_speak",
        persona="hickey",
        era="2020s",
        feature_bans=["no_mutation"],
    )
    cust = spec["customization"]
    assert cust["persona"] == "hickey"
    assert cust["era"] == "2020s"
    assert "no_mutation" in cust["feature_bans"]
    assert "natural_language" in cust
    assert "the answer is" in cust["natural_language"]["return_stmt"]
