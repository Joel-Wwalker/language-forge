"""Spec-driven source substitution.

# THE CONTRACT (Phase 1.5 bugfix Fix 2)
#
# Any code path that hands SOURCE CODE to a templated language for
# parsing must apply substitutions first, OR must route through the
# language's own codegen which handles substitutions internally.
#
# Otherwise: a themed c_like language (e.g. pirate phrasebook with
# `var → loot`) will refuse to parse canonical c_like source from
# the curated kata pack, and every kata fails. This was Bug 3 in
# Gate 2: 8 out of 12 smoke-failed slots all reported `kata: 0/12
# passed` because of this.

The substitution categories supported here:

  - keyword spelling (var → loot, func → yarrn, ...)
  - comment syntax (// → #, /* */ → ;...)
  - boolean / null literal rendering (true → aye, ...)

These came out of Phase 1.5 Stage A. Stage A's parameterized
`_template_from_reference` lived in `generator.py`. This module
extracts the pure substitution helpers so they can be called from
the kata system, the smoke validator, the case-analysis emitter,
and the kata translator's LLM path — anywhere source is handed to
a templated language for parsing.

`generator.py` now imports from here; the underscored names there
are thin aliases preserved for backward compatibility with existing
tests.

Public API:

    apply_spec_keyword_substitutions(source, spec, *, file_role)
        -- the dispatcher. Returns substituted source.

    keyword_overrides_from_spec(spec) -> dict[str, str]
        -- raw keyword override map.

    comment_syntax_from_spec(spec) -> dict
        -- normalized comment syntax with c_like defaults.
"""
from __future__ import annotations

import re
from typing import Optional


# Canonical keyword roles. Specs use these names internally; the spec's
# `customization.keyword_overrides` maps each role to a target-language
# spelling. Identity defaults apply when no override is set.
KEYWORD_ROLES = (
    "var", "func", "if", "else", "while", "return",
    "true", "false", "null",
)

# Toylang's defaults — used as the "old" comment markers when applying
# source-level comment substitution. The reference compiler uses c_like
# comment syntax; targets may differ.
_DEFAULT_COMMENT = {"line": "//", "block_open": "/*", "block_close": "*/"}


def keyword_overrides_from_spec(spec: dict) -> dict[str, str]:
    """Build a {canonical: spelling} mapping for keyword substitution.

    Sources, in priority order:
      1. `spec.customization.keyword_overrides` (already a {canon: spelling}
         dict; produced by themes / phrasebooks via spec_builder).
      2. Structured spec fields (`variable_declaration.keyword`,
         `function_definition.keyword`, ...) for cases where overrides
         got embedded structurally instead of via the override dict.

    Falls back to identity for any role not specified."""
    cust = spec.get("customization") or {}
    direct = dict(cust.get("keyword_overrides") or {})
    structured = {
        "var":    (spec.get("variable_declaration") or {}).get("keyword"),
        "func":   (spec.get("function_definition") or {}).get("keyword"),
        "if":     (spec.get("if_statement") or {}).get("keyword"),
        "else":   (spec.get("if_statement") or {}).get("else_keyword"),
        "while":  (spec.get("while_statement") or {}).get("keyword"),
        "return": (spec.get("return_statement") or {}).get("keyword"),
    }
    for role, value in structured.items():
        if value and role not in direct:
            direct[role] = value
    return {role: direct.get(role, role) for role in KEYWORD_ROLES}


def comment_syntax_from_spec(spec: dict) -> dict:
    """Return the spec's comment syntax. Defaults to c_like (// + /* */)
    when fields are absent."""
    cs = spec.get("comment_syntax") or {}
    return {
        "line": cs.get("line") or "//",
        "block_open": cs.get("block_open") or "/*",
        "block_close": cs.get("block_close") or "*/",
    }


# ---------------------------------------------------------------------------
# Per-target substitution primitives. Each operates on text and returns
# substituted text. They're kept separate (rather than collapsed into one
# big function) so callers can pick the right operation for their context
# and so each is independently testable.
# ---------------------------------------------------------------------------

def substitute_grammar_keywords(grammar: str,
                                overrides: dict[str, str]) -> str:
    """Substitute keyword spellings inside a Lark grammar string.

    Targets bare quoted-string occurrences like `"var"` or `"func"` —
    these are the anonymous tokens in toylang's grammar. Quotes are
    part of the match so we don't touch bare identifiers named after
    a keyword (e.g. a Python comment that happens to mention `var`).
    `re.escape` on the value prevents new spellings from being
    interpreted as regex metachars."""
    out = grammar
    for canon, new in overrides.items():
        if new == canon:
            continue
        out = re.sub(rf'"{re.escape(canon)}"', f'"{new}"', out)
    return out


def substitute_grammar_comments(grammar: str, comment: dict) -> str:
    """Substitute the `LINE_COMMENT` and `BLOCK_COMMENT` terminals in a
    Lark grammar string when the spec uses non-toylang comment syntax.
    Toylang's defaults are `//` line and `/* */` block."""
    out = grammar
    new_line = comment["line"]
    new_open = comment["block_open"]
    new_close = comment["block_close"]
    if new_line != "//":
        out = re.sub(
            r'LINE_COMMENT:\s*"//"',
            f'LINE_COMMENT: "{new_line}"',
            out,
        )
    if new_open != "/*" or new_close != "*/":
        out = re.sub(
            r'BLOCK_COMMENT:\s*"/\*"\s*/\(\.\|\\n\)\*\?/\s*"\*/"',
            f'BLOCK_COMMENT: "{re.escape(new_open)}" /(.|\\n)*?/ "{re.escape(new_close)}"',
            out,
        )
    return out


def substitute_source_keywords(source: str,
                               overrides: dict[str, str]) -> str:
    """Word-boundary substitution of keyword spellings in target-language
    source. `var x = 5;` → `let x = 5;` but `varying` stays `varying`.

    NOTE: doesn't currently distinguish keywords inside string literals
    from real keywords. For canonical kata sources this is fine in
    practice (no kata test source has a keyword-like word inside a
    string literal). Hardening to a real lexer-aware substitution is a
    future-Phase concern."""
    out = source
    for canon, new in overrides.items():
        if new == canon:
            continue
        out = re.sub(rf'\b{re.escape(canon)}\b', new, out)
    return out


def substitute_source_comments(source: str,
                               old: dict, new: dict) -> str:
    """Replace comment markers in a source file. Skips work when the
    syntax is unchanged."""
    out = source
    if new["line"] != old["line"]:
        out = out.replace(old["line"], new["line"])
    if new["block_open"] != old["block_open"]:
        out = out.replace(old["block_open"], new["block_open"])
    if new["block_close"] != old["block_close"]:
        out = out.replace(old["block_close"], new["block_close"])
    return out


def substitute_runtime_str_literals(runtime_src: str,
                                    overrides: dict[str, str]) -> str:
    """In runtime.py's `toy_str`, rendered names for True / False / None
    are baked in as `return "true"` / `return "false"` / `return "null"`.
    Substitute when the spec maps those keywords to new spellings —
    otherwise canonical tests fail (expected_output.txt would say
    `aye` but toy_str would still emit `true`)."""
    out = runtime_src
    for canon in ("true", "false", "null"):
        new = overrides.get(canon, canon)
        if new == canon:
            continue
        out = re.sub(
            rf'return\s+"{re.escape(canon)}"',
            f'return "{new}"',
            out,
        )
    return out


# ---------------------------------------------------------------------------
# Public dispatcher (the API the kata system uses)
# ---------------------------------------------------------------------------

def apply_spec_keyword_substitutions(source: str, spec: dict, *,
                                     file_role: str = "test_source") -> str:
    """Apply the spec's keyword / comment / string substitutions to a
    source string.

    Returns the source unchanged if the spec has no substitutions
    defined for the relevant categories. This makes the function safe
    to call unconditionally — callers don't need to check whether the
    spec is themed.

    Args:
        source: the source-code string to substitute.
        spec: the resolved spec, source of overrides.
        file_role: which substitution categories apply.
            - "test_source" (default): keywords + comments. The
              common case for kata sources, sample programs, etc.
            - "parser": grammar-aware substitution INSIDE a
              `GRAMMAR = r\"\"\"...\"\"\"` string literal in a
              parser.py source. Used by `_template_from_reference`
              when copying parser.py from a reference compiler.
            - "runtime": string-literal substitution for boolean
              rendering in `toy_str`. Used when copying runtime.py.
            - "expected_output": substitute true/false/null in
              expected_output.txt files so they match what the
              substituted runtime emits.
            - "module_swap_only": no-op for substitution purposes;
              caller has done module-name rewrite separately.
    """
    overrides = keyword_overrides_from_spec(spec)
    new_comment = comment_syntax_from_spec(spec)

    if file_role == "parser":
        m = re.search(r'(GRAMMAR\s*=\s*r?""")(.*?)(""")', source, re.DOTALL)
        if not m:
            return source
        head, body, tail = m.group(1), m.group(2), m.group(3)
        body = substitute_grammar_keywords(body, overrides)
        body = substitute_grammar_comments(body, new_comment)
        return source[:m.start()] + head + body + tail + source[m.end():]

    if file_role == "runtime":
        return substitute_runtime_str_literals(source, overrides)

    if file_role == "test_source":
        out = substitute_source_keywords(source, overrides)
        out = substitute_source_comments(out, _DEFAULT_COMMENT, new_comment)
        return out

    if file_role == "expected_output":
        # Just true/false/null — the only canonical-output tokens that
        # a spec might rename.
        out = source
        for canon in ("true", "false", "null"):
            new = overrides.get(canon, canon)
            if new != canon:
                out = re.sub(rf'\b{re.escape(canon)}\b', new, out)
        return out

    return source  # "module_swap_only" — caller handles separately


# ---------------------------------------------------------------------------
# Backward-compat aliases — let existing code that imports the
# underscored names from generator.py keep working without churn.
# Tests under tests/test_phase15_template_substitution.py use these.
# ---------------------------------------------------------------------------

_KEYWORD_ROLES = KEYWORD_ROLES
_keyword_overrides_from_spec = keyword_overrides_from_spec
_comment_syntax_from_spec = comment_syntax_from_spec
_substitute_grammar_keywords = substitute_grammar_keywords
_substitute_grammar_comments = substitute_grammar_comments
_substitute_source_keywords = substitute_source_keywords
_substitute_source_comments = substitute_source_comments
_substitute_runtime_str_literals = substitute_runtime_str_literals


def _apply_template_substitutions(spec: dict, source: str, *,
                                  file_role: str = "test_source") -> str:
    """Legacy alias preserving the (spec, source, file_role) parameter
    order used by `generator.py` and existing tests. The new public API
    `apply_spec_keyword_substitutions` flips to (source, spec) which
    reads more naturally for new callers in the kata system."""
    return apply_spec_keyword_substitutions(source, spec, file_role=file_role)
