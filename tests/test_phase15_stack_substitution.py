"""Phase 1.5 scope expansion — stack-based theming substitution.

# THE GAP (Gate 2 second-attempt)

Even after Phase 1.5's bugfix Fix 2 centralized the substitution layer
and routed it through the kata system, themed stack_based slots still
failed kata smoke at 1/13. The fix worked for c_like but the role set
KEYWORD_ROLES was c_like-only — `var`, `func`, `return`, `null`. None
of those are forthlang keywords. The 4 stack_based slots that hit
themed phrasebooks in Gate 2 (043, 046, 048, 050) had keyword_overrides
like `{"if": "ifnay", "while": "keelhaul", "null": "ghost"}` — and only
`if` was actually a forthlang keyword the substitution layer knew about.

# THE FIX

Per-family role lists in `substitution.py`:

  - `KEYWORD_ROLES_C_LIKE`   (existing — `var`, `func`, ..., `null`)
  - `KEYWORD_ROLES_STACK_BASED` (new — forthlang's substitutable
                                 parser keywords + true/false/nil)
  - `KEYWORD_ROLES_S_EXPRESSION` (placeholder)

`_roles_for_spec(spec)` picks the right tuple. `keyword_overrides_from_spec`
filters the spec's overrides to the family's roles AND translates
cross-family aliases (`null` -> `nil` for stack_based) so substitution
fires on the right source word.

`apply_spec_keyword_substitutions(file_role="parser")` dispatches to
`substitute_handrolled_parser_keywords` for stack_based (forthlang has
a hand-rolled parser with a `_KEYWORDS` dict, no Lark grammar).
`substitute_runtime_str_literals` handles BOTH `null` and `nil`.

These tests pin the contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.generator import _template_from_reference
from forge.orchestrator.katas import substitute_kata_for_target
from forge.orchestrator.substitution import (
    KEYWORD_ROLES,
    KEYWORD_ROLES_C_LIKE,
    KEYWORD_ROLES_STACK_BASED,
    KEYWORD_ROLES_S_EXPRESSION,
    _roles_for_spec,
    _syntax_family,
    apply_spec_keyword_substitutions,
    keyword_overrides_from_spec,
    substitute_handrolled_parser_keywords,
    substitute_runtime_str_literals,
)


WORKSPACE = Path(__file__).resolve().parents[1]
FORTHLANG_DIR = WORKSPACE / "generated" / "forthlang"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pirate_stack_spec(lang_name: str = "pirate_stack") -> dict:
    """Themed stack_based with realistic overrides matching the
    Gate 2 failing-slot pattern."""
    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        lang_name,
    )
    cust = dict(spec.get("customization") or {})
    # The resolver typically produces c_like-style keys; we mirror that
    # here so the test exercises the alias-translation path. Some keys
    # apply to stack_based directly (`if`, `else`, `while`, `true`,
    # `false`); others (`var`, `func`, `return`) get filtered out;
    # `null` aliases to `nil` for forthlang.
    cust["keyword_overrides"] = {
        "var": "loot",          # filtered (no `var` in forthlang)
        "func": "yarrn",        # filtered (no `func` in forthlang)
        "return": "deliver",    # filtered (no `return` in forthlang)
        "if": "ifnay",          # SUBSTITUTED
        "else": "elseways",     # SUBSTITUTED
        "while": "keelhaul",    # SUBSTITUTED (forthlang's begin/while/repeat)
        "true": "aye",          # SUBSTITUTED (boolean literal)
        "false": "nay",         # SUBSTITUTED (boolean literal)
        "null": "ghost",        # ALIASED to nil -> SUBSTITUTED
    }
    spec["customization"] = cust
    return spec


def _write_spec_for_verify(lang_dir: Path, spec: dict) -> None:
    (lang_dir / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Per-family role-set unit tests
# ---------------------------------------------------------------------------

def test_keyword_roles_c_like_unchanged():
    """The c_like role set still contains the canonical 9 roles. This
    pins backward compatibility — Phase 1.5 Stage A's tests rely on
    this exact tuple."""
    assert KEYWORD_ROLES_C_LIKE == (
        "var", "func", "if", "else", "while", "return",
        "true", "false", "null",
    )


def test_keyword_roles_stack_based_includes_forth_keywords():
    """The stack_based role set covers the multi-character keywords
    in forthlang's `_KEYWORDS` dict + boolean/null literals."""
    expected = {
        "if", "else", "then",
        "begin", "until", "again", "while", "repeat",
        "do", "loop",
        "variable", "constant",
        "true", "false", "nil",
    }
    assert set(KEYWORD_ROLES_STACK_BASED) == expected


def test_keyword_roles_stack_based_excludes_single_char_keywords():
    """`:` and `;` are NOT in the role set (single chars; tokenizer
    embeds them, can't be cleanly substituted). This pins the audit
    decision documented in substitution.py."""
    assert ":" not in KEYWORD_ROLES_STACK_BASED
    assert ";" not in KEYWORD_ROLES_STACK_BASED


def test_keyword_roles_stack_based_excludes_stack_primitives():
    """`dup`/`drop`/`swap`/etc. are NOT in the role set. They're NAME
    tokens at parse time; their meaning lives in codegen's
    `_PY_NAME_MAP`. Substituting them needs codegen rewrites that are
    out of Phase 1.5 scope (deferred to Phase 5)."""
    primitives = {"dup", "drop", "swap", "over", "rot", "nip", "tuck"}
    assert primitives.isdisjoint(KEYWORD_ROLES_STACK_BASED)


def test_keyword_roles_legacy_alias_is_c_like():
    """KEYWORD_ROLES (the legacy name) is the c_like tuple. Existing
    tests/imports keep working without modification."""
    assert KEYWORD_ROLES is KEYWORD_ROLES_C_LIKE


def test_roles_for_spec_dispatches_by_family():
    assert _roles_for_spec({"options": {"syntax": "c_like"}}) is KEYWORD_ROLES_C_LIKE
    assert _roles_for_spec({"options": {"syntax": "stack_based"}}) is KEYWORD_ROLES_STACK_BASED
    assert _roles_for_spec({"options": {"syntax": "s_expression"}}) is KEYWORD_ROLES_S_EXPRESSION
    # Unknown family -> default to c_like (the safest choice for
    # cross-family roles like if/else/true/false).
    assert _roles_for_spec({"options": {"syntax": "python_like"}}) is KEYWORD_ROLES_C_LIKE


# ---------------------------------------------------------------------------
# keyword_overrides_from_spec: filtering + alias translation
# ---------------------------------------------------------------------------

def test_overrides_filtered_by_family_for_stack_based():
    """A stack_based spec with c_like-style overrides keeps only the
    roles that apply: `if/else/while/true/false`. `var/func/return`
    are filtered out — they have no forthlang equivalent."""
    spec = _pirate_stack_spec()
    overrides = keyword_overrides_from_spec(spec)
    # Stack-based-applicable roles are present.
    assert overrides["if"] == "ifnay"
    assert overrides["else"] == "elseways"
    assert overrides["while"] == "keelhaul"
    assert overrides["true"] == "aye"
    assert overrides["false"] == "nay"
    # `null -> ghost` translates to `nil -> ghost` for forthlang.
    assert overrides["nil"] == "ghost"
    # c_like-only roles are not in the result for stack_based.
    assert "var" not in overrides
    assert "func" not in overrides
    assert "return" not in overrides
    # Identity for keys without overrides.
    assert overrides["then"] == "then"
    assert overrides["begin"] == "begin"


def test_overrides_clike_unchanged_after_refactor():
    """A c_like spec produces the same overrides as before the
    per-family refactor. Pins Phase 1.5 Stage A's contract."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "test_clike",
    )
    cust = dict(spec.get("customization") or {})
    cust["keyword_overrides"] = {
        "var": "let", "func": "fn", "if": "if", "else": "else",
        "while": "while", "return": "return",
        "true": "true", "false": "false", "null": "null",
    }
    spec["customization"] = cust
    overrides = keyword_overrides_from_spec(spec)
    assert overrides["var"] == "let"
    assert overrides["func"] == "fn"
    # All 9 c_like roles present.
    assert set(overrides.keys()) == set(KEYWORD_ROLES_C_LIKE)


def test_null_alias_does_not_clobber_explicit_nil():
    """If a stack_based spec carries BOTH `null` and `nil` overrides
    (unusual but possible), the explicit `nil` wins — the alias only
    applies when `nil` is absent."""
    spec = {
        "options": {"syntax": "stack_based"},
        "customization": {
            "keyword_overrides": {
                "null": "ghost",
                "nil": "void",  # explicit forthlang-spelling override
            },
        },
    }
    overrides = keyword_overrides_from_spec(spec)
    assert overrides["nil"] == "void"


# ---------------------------------------------------------------------------
# Hand-rolled parser substitution
# ---------------------------------------------------------------------------

def test_substitute_handrolled_parser_keywords_basic():
    """Substitutes dict-key strings of the form `"<canon>":` in a
    forthlang-shaped _KEYWORDS dict."""
    src = (
        '_KEYWORDS = {\n'
        '    ":": "COLON", ";": "SEMI",\n'
        '    "if": "IF", "else": "ELSE", "then": "THEN",\n'
        '}\n'
    )
    out = substitute_handrolled_parser_keywords(src, {
        "if": "arrr", "else": "or_else", "then": "ahoy",
    })
    assert '"arrr": "IF"' in out
    assert '"or_else": "ELSE"' in out
    assert '"ahoy": "THEN"' in out
    # Single-character keywords NOT touched.
    assert '":": "COLON"' in out
    assert '";": "SEMI"' in out


def test_substitute_handrolled_parser_keywords_no_overrides():
    """Identity overrides leave the source unchanged."""
    src = '_KEYWORDS = {"if": "IF", "do": "DO"}\n'
    out = substitute_handrolled_parser_keywords(src, {
        "if": "if", "do": "do",
    })
    assert out == src


def test_substitute_handrolled_parser_keywords_against_real_forthlang():
    """Sanity: applying a realistic override set to forthlang's actual
    parser.py produces a parser whose `_KEYWORDS` dict has the new
    spellings AND the parser still imports cleanly."""
    parser_src = (FORTHLANG_DIR / "parser.py").read_text(encoding="utf-8")
    overrides = {
        "if": "ifnay", "else": "elseways",
        "do": "commence", "loop": "pillage",
    }
    out = substitute_handrolled_parser_keywords(parser_src, overrides)
    assert '"ifnay": "IF"' in out
    assert '"elseways": "ELSE"' in out
    assert '"commence": "DO"' in out
    assert '"pillage": "LOOP"' in out
    # Other keywords unchanged.
    assert '"begin": "BEGIN"' in out
    assert '"variable": "VARIABLE"' in out


# ---------------------------------------------------------------------------
# Family-isolation tests (the main argument for per-family role sets)
# ---------------------------------------------------------------------------

def test_clike_spec_does_not_substitute_stack_keywords():
    """A c_like-themed source string with `then`/`begin`/`do` (which
    are c_like-irrelevant words) should NOT be substituted by a
    c_like spec. Only `var`/`func`/`if`/`return`/etc. are targeted."""
    spec = {
        "options": {"syntax": "c_like"},
        "customization": {"keyword_overrides": {"var": "let"}},
    }
    src = "var x = 5; then begin do something;"
    out = apply_spec_keyword_substitutions(src, spec, file_role="test_source")
    # `var` substituted.
    assert "let x = 5" in out
    # Stack-based keywords still present (they're irrelevant for c_like).
    assert "then begin do" in out


def test_stack_spec_does_not_substitute_clike_keywords():
    """A stack_based spec's overrides only fire on stack_based keywords.
    A `var` key in the override dict is filtered out by
    keyword_overrides_from_spec, so the substitution layer never
    substitutes `var` even if the canonical word `var` appears in the
    source."""
    spec = {
        "options": {"syntax": "stack_based"},
        "customization": {"keyword_overrides": {
            "var": "loot",      # filtered
            "if": "ifnay",      # applies
        }},
    }
    src = "var x if cond then end"
    out = apply_spec_keyword_substitutions(src, spec, file_role="test_source")
    # `if` substituted.
    assert "ifnay" in out
    # `var` NOT substituted (filtered out for stack_based).
    assert "var x" in out
    assert "loot" not in out


# ---------------------------------------------------------------------------
# Runtime literal substitution: handles both `null` and `nil`
# ---------------------------------------------------------------------------

def test_runtime_substitution_handles_nil_for_stack_based():
    """forthlang's `_toy_str` returns `"nil"` for None. A spec that
    overrides null (via the `null` role name in c_like-style or `nil`
    directly) gets the runtime substituted."""
    forthlang_runtime_excerpt = (
        'def _toy_str(v):\n'
        '    if v is True: return "true"\n'
        '    if v is False: return "false"\n'
        '    if v is None: return "nil"\n'
        '    return str(v)\n'
    )
    overrides = {"true": "aye", "false": "nay", "nil": "ghost"}
    out = substitute_runtime_str_literals(forthlang_runtime_excerpt, overrides)
    assert 'return "aye"' in out
    assert 'return "nay"' in out
    assert 'return "ghost"' in out
    # No leftover canonical spellings.
    assert 'return "nil"' not in out


def test_runtime_substitution_handles_null_for_c_like():
    """toylang's `toy_str` returns `"null"` for None. The same helper
    works for both shapes."""
    toylang_runtime_excerpt = (
        'def toy_str(v):\n'
        '    if v is True: return "true"\n'
        '    if v is False: return "false"\n'
        '    if v is None: return "null"\n'
        '    return str(v)\n'
    )
    overrides = {"true": "aye", "false": "nay", "null": "ghost"}
    out = substitute_runtime_str_literals(toylang_runtime_excerpt, overrides)
    assert 'return "aye"' in out
    assert 'return "nay"' in out
    assert 'return "ghost"' in out


# ---------------------------------------------------------------------------
# Slow integration test: themed stack_based passes smoke
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_themed_stack_based_kata_pack_passes_smoke(tmp_path):
    """The Gate 2 acceptance test for Work 1. Build a pirate-themed
    stack_based by templating from forthlang + applying substitutions,
    then run smoke. The kata pack MUST pass at parity with non-themed
    stack_based (with at most 1 slot of slack for content edge cases).

    Pre-fix: kata 1/13 across the 4 themed stack_based slots.
    Post-fix: target ≥ 12/13."""
    from forge.catalog.smoke_test import smoke_test

    spec = _pirate_stack_spec(lang_name="pirate_smoke")
    lang_dir = tmp_path / "pirate_smoke"
    lang_dir.mkdir()
    _write_spec_for_verify(lang_dir, spec)

    fulfilled = _template_from_reference(spec, lang_dir, FORTHLANG_DIR)
    # forthlang doesn't ship with the same component set as toylang;
    # at minimum parser + codegen + runtime + tests should be templated.
    assert "parser" in fulfilled
    assert "codegen" in fulfilled
    assert "runtime" in fulfilled
    assert "tests" in fulfilled

    # Sanity-check the templated parser has the new spellings.
    parser_text = (lang_dir / "parser.py").read_text(encoding="utf-8")
    assert '"ifnay": "IF"' in parser_text
    assert '"elseways": "ELSE"' in parser_text

    res = smoke_test(lang_dir)

    # Canonical must pass (same baseline as non-themed stack_based).
    assert res.canonical["passed"] == res.canonical["total"], (
        f"canonical regressed on themed stack_based: {res.failures}"
    )

    # Kata MUST be present (stack_based -> stack_classics).
    assert res.kata is not None, "expected curated 'stack_classics' pack"
    assert res.kata["pack_key"] == "stack_classics"
    assert res.kata["total"] > 0

    # The acceptance bar: at least 12 of 13 katas pass. Pre-fix only
    # 1 passed. Some katas may legitimately fail because they use
    # stack-manipulation primitives (`dup`, `drop`, etc.) that are
    # out-of-scope for substitution per Phase 1.5 expansion. The slack
    # accounts for that.
    assert res.kata["passed"] >= res.kata["total"] - 1, (
        f"themed stack_based kata pass count was {res.kata['passed']}/"
        f"{res.kata['total']}; pre-fix this was 1. "
        f"failures: {res.failures}"
    )


# ---------------------------------------------------------------------------
# substitute_kata_for_target on stack_based
# ---------------------------------------------------------------------------

def test_substitute_kata_for_target_on_stack_based():
    """The kata substitution helper picks up forthlang keywords now."""
    spec = _pirate_stack_spec()
    kata = {
        "id": "factorial",
        "reference_solution": (
            ": factorial ( n -- n! )\n"
            "    dup 1 <= if drop 1 else dup 1 - factorial * then ;\n"
        ),
        "tests": [
            {"call": "5 factorial", "expected": "120"},
            {"call": "is_zero(0)", "expected": "true"},
            {"call": "missing()", "expected": "nil"},
        ],
    }
    out = substitute_kata_for_target(kata, spec)
    # `if` and `else` and `then` substituted in source.
    assert "ifnay" in out["reference_solution"]
    assert "elseways" in out["reference_solution"]
    # Stack primitives like `dup`/`drop` NOT touched.
    assert "dup" in out["reference_solution"]
    assert "drop" in out["reference_solution"]
    # Boolean / nil expected outputs substituted.
    assert out["tests"][1]["expected"] == "aye"
    assert out["tests"][2]["expected"] == "ghost"
    # Numeric expected unchanged.
    assert out["tests"][0]["expected"] == "120"
