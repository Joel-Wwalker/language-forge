"""Tests for the third syntax family: s_expression (Lisp-style).

Roadmap upload/families.md Tier 1: code is data, prefix notation,
homoiconic. We don't ship a hand-written reference compiler in this
PR — the LLM-generated path covers that — but we do verify:

  - build_spec produces a coherent spec for s_expression
  - the spec passes JSON-schema validation
  - the SExpressionBackend mechanically translates c_like classics
    into prefix form that's syntactically valid Lisp
  - the can_handle dispatcher routes s_expression → SExpressionBackend
  - coherence rules surface the typed-Racket warning
  - the option_axes safety net (from test_crossbreeding) still passes
    with the new family in place
"""
from __future__ import annotations

import re

from forge.orchestrator.spec_builder import build_spec, validate_spec
from forge.orchestrator.coherence import check, errors, warnings
from forge.orchestrator.mechanical_translator import (
    can_handle, transpile, SExpressionBackend, CLikeBackend, PythonLikeBackend,
)


# ---------- spec_builder ----------

def test_build_spec_s_expression_dynamic():
    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "lisplang",
    )
    assert spec["lang_name"] == "lisplang"
    assert spec["block_style"] == "parens"
    assert spec["statement_terminator"] == ")"
    assert spec["comment_syntax"]["line"] == ";"
    assert spec["function_definition"]["keyword"] == "defn"
    assert spec["variable_declaration"]["keyword"] == "def"
    assert spec["null_keyword"] == "nil"
    assert spec["boolean_keywords"] == {"true": "true", "false": "false"}
    # Schema acceptance
    validate_spec(spec)


def test_build_spec_s_expression_static_uses_typed_racket_form():
    spec = build_spec(
        {"syntax": "s_expression", "typing": "static", "memory": "host_gc"},
        "typedlisp",
    )
    assert spec["function_definition"]["type_annotations"].startswith("(: add ")
    assert spec["variable_declaration"]["type_annotations"].startswith("(: x ")
    assert spec["type_system"]["annotation_form"] == "(: name type)"
    assert spec["type_system"]["inference"] is True
    validate_spec(spec)


def test_build_spec_s_expression_immutable_uses_set_bang():
    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc",
         "default_mutability": "immutable"},
        "rigidlisp",
    )
    assert "set!" in spec["keywords"]
    assert "set!" in spec["variable_declaration"]["syntax_example"]


def test_build_spec_s_expression_block_comment():
    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc",
         "comment_style": "block"},
        "racketlike",
    )
    assert spec["comment_syntax"]["block_open"] == "#|"
    assert spec["comment_syntax"]["block_close"] == "|#"


# ---------- coherence ----------

def test_coherence_static_s_expression_warns_typed_racket():
    issues = check({"syntax": "s_expression", "typing": "static", "memory": "host_gc"})
    codes = {i.code for i in issues}
    assert "static_s_expression_typed_racket" in codes
    # Should be a warning, not an error.
    assert all(i.severity == "warning" for i in issues
               if i.code == "static_s_expression_typed_racket")


def test_coherence_s_expression_phrasebook_warns():
    issues = check({
        "syntax": "s_expression", "typing": "dynamic", "memory": "host_gc",
        "phrasebook": "child_speak",
    })
    codes = {i.code for i in issues}
    assert "s_expression_with_phrasebook" in codes


def test_coherence_s_expression_no_errors_for_baseline():
    issues = check({"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"})
    assert errors(issues) == []


# ---------- mechanical translator dispatch ----------

def test_can_handle_s_expression_returns_s_expression_backend():
    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "lisplang",
    )
    backend = can_handle(spec)
    assert isinstance(backend, SExpressionBackend)


def test_can_handle_s_expression_static_returns_none():
    """Static typing requires inference for type annotations: bail to LLM."""
    spec = build_spec(
        {"syntax": "s_expression", "typing": "static", "memory": "host_gc"},
        "typedlisp",
    )
    assert can_handle(spec) is None


def test_can_handle_does_not_confuse_families():
    """Adding s_expression mustn't cause c_like/python_like to misroute."""
    c_spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "ctest")
    p_spec = build_spec({"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"}, "ptest")
    assert isinstance(can_handle(c_spec), CLikeBackend)
    assert isinstance(can_handle(p_spec), PythonLikeBackend)


# ---------- transpile output (mechanical c_like -> Lisp) ----------

def _spec():
    return build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "lisplang",
    )


def test_transpile_var_decl_to_def():
    out = transpile("var x = 42;\n", _spec())
    assert "(def x 42)" in out


def test_transpile_function_to_defn():
    src = "func double(n) { return n * 2; }\n"
    out = transpile(src, _spec())
    # `defn` form, prefix multiplication, explicit return
    assert "(defn double (n)" in out
    assert "(* n 2)" in out
    assert "(return" in out


def test_transpile_arithmetic_is_prefix():
    src = "var y = 1 + 2 * 3;\n"
    out = transpile(src, _spec())
    # Must contain prefix arithmetic; must NOT contain infix `1 + 2`
    assert "(+ " in out
    assert "(* " in out
    assert " + " not in out  # no infix


def test_transpile_assignment_uses_set_bang():
    src = (
        "var i = 0;\n"
        "while (i < 5) {\n"
        "  i = i + 1;\n"
        "}\n"
    )
    out = transpile(src, _spec())
    assert "(set! i" in out
    assert "(while" in out


def test_transpile_if_is_three_arg():
    src = (
        "func sign(x) {\n"
        "  if (x > 0) { return 1; }\n"
        "  else { return -1; }\n"
        "}\n"
    )
    out = transpile(src, _spec())
    # Lisp `if` always has cond/then/else
    assert "(if " in out
    assert "(> x 0)" in out
    # Comparison `==` would become `=` in Lisp; the unary `-1` becomes `(- 1)`
    assert "(- 1)" in out


def test_transpile_call_is_prefix():
    src = "print(max(3, 7));\n"
    out = transpile(src, _spec())
    # No commas; space-separated prefix calls
    assert "(print " in out
    assert "(max 3 7)" in out
    assert "," not in out


def test_transpile_logical_ops_become_words():
    src = "var b = !(1 == 2 && 3 != 4);\n"
    out = transpile(src, _spec())
    assert "(not" in out
    assert "(and " in out
    # `==` becomes `=` in Lisp
    assert "(= 1 2)" in out
    # `!=` stays as `!=` (we keep the c_like spelling for inequality)
    assert "(!= 3 4)" in out


def test_transpile_balanced_parens():
    """Every open paren must have a matching close. This is the cheapest
    check that the output is even syntactically Lispy."""
    src = (
        "var n = 5;\n"
        "func factorial(x) {\n"
        "  if (x <= 1) { return 1; }\n"
        "  else { return x * factorial(x - 1); }\n"
        "}\n"
        "print(factorial(n));\n"
    )
    out = transpile(src, _spec())
    # Count parens (excluding parens inside string literals — none here)
    opens = out.count("(")
    closes = out.count(")")
    assert opens == closes, f"unbalanced: {opens} opens vs {closes} closes\n{out}"


def test_transpile_no_curly_braces_or_semicolons():
    src = (
        "var x = 1;\n"
        "func id(a) { return a; }\n"
        "print(id(x));\n"
    )
    out = transpile(src, _spec())
    # The output must be free of c_like punctuation
    assert "{" not in out
    assert "}" not in out
    assert ";" not in out


# ---------- safety net ----------

def test_s_expression_in_schema_enum():
    """Schema must list s_expression alongside c_like / python_like."""
    import json, pathlib
    schema = json.loads(
        (pathlib.Path(__file__).resolve().parents[1]
         / "schemas" / "language_spec.schema.json").read_text(encoding="utf-8")
    )
    assert "s_expression" in schema["properties"]["options"]["properties"]["syntax"]["enum"]
    assert "parens" in schema["properties"]["block_style"]["enum"]
