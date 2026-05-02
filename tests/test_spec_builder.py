"""Tests for the deterministic spec builder."""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from forge.orchestrator.spec_builder import build_spec, load_schema, validate_spec


SCHEMA = load_schema()
VALIDATOR = Draft7Validator(SCHEMA)

ALL_OPTIONS = list(itertools.product(
    ["c_like", "python_like"],
    ["static", "dynamic"],
    ["host_gc", "refcount"],
))


@pytest.mark.parametrize("syntax,typing,memory", ALL_OPTIONS)
def test_build_spec_validates_for_all_combos(syntax, typing, memory):
    opts = {"syntax": syntax, "typing": typing, "memory": memory}
    spec = build_spec(opts, "demo")
    # Schema validation should be silent.
    validate_spec(spec)
    assert spec["lang_name"] == "demo"
    # The user's three option choices must appear verbatim. Extended options
    # may be filled in with defaults (validated separately in test_extended_options.py).
    for k, v in opts.items():
        assert spec["options"][k] == v


def test_example_toylang_spec_validates():
    path = Path(__file__).resolve().parents[1] / "schemas" / "example_toylang_spec.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    validate_spec(spec)


def test_c_like_uses_braces_and_semicolons():
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "lang")
    assert spec["block_style"] == "braces"
    assert spec["statement_terminator"] == ";"
    assert spec["comment_syntax"]["line"] == "//"


def test_python_like_uses_indent_and_newlines():
    spec = build_spec({"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"}, "lang")
    assert spec["block_style"] == "indent"
    assert spec["statement_terminator"] == "newline"
    assert spec["comment_syntax"]["line"] == "#"


def test_static_typing_sets_type_system():
    spec = build_spec({"syntax": "c_like", "typing": "static", "memory": "host_gc"}, "lang")
    assert "type_system" in spec
    assert "int" in spec["type_system"]["primitive_types"]


def test_dynamic_typing_omits_or_nullifies_annotations():
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "lang")
    assert spec["function_definition"]["type_annotations"] is None
    assert spec["variable_declaration"]["type_annotations"] is None


def test_memory_overlay_documents_choice():
    for mem in ("host_gc", "refcount"):
        spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": mem}, "lang")
        assert spec["memory_model"]["kind"] == mem
        assert spec["memory_model"]["notes"]
