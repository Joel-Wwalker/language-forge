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


# Canonical keyword roles per syntax family.
#
# Phase 1.5 scope expansion: previously KEYWORD_ROLES was a single flat
# tuple of c_like role names ("var", "func", "if", ...). That worked
# fine for c_like but produced silent no-ops on stack_based: themed
# stack_based slots had `keyword_overrides = {"if": "ifnay", ...}` but
# the substitution layer didn't know forthlang's parser also has `then`,
# `begin`, `until`, `do`, `loop`, `variable`, `constant` as keywords —
# and forthlang renders null as `nil`, not `null`. The result: only
# 1/13 katas passed in 4 themed stack_based slots in Gate 2.
#
# The fix: per-family role lists. The dispatcher picks the right tuple
# based on the spec's syntax. This keeps c_like and stack_based
# overrides from accidentally cross-pollinating (a c_like-themed `var`
# override doesn't try to rewrite stack_based source, and vice versa).
#
# Each tuple lists role NAMES (the keys the spec's keyword_overrides
# dict uses). The tuple order doesn't matter; the substitution applies
# in dict-iteration order.
KEYWORD_ROLES_C_LIKE = (
    "var", "func", "if", "else", "while", "return",
    "true", "false", "null",
)

# Forth (forthlang) parser keywords that are CLEANLY substitutable.
# Audited from generated/forthlang/parser.py:_KEYWORDS dict and
# generated/forthlang/runtime.py:_toy_str.
#
# EXCLUDED from substitution (and why):
#   - `:` `;`   single chars; embedded in tokenizer special-case logic
#   - `."` `s"` string-literal openers, hardcoded in tokenizer
#   - `(` `)`   paren comments, hardcoded in tokenizer
#   - `\\`      line comment, hardcoded in tokenizer
#   - `dup` / `drop` / `swap` / etc.   stack manipulation primitives.
#                These are NAME tokens at parse time; their meaning is
#                in codegen's `_PY_NAME_MAP`. Substituting them would
#                require codegen rewrites in addition to source rewrites
#                (out of scope for Phase 1.5; deferred to Phase 5).
#
# `nil` is forthlang's spelling for null. The role name MATCHES the
# canonical word in source — the role-name "nil" is what
# keyword_overrides uses as the key. (For c_like the equivalent role
# name is "null" because toylang renders null as `null`.)
KEYWORD_ROLES_STACK_BASED = (
    "if", "else", "then",
    "begin", "until", "again", "while", "repeat",
    "do", "loop",
    "variable", "constant",
    "true", "false", "nil",
)

# s_expression / lisplang. Only the cross-family roles for now. lisplang
# has its own keywords (`define`, `lambda`, `cond`, ...) but Phase 1.5
# Stage A's substitution work targeted c_like, and themed lisplang slots
# weren't part of the Gate 2 failure set. Keep this here as a placeholder
# so the per-family dispatch is uniform; when themed s_expression slots
# need substitution coverage, expand the tuple.
KEYWORD_ROLES_S_EXPRESSION = (
    "if", "else", "true", "false", "null",
)

# mllang ML-family keywords. Audited from generated/mllang/parser.py's
# GRAMMAR + the reserved-keyword negative-lookahead in NAME's regex.
# These all appear as anonymous string literals in the grammar
# (e.g. `"let"`, `"rec"`, `"match"`, ...) which Lark's keyword-resolution
# treats as terminals outranking NAME. Substitution rewrites these in
# both the parser source AND the test sources, so a themed mllang with
# `let -> define` re-spells the grammar AND the canonical test bodies.
#
# EXCLUDED from substitution (and why):
#   - `::`       cons operator; a multi-char operator, not a word.
#                Substituting would require rewriting parser operator
#                tables, not just the GRAMMAR string.
#   - `->`       function-arrow operator; same reason as `::`.
#   - `;;`       top-level terminator; a literal in the grammar but
#                substituting it would require concurrent rewrites in
#                every test source's terminator. Deferred for v1.
#   - `=`, `|`, `^`, `+.`, `-.`, `*.`, `/.`   operators, not words.
KEYWORD_ROLES_ML_LIKE = (
    "let", "rec", "in",
    "if", "then", "else",
    "match", "with", "type", "of", "fun",
    "mod", "not",
    "true", "false",
)

# logic_like / prologlang keywords. Audited from generated/prologlang/
# parser.py's GRAMMAR + ATOM_NAME's negative lookahead + the base
# spec's keywords list.
#
# Logic programming is operator-heavy, not keyword-heavy. Most of
# Prolog's "vocabulary" is built-in predicates (`write`, `nl`, `length`,
# `member`, ...) which are NOT keywords at parse time — they're regular
# atom tokens whose meaning is set by runtime dispatch. Substituting
# them would require concurrent rewrites in stdlib.register_builtins,
# which is out of scope for the parser-grammar substitution layer.
# That's the same exclusion logic that kept `print_int` out of
# KEYWORD_ROLES_ML_LIKE.
#
# IN: words that appear as anonymous string terminals in the grammar
# (so substituting them re-spells the parser) OR as atoms in test
# sources that benefit from rename.
#   - `is`     : infix operator in grammar (`cmp_expr ... "is" add_expr`)
#                + reserved via ATOM_NAME negative lookahead. Substitution
#                fires in the parser (so source `X equals 2 + 3` parses)
#                AND codegen normalizes the parsed `is_op` tree node to
#                `Compound("is", [...])` regardless of source spelling.
#                Result: `is` substitutes cleanly end-to-end.
#   - `not`    : in the keywords list for parity with other families,
#                but logic_like grammar uses `\+` for negation instead
#                of a `not` keyword. Including the role still allows
#                themes/phrasebooks to assert it without breaking parse.
#   - `true`   : an atom; substitutes cleanly in test source.
#   - `false`  : ditto.
#   - `fail`   : an atom usable as a built-in goal; substitutes cleanly.
#
# EXCLUDED from substitution (and why):
#   - `mod`    : infix operator in `MUL_OP` enum AND grammar emits the
#                source token through to codegen (which builds a generic
#                Compound for binops, passing the operator name verbatim).
#                Substituting `mod -> remainder` in source makes the
#                parser accept `remainder`, but codegen emits
#                `Compound("remainder", [...])` which the runtime's
#                `_eval_arith` doesn't recognize — `is/2` fails silently.
#                Excluded from substitution. This is a documented seam-
#                resistance finding (LOGICLANG_DESIGN.md §9): unlike
#                mllang's `mod` (which codegen lowers to Python `%`),
#                logic_like operators are first-class terms whose
#                identity reaches the runtime dispatch. A future
#                expansion could add an alias table to `_eval_arith`,
#                routed through the spec — out of scope for v1.
#   - `:-`     : multi-char rule operator. Same exclusion logic as
#                mllang's `::` — would require operator-table rewrites
#                beyond the substitution layer's scope.
#   - `?-`     : directive marker; multi-char. Excluded.
#   - `\+`     : negation-as-failure; multi-char operator. Excluded.
#   - `,` `;` `|` : conjunction / disjunction / cons-tail operators.
#   - `=` `=:=` `=\=` `<` `>` `=<` `>=` `==` `\==` `\=`   : operators.
#   - `+` `-` `*` `/` `//` `**` : arithmetic operators (used inside is/2).
#   - `.`      : clause terminator; substituting it would change every
#                clause's end-marker and is too invasive for v1.
#   - Built-in predicate names (`write`, `nl`, `length`, `append`,
#     `member`, `reverse`, `atom`, `number`, `integer`, `var`, `nonvar`,
#     `is_list`, `once`, `call`, `findall`) : atom tokens at parse time,
#     but their meaning is set by stdlib.register_builtins. Substituting
#     them in source without concurrent stdlib rewrites would emit goals
#     that fall through to "no clauses defined" and silently fail.
#     Deferred to a future expansion that wires substitution into
#     stdlib's builtin registration.
KEYWORD_ROLES_LOGIC_LIKE = (
    "is", "not",
    "true", "false", "fail",
)

# Default fallback (for unknown / missing syntax). c_like is the most
# common family and the safest default — its role names overlap with
# stack_based and s_expression on `if/else/while/true/false/null` so
# substitution there is at worst a no-op when the canonical word
# doesn't appear.
KEYWORD_ROLES = KEYWORD_ROLES_C_LIKE  # legacy public alias


_ROLES_BY_FAMILY: dict[str, tuple[str, ...]] = {
    "c_like":       KEYWORD_ROLES_C_LIKE,
    "stack_based":  KEYWORD_ROLES_STACK_BASED,
    "s_expression": KEYWORD_ROLES_S_EXPRESSION,
    "ml_like":      KEYWORD_ROLES_ML_LIKE,
    "logic_like":   KEYWORD_ROLES_LOGIC_LIKE,
    # python_like deferred: no reference compiler exists yet (Phase 5).
}


def _syntax_family(spec: dict) -> str:
    """Return the spec's syntax family, defaulting to c_like."""
    return ((spec.get("options") or {}).get("syntax") or "c_like")


def _roles_for_spec(spec: dict) -> tuple[str, ...]:
    """Return the keyword-role tuple appropriate for this spec's family."""
    return _ROLES_BY_FAMILY.get(_syntax_family(spec), KEYWORD_ROLES_C_LIKE)


# Per-family canonical comment markers — used as the "old" markers when
# applying source-level comment substitution against a templated test
# file. The reference compiler's source uses these; targets may differ.
_DEFAULT_COMMENT_BY_FAMILY: dict[str, dict] = {
    "c_like":       {"line": "//", "block_open": "/*", "block_close": "*/"},
    "stack_based":  {"line": "\\", "block_open": "(",  "block_close": ")"},
    "s_expression": {"line": ";",  "block_open": "#|", "block_close": "|#"},
    # ml_like has no line comments; nested block `(* *)`.
    "ml_like":      {"line": None, "block_open": "(*", "block_close": "*)"},
    # logic_like uses `%` line comments and `/* */` non-nesting block.
    # Without this entry, the substitution layer falls back to c_like
    # defaults, sees `//` in a logic_like test source (used as integer
    # divide), and rewrites it to `%` (logic_like's line comment) -
    # breaking the parser because the `//` was arithmetic, not a comment.
    "logic_like":   {"line": "%", "block_open": "/*", "block_close": "*/"},
}

# Backward-compat — c_like default for code paths that haven't been
# parameterized by family yet.
_DEFAULT_COMMENT = _DEFAULT_COMMENT_BY_FAMILY["c_like"]


def _default_comment_for_spec(spec: dict) -> dict:
    """Return the canonical comment markers for this spec's family.
    Used when substituting source-level comment markers in a kata or
    test file: we substitute the family's canonical markers to whatever
    the spec defines."""
    return _DEFAULT_COMMENT_BY_FAMILY.get(_syntax_family(spec),
                                          _DEFAULT_COMMENT_BY_FAMILY["c_like"])


def keyword_overrides_from_spec(spec: dict) -> dict[str, str]:
    """Build a {canonical: spelling} mapping for keyword substitution,
    filtered to the spec's syntax family.

    Sources, in priority order:
      1. `spec.customization.keyword_overrides` (already a {canon: spelling}
         dict; produced by themes / phrasebooks via spec_builder).
      2. Structured spec fields (`variable_declaration.keyword`,
         `function_definition.keyword`, ...) for cases where overrides
         got embedded structurally instead of via the override dict.

    The result is intersected with the family's `KEYWORD_ROLES_*` tuple,
    so c_like roles like `var`/`func`/`return` don't leak into a
    stack_based substitution (where they have no meaning) and
    stack_based roles like `then`/`begin` don't leak into c_like.

    Phase 1.5 scope-expansion note: stack_based slots produced by the
    resolver tend to carry c_like-style override keys (`var`, `func`,
    `null`) because the resolver doesn't know about per-family role
    sets. These get filtered here. Cross-family roles that DO apply
    (`if`, `else`, `while`, `true`, `false`) pass through. The `null`
    role's stack_based equivalent is `nil` — if a stack_based spec
    has `{"null": "ghost"}` we translate it to `{"nil": "ghost"}` so
    the substitution actually fires on forthlang's `nil` token.

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

    family = _syntax_family(spec)
    roles = _ROLES_BY_FAMILY.get(family, KEYWORD_ROLES_C_LIKE)

    # Cross-family abstract-role aliases. The spec might carry an
    # override under a c_like-style role name (`null`) that maps to a
    # different canonical word in this family (`nil`). Rewrite the key
    # so substitution fires on the right source token.
    #
    # The mapping is one-way (alias_in_spec -> word_in_this_family).
    # Only applies when the family doesn't already have the alias as
    # a real role. If the spec's `null` doesn't have a stack_based
    # equivalent (e.g., role `var` on a stack_based slot), it's
    # silently dropped — that's the filter's job.
    _ALIASES_TO_FAMILY = {
        "stack_based": {"null": "nil"},
        # c_like uses `null` natively, no alias needed.
        # s_expression uses `null` in our prompts, no alias needed.
    }
    aliases = _ALIASES_TO_FAMILY.get(family, {})
    for alias_key, family_key in aliases.items():
        if alias_key in direct and family_key not in direct:
            direct[family_key] = direct[alias_key]

    return {role: direct.get(role, role) for role in roles}


def comment_syntax_from_spec(spec: dict) -> dict:
    """Return the spec's comment syntax. Defaults to the family's
    canonical comment markers when fields are absent (c_like uses //,
    stack_based uses \\, s_expression uses ;)."""
    cs = spec.get("comment_syntax") or {}
    fam_default = _default_comment_for_spec(spec)
    return {
        "line": cs.get("line") or fam_default["line"],
        "block_open": cs.get("block_open") or fam_default["block_open"],
        "block_close": cs.get("block_close") or fam_default["block_close"],
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


def substitute_handrolled_parser_keywords(parser_src: str,
                                          overrides: dict[str, str]) -> str:
    """Substitute keyword spellings inside a HAND-ROLLED parser's
    `_KEYWORDS` dict (forthlang-style).

    Phase 1.5 scope expansion: forthlang's parser is hand-rolled (it
    handles context-sensitive Forth tokenization that Lark can't do
    cleanly). Its keyword set lives in a Python dict literal:

        _KEYWORDS = {
            ":": "COLON", ";": "SEMI",
            "if": "IF", "else": "ELSE", "then": "THEN",
            ...
        }

    For a themed stack_based language, we want `_KEYWORDS["arrr"]` to
    resolve to `IF` instead of `_KEYWORDS["if"]`. We do that by
    rewriting the dict-key strings: `"if":` becomes `"<new>":`.

    The match pattern `"<canon>":` is specific enough to avoid
    accidental hits on bare identifiers in code or comments. The
    forthlang parser's tokenization functions reference these keys
    via dict lookup (`_KEYWORDS[word]`) — they don't hardcode the
    spelling anywhere else, so substituting just the dict keys is
    sufficient.

    Caveat: this is forthlang-specific. If another hand-rolled parser
    appears with a different keyword-table shape, we'd need a parallel
    substituter for it. For now, only forthlang has this shape."""
    out = parser_src
    for canon, new in overrides.items():
        if new == canon:
            continue
        # Match `"canon":` with optional whitespace before the colon.
        # Quotes anchor on dict-key literals; the trailing `:` ensures
        # we only hit dict entries, not string literals used as values
        # or in comments.
        out = re.sub(
            rf'"{re.escape(canon)}"\s*:',
            f'"{new}":',
            out,
        )
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
    """In runtime.py's `toy_str` / `_toy_str`, rendered names for
    True / False / None are baked in as `return "true"` / `return
    "false"` / `return "null"` (toylang) or `return "nil"` (forthlang).
    Substitute when the spec maps those keywords to new spellings —
    otherwise canonical tests fail (expected_output.txt would say
    `aye` but toy_str would still emit `true`).

    We try BOTH `null` and `nil` so this helper works against either
    the toylang or forthlang runtime shapes; the override key in the
    spec determines what the new value is."""
    out = runtime_src
    # `true` / `false` are universal across families.
    for canon in ("true", "false"):
        new = overrides.get(canon, canon)
        if new == canon:
            continue
        out = re.sub(
            rf'return\s+"{re.escape(canon)}"',
            f'return "{new}"',
            out,
        )
    # Null literal: spec might use `null` (c_like) or `nil` (stack_based).
    # Prefer the new value from whichever role the spec actually carries.
    null_new = overrides.get("null") or overrides.get("nil")
    if null_new and null_new not in ("null", "nil"):
        # Substitute both possible canonical spellings so the helper
        # works across reference compilers.
        for canon in ("null", "nil"):
            out = re.sub(
                rf'return\s+"{re.escape(canon)}"',
                f'return "{null_new}"',
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
    family = _syntax_family(spec)

    if file_role == "parser":
        # Forthlang's parser is hand-rolled with a `_KEYWORDS` dict
        # literal; toylang and lisplang have a Lark `GRAMMAR = r"""...
        # """` string. Dispatch by family. Phase 1.5 scope expansion.
        if family == "stack_based":
            return substitute_handrolled_parser_keywords(source, overrides)
        m = re.search(r'(GRAMMAR\s*=\s*r?""")(.*?)(""")', source, re.DOTALL)
        if not m:
            return source
        head, body, tail = m.group(1), m.group(2), m.group(3)
        body = substitute_grammar_keywords(body, overrides)
        body = substitute_grammar_comments(body, new_comment)
        return source[:m.start()] + head + body + tail + source[m.end():]

    if file_role == "codegen":
        # Phase 1.5 scope expansion: forthlang's codegen has a
        # `_PY_NAME_MAP` dict that maps Forth names (`true`, `false`,
        # `nil`, `dup`, `+`, ...) to the Python identifiers/functions
        # they should compile into. After source substitution, the
        # parser emits NAME tokens with the new spellings — but if
        # codegen still maps `"true"` → `"true"`, then a substituted
        # source containing `aye` looks up `_PY_NAME_MAP["aye"]`,
        # falls through, and emits `aye()` — which the runtime
        # doesn't define. The fix is to rewrite the dict KEYS too,
        # so `_PY_NAME_MAP["aye"] = "true"` and codegen emits the
        # correct runtime call.
        #
        # Only stack_based has this shape today. c_like / s_expression
        # codegen don't have a name-map dict in the same way.
        if family != "stack_based":
            return source  # module_swap_only equivalent for other families
        out = source
        # Only substitute the boolean / null literal entries — these
        # are the canonical-Forth-names whose Python equivalent is a
        # runtime function. Stack-manipulation entries (`dup`, `drop`,
        # etc.) are out of scope for Phase 1.5 substitution.
        for canon in ("true", "false", "nil"):
            new = overrides.get(canon, canon)
            if new == canon:
                continue
            # Match `"<canon>":` (dict key) — same shape as the
            # hand-rolled parser substitution.
            out = re.sub(
                rf'"{re.escape(canon)}"\s*:',
                f'"{new}":',
                out,
            )
        return out

    if file_role == "runtime":
        return substitute_runtime_str_literals(source, overrides)

    if file_role == "test_source":
        out = substitute_source_keywords(source, overrides)
        # Use the family's canonical comment markers as the "old" markers
        # so kata source for stack_based has its `\` line-comments
        # rewritten to whatever the spec defines, not c_like's `//`.
        family_default = _default_comment_for_spec(spec)
        out = substitute_source_comments(out, family_default, new_comment)
        return out

    if file_role == "expected_output":
        # Boolean / null literals in expected stdout. Match against
        # both `null` and `nil` since the canonical word depends on
        # the family of the original kata source. The override value
        # is taken from whichever role the spec carries.
        out = source
        for canon in ("true", "false"):
            new = overrides.get(canon, canon)
            if new != canon:
                out = re.sub(rf'\b{re.escape(canon)}\b', new, out)
        null_new = overrides.get("null") or overrides.get("nil")
        if null_new and null_new not in ("null", "nil"):
            for canon in ("null", "nil"):
                out = re.sub(rf'\b{re.escape(canon)}\b', null_new, out)
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
_substitute_handrolled_parser_keywords = substitute_handrolled_parser_keywords


def _apply_template_substitutions(spec: dict, source: str, *,
                                  file_role: str = "test_source") -> str:
    """Legacy alias preserving the (spec, source, file_role) parameter
    order used by `generator.py` and existing tests. The new public API
    `apply_spec_keyword_substitutions` flips to (source, spec) which
    reads more naturally for new callers in the kata system."""
    return apply_spec_keyword_substitutions(source, spec, file_role=file_role)
