"""Tests for the Tier-1+2 extended options from forge-extended-options.md.

These verify backward compatibility (defaults match the original 3-axis MVP)
AND that each new axis propagates into the spec correctly.
"""
from __future__ import annotations

import itertools
import pytest

from forge.orchestrator.spec_builder import build_spec, validate_spec


BASE = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}
PY_BASE = {"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"}


def test_defaults_for_all_extended_axes():
    """When no extended options provided, defaults appear on the spec."""
    spec = build_spec(BASE, "demo")
    o = spec["options"]
    assert o["comment_style"] == "both"          # c_like default
    assert o["string_literals"] == "double"
    assert o["numeric_literals"] == "decimal_only"
    assert o["default_mutability"] == "mutable"
    assert o["error_handling"] == "panic_only"
    assert o["loop_forms"] == ["while"]
    assert o["multiple_returns"] == "none"
    assert o["boolean_evaluation"] == "short_circuit"


def test_python_like_default_comment_is_line():
    spec = build_spec(PY_BASE, "demo")
    assert spec["options"]["comment_style"] == "line"


@pytest.mark.parametrize("syn,typ,mem", list(itertools.product(
    ["c_like", "python_like"], ["static", "dynamic"], ["host_gc", "refcount"]
)))
def test_existing_8_combos_still_validate_with_defaults(syn, typ, mem):
    """Backward compat: every original MVP combo must still produce a valid spec."""
    spec = build_spec({"syntax": syn, "typing": typ, "memory": mem}, "demo")
    validate_spec(spec)


# ---- comment_style ----

def test_comment_style_line_only():
    spec = build_spec({**BASE, "comment_style": "line"}, "demo")
    assert spec["comment_syntax"]["line"] == "//"
    assert spec["comment_syntax"]["block_open"] is None


def test_comment_style_nestable_block():
    spec = build_spec({**BASE, "comment_style": "nestable_block"}, "demo")
    assert spec["comment_syntax"].get("nestable") is True


# ---- string_literals ----

def test_string_literals_triple_quoted():
    spec = build_spec({**BASE, "string_literals": "triple_quoted"}, "demo")
    assert spec["literals"]["string_form"] == "triple_quoted"
    assert "multi" in spec["literals"]["string"].lower() or '"""' in spec["literals"]["string"]


def test_string_literals_raw_and_normal():
    spec = build_spec({**BASE, "string_literals": "raw_and_normal"}, "demo")
    assert spec["literals"]["string_form"] == "raw_and_normal"
    assert "raw" in spec["literals"]["string"].lower() or "r\"" in spec["literals"]["string"]


# ---- numeric_literals ----

def test_numeric_literals_c_style():
    spec = build_spec({**BASE, "numeric_literals": "c_style"}, "demo")
    assert spec["literals"]["integer_form"] == "c_style"
    assert "0x" in spec["literals"]["integer"]


def test_numeric_literals_extended():
    spec = build_spec({**BASE, "numeric_literals": "extended"}, "demo")
    assert spec["literals"]["integer_form"] == "extended"
    assert "underscore" in spec["literals"]["integer"].lower()


# ---- default_mutability ----

def test_immutable_by_default_adds_mut_keyword():
    spec = build_spec({**BASE, "default_mutability": "immutable"}, "demo")
    assert "mut" in spec["keywords"]
    assert spec["variable_declaration"]["mutability"] == "immutable_by_default"
    assert "mut" in spec["variable_declaration"]["syntax_example"]


def test_mutable_by_default_unchanged():
    spec = build_spec({**BASE, "default_mutability": "mutable"}, "demo")
    assert "mut" not in spec["keywords"]
    assert spec["variable_declaration"]["mutability"] == "mutable_by_default"


# ---- error_handling ----

def test_error_handling_exceptions_adds_keywords():
    spec = build_spec({**BASE, "error_handling": "exceptions"}, "demo")
    assert spec["error_handling"]["kind"] == "exceptions"
    for kw in ("try", "catch", "throw"):
        assert kw in spec["keywords"]


def test_error_handling_result_type():
    spec = build_spec({**BASE, "error_handling": "result_type"}, "demo")
    assert spec["error_handling"]["kind"] == "result_type"


def test_error_handling_panic_default():
    spec = build_spec(BASE, "demo")
    assert spec["error_handling"]["kind"] == "panic_only"
    for kw in ("try", "catch", "throw"):
        assert kw not in spec["keywords"]


# ---- loop_forms ----

def test_loop_forms_multiselect():
    spec = build_spec({**BASE, "loop_forms": ["while", "c_for", "loop_break"]}, "demo")
    assert set(spec["loop_forms"]) == {"while", "c_for", "loop_break"}


def test_loop_forms_at_least_while_default():
    spec = build_spec(BASE, "demo")
    assert "while" in spec["loop_forms"]


# ---- multiple_returns + boolean_evaluation ----

def test_multiple_returns_tuple():
    spec = build_spec({**BASE, "multiple_returns": "tuple"}, "demo")
    assert spec["multiple_returns"] == "tuple"


def test_boolean_evaluation_eager():
    spec = build_spec({**BASE, "boolean_evaluation": "eager"}, "demo")
    assert spec["boolean_evaluation"] == "eager"


# ---- combinatorial smoke ----

def test_kitchen_sink_combo_validates():
    """A maximally-customized spec still validates."""
    spec = build_spec({
        **BASE,
        "comment_style": "nestable_block",
        "string_literals": "triple_quoted",
        "numeric_literals": "extended",
        "default_mutability": "immutable",
        "error_handling": "exceptions",
        "loop_forms": ["while", "c_for", "foreach", "repeat_until", "loop_break"],
        "multiple_returns": "tuple",
        "boolean_evaluation": "eager",
    }, "kitchen")
    validate_spec(spec)


def test_extended_options_compose_with_customization():
    """Extended options + user customization both apply on the same spec."""
    spec = build_spec(
        {**BASE, "default_mutability": "immutable", "error_handling": "exceptions"},
        "demo",
        customization={
            "keyword_overrides": {"var": "let"},
            "extra_design_notes": ["noted"],
        },
    )
    # Customization renamed `var` → `let`, and extended-options added `mut`.
    assert "let" in spec["keywords"]
    assert "mut" in spec["keywords"]
    assert "var" not in spec["keywords"]
    assert "noted" in spec["design_notes"]
    # error_handling stayed intact
    assert spec["error_handling"]["kind"] == "exceptions"
