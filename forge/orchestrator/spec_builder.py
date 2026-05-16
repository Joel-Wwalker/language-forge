"""Stage 1: deterministic spec builder.

Pure function: build_spec(options, lang_name) -> dict.

Given the user's three option choices (syntax / typing / memory) plus a name,
assemble a base spec from per-option defaults. The resolver fills in any
remaining gaps and validates structural coherence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypedDict

from jsonschema import Draft7Validator


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "schemas" / "language_spec.schema.json"


class Options(TypedDict, total=False):
    # MVP: required
    syntax: Literal["c_like", "python_like", "s_expression", "stack_based", "ml_like", "logic_like"]
    typing: Literal["static", "dynamic"]
    memory: Literal["host_gc", "refcount"]
    # Tier 1: optional, default to current MVP behavior
    comment_style: Literal["line", "block", "both", "nestable_block"]
    string_literals: Literal["single", "double", "both", "triple_quoted", "raw_and_normal"]
    numeric_literals: Literal["decimal_only", "c_style", "extended"]
    default_mutability: Literal["mutable", "immutable"]
    error_handling: Literal["panic_only", "exceptions", "result_type"]
    loop_forms: list  # subset of {while, c_for, foreach, repeat_until, loop_break}
    multiple_returns: Literal["none", "tuple", "named"]
    boolean_evaluation: Literal["short_circuit", "eager"]


# ---------------------------------------------------------------------------
# Defaults for the new axes: chosen so existing 8 MVP combos keep passing.
# ---------------------------------------------------------------------------

_DEFAULT_EXTENDED = {
    "comment_style": None,           # filled per-syntax below
    "string_literals": "double",
    "numeric_literals": "decimal_only",
    "default_mutability": "mutable",
    "error_handling": "panic_only",
    "loop_forms": ["while"],
    "multiple_returns": "none",
    "boolean_evaluation": "short_circuit",
    "naming_convention": None,       # filled per-syntax below
    "null_model": "nullable",
}

# Per-syntax defaults that fill in `None` slots above.
_SYNTAX_EXTENDED_DEFAULTS = {
    "c_like": {"comment_style": "both", "naming_convention": "snake_case"},
    "python_like": {"comment_style": "line", "naming_convention": "snake_case"},
    # Lisps idiomatically use `;` line comments and `kebab-case`. naming_convention
    # is constrained to snake/camel/Pascal in the schema today, so we map kebab to
    # snake (closest equivalent) at the spec level. Codegen keeps the kebab form.
    "s_expression": {"comment_style": "line", "naming_convention": "snake_case"},
    # Forth-likes use `\ line` and `( paren )` comments. Identifiers are
    # space-separated tokens (kebab-case is idiomatic but most printable
    # ASCII works); we map to snake_case for the schema.
    "stack_based": {"comment_style": "both", "naming_convention": "snake_case"},
    # OCaml-flavored ML: only block comments `(* ... *)`. snake_case for
    # identifiers (lowercase-leading by grammar; uppercase-leading is
    # reserved for ADT constructors). NO while/for loops - mllang
    # iteration is recursion + pattern matching on list cons; the
    # _DEFAULT_EXTENDED['while'] would corrupt ml_like specs if it
    # weren't overridden here.
    "ml_like": {"comment_style": "block", "naming_convention": "snake_case",
                "loop_forms": []},
    # logic_like (pragmatic Prolog) uses `%` line comments + `/* */`
    # block comments. NO loops - iteration is recursion or backtracking.
    # Identifiers are atoms (lowercase-leading); variables are uppercase-
    # leading. We map to snake_case as the closest schema-supported
    # naming convention. The _DEFAULT_EXTENDED['loop_forms']=['while']
    # would corrupt logic_like the same way it corrupted ml_like before
    # the Seam 8 fix - the explicit `[]` here prevents that.
    "logic_like": {"comment_style": "both", "naming_convention": "snake_case",
                   "loop_forms": []},
}


# Minimal-but-applied stdlib. Every generated language ships these so a user
# can write a real script: read a file, split, count, write a file. Functions
# pair off: lists/dicts/strings/io/math/convert. Roughly 22 functions.
_DEFAULT_STDLIB_FUNCTIONS = [
    # Output / display
    {"name": "print", "description": "Print to stdout with newline.", "signature": "print(value, ...) -> void"},
    {"name": "input", "description": "Read one line from stdin (no trailing newline).", "signature": "input(prompt) -> string"},

    # Collections (functional shape; no literal syntax required)
    {"name": "list", "description": "Build a list from arguments. `list(1, 2, 3)`.", "signature": "list(...) -> list"},
    {"name": "len",  "description": "Length of a string, list, or dict.", "signature": "len(coll) -> int"},
    {"name": "get",  "description": "Read element by index (list) or key (dict). Returns null if absent.", "signature": "get(coll, k) -> any"},
    {"name": "set",  "description": "Mutate element by index or key. Returns the collection.", "signature": "set(coll, k, v) -> coll"},
    {"name": "push", "description": "Append to the end of a list. Returns the list.", "signature": "push(lst, x) -> list"},
    {"name": "pop",  "description": "Remove and return the last element of a list.", "signature": "pop(lst) -> any"},
    {"name": "dict", "description": "Build a dict from alternating key, value arguments.", "signature": "dict(k1, v1, k2, v2, ...) -> dict"},
    {"name": "has",  "description": "True if a dict has the key, or list has the index.", "signature": "has(coll, k) -> bool"},
    {"name": "keys", "description": "List of keys in a dict (insertion order).", "signature": "keys(d) -> list"},
    {"name": "range","description": "List of integers. `range(n)` is 0..n-1; `range(a, b)` is a..b-1.", "signature": "range(stop) | range(start, stop) -> list"},

    # Strings
    {"name": "str",     "description": "Convert any value to its printable string.", "signature": "str(v) -> string"},
    {"name": "split",   "description": "Split a string on a separator, return list of pieces.", "signature": "split(s, sep) -> list"},
    {"name": "join",    "description": "Join a list of strings with a separator.", "signature": "join(sep, lst) -> string"},
    {"name": "upper",   "description": "Uppercase a string.", "signature": "upper(s) -> string"},
    {"name": "lower",   "description": "Lowercase a string.", "signature": "lower(s) -> string"},
    {"name": "replace", "description": "Replace every occurrence of `old` with `new` in `s`.", "signature": "replace(s, old, new) -> string"},

    # Numbers
    {"name": "int",   "description": "Convert string or float to int.", "signature": "int(v) -> int"},
    {"name": "float", "description": "Convert string or int to float.", "signature": "float(v) -> float"},

    # Files and processes
    {"name": "read_file",  "description": "Read a UTF-8 text file as a string.", "signature": "read_file(path) -> string"},
    {"name": "write_file", "description": "Write a string to a file (overwrites). Returns null.", "signature": "write_file(path, s) -> null"},
    {"name": "argv",       "description": "List of command-line arguments after the program name.", "signature": "argv() -> list"},
    {"name": "exit",       "description": "Exit the program with an integer status code.", "signature": "exit(code) -> never"},
]


# ---------------------------------------------------------------------------
# Per-axis defaults
# ---------------------------------------------------------------------------

_C_LIKE_BASE = {
    "comment_syntax": {"line": "//", "block_open": "/*", "block_close": "*/"},
    "statement_terminator": ";",
    "block_style": "braces",
    "function_definition": {
        "keyword": "func",
        "syntax_example": "func name(a, b) { return a + b; }",
        "type_annotations": None,
    },
    "variable_declaration": {
        "keyword": "var",
        "syntax_example": "var x = 10;",
        "type_annotations": None,
    },
    "print_form": "print(<args>);",
    "boolean_keywords": {"true": "true", "false": "false"},
    "null_keyword": "null",
    "operators": {
        "arithmetic": ["+", "-", "*", "/", "%"],
        "comparison": ["==", "!=", "<", ">", "<=", ">="],
        "logical": ["&&", "||", "!"],
        "assignment": ["="],
    },
    "literals": {
        "integer": "decimal digits",
        "float": "decimal digits with '.'",
        "string": "double-quoted with backslash escapes",
        "boolean": "true / false",
    },
    "keywords": ["var", "func", "return", "if", "else", "while", "true", "false", "null", "print"],
}

_PYTHON_LIKE_BASE = {
    "comment_syntax": {"line": "#", "block_open": None, "block_close": None},
    "statement_terminator": "newline",
    "block_style": "indent",
    "function_definition": {
        "keyword": "def",
        "syntax_example": "def name(a, b):\n    return a + b",
        "type_annotations": None,
    },
    "variable_declaration": {
        "keyword": "let",
        "syntax_example": "let x = 10",
        "type_annotations": None,
    },
    "print_form": "print(<args>)",
    "boolean_keywords": {"true": "True", "false": "False"},
    "null_keyword": "None",
    "operators": {
        "arithmetic": ["+", "-", "*", "/", "%"],
        "comparison": ["==", "!=", "<", ">", "<=", ">="],
        "logical": ["and", "or", "not"],
        "assignment": ["="],
    },
    "literals": {
        "integer": "decimal digits",
        "float": "decimal digits with '.'",
        "string": "double-quoted with backslash escapes",
        "boolean": "True / False",
    },
    "keywords": ["let", "def", "return", "if", "elif", "else", "while", "True", "False", "None", "print"],
}

# ---------------------------------------------------------------------------
# Roadmap §families.md Tier 1: S-expression / Lisp family.
#
# Code is data: every form is `(operator operand operand ...)`. Function
# calls, control flow, definitions, and arithmetic all use the same shape.
# The parser is famously trivial; what makes a Lisp a Lisp is layer 3
# (uniform call notation, expressions everywhere) and layer 4 (lists as
# the primary data structure).
#
# We model this dialect as Clojure-flavored: `nil` for null, `true`/`false`
# unquoted, `defn` for function definition, `def` for global binding, and
# kebab-case identifiers. The reference family ships:
#   - `(def x 10)` for variable declaration
#   - `(defn name (a b) body...)` for function definition
#   - `(if cond then else)` for conditional
#   - `(while cond body...)` for loops
#   - `(+ a b)`, `(* a b)`, ... arithmetic as prefix calls
#   - `(= a b)`, `(< a b)`, ... comparison as prefix calls
#   - `(and a b)`, `(or a b)`, `(not a)` for logicals
#
# `block_style: parens` is a new value; the schema enum was widened.
# `statement_terminator: ")"` because that's literally what closes a form.
# ---------------------------------------------------------------------------
_S_EXPRESSION_BASE = {
    "comment_syntax": {"line": ";", "block_open": None, "block_close": None},
    "statement_terminator": ")",
    "block_style": "parens",
    "function_definition": {
        "keyword": "defn",
        "syntax_example": "(defn add (a b) (+ a b))",
        "type_annotations": None,
    },
    "variable_declaration": {
        "keyword": "def",
        "syntax_example": "(def x 10)",
        "type_annotations": None,
    },
    "print_form": "(print <args>)",
    "boolean_keywords": {"true": "true", "false": "false"},
    "null_keyword": "nil",
    "operators": {
        # In an s-expression language, operators ARE function names. We list
        # them so codegen + theme/keyword-overrides can still parameterize
        # them, but they always appear in prefix position: `(+ a b)`.
        "arithmetic": ["+", "-", "*", "/", "mod"],
        "comparison": ["=", "!=", "<", ">", "<=", ">="],
        "logical": ["and", "or", "not"],
        # No assignment operator at the syntax level; `def` and `set!` are
        # special forms (and `set!` only exists if the language is mutable).
        "assignment": [],
    },
    "literals": {
        "integer": "decimal digits",
        "float": "decimal digits with '.'",
        "string": "double-quoted with backslash escapes",
        "boolean": "true / false (unquoted symbols)",
    },
    "keywords": [
        "def", "defn", "if", "else", "when", "while", "true", "false", "nil",
        "let", "fn", "do", "print",
    ],
}

# ---------------------------------------------------------------------------
# Roadmap families.md Tier 1 (item 2.2): Stack-based / concatenative family.
#
# Programs are sequences of operations on an implicit data stack.
# `2 3 + 4 *` instead of `(2 + 3) * 4`. Function definitions consume and
# produce stack values. Examples: Forth, Factor, PostScript, Joy, Cat.
#
# We model this dialect after Forth (the most familiar stack language)
# with a Factor-influenced print form. Forms supported in the reference:
#   `: name body ;`            colon definition
#   `( ... )` / `\ comment`    paren / line comments
#   `if ... else ... then`     conditional (compiler words)
#   `begin ... until`          loop (until top of stack is true)
#   `do ... loop`              counted loop (over the dual loop stack)
#   `variable name`            variable declaration
#   `value name !`             store
#   `name @`                   fetch
#   `dup drop swap over rot`   stack manipulation
#   `+ - * / mod`              arithmetic (postfix)
#   `= <> < > <= >=`           comparison
#   `and or not`               logical
#   `." text"` / `s" text"`    print / push string literal
#   `.`                        print top of stack
#   `cr`                       newline
#
# `block_style: concatenative` and `statement_terminator: " "` (whitespace).
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ml_like family — dynamic OCaml-flavored ML (added by ml-family experiment).
#
# Strict eval, expression-oriented, `let`/`let rec` bindings, pattern
# matching with ADTs, `match ... with | pat -> body`, list cons via
# `::`, double-semicolon `;;` to terminate top-level items, block
# comments `(* ... *)`. See generated/mllang/ for the reference
# compiler + MLLANG_DESIGN.md for the full design.
# ---------------------------------------------------------------------------
_ML_LIKE_BASE = {
    "comment_syntax": {"line": None, "block_open": "(*", "block_close": "*)"},
    "statement_terminator": ";;",
    "block_style": "expression-oriented",
    "function_definition": {
        "keyword": "let",
        "syntax_example": "let add a b = a + b ;;",
        "type_annotations": None,
    },
    "variable_declaration": {
        "keyword": "let",
        "syntax_example": "let x = 10 ;;",
        "type_annotations": None,
    },
    "print_form": "print_any (<args>) ;;",
    "boolean_keywords": {"true": "true", "false": "false"},
    "null_keyword": "()",
    "operators": {
        # mllang has int + float operator pairs (`+` vs `+.`). The float
        # forms are listed alongside int because theme/keyword themes
        # may want to rename them in parallel.
        "arithmetic": ["+", "-", "*", "/", "mod", "+.", "-.", "*.", "/."],
        "comparison": ["=", "<>", "<", ">", "<=", ">="],
        "logical": ["&&", "||", "not"],
        # No assignment operator at the source level. `let` is the
        # binding form; bindings are immutable in v1.
        "assignment": [],
    },
    "literals": {
        "integer": "decimal digits",
        "float": "decimal digits with '.'",
        "string": "double-quoted with backslash escapes",
        "boolean": "true / false",
        "unit": "()",
    },
    "keywords": [
        "let", "rec", "in", "if", "then", "else",
        "match", "with", "type", "of", "fun", "mod", "not",
        "true", "false",
    ],
}


# ---------------------------------------------------------------------------
# logic_like family — pragmatic Prolog (added by logic-family experiment).
#
# Facts, rules, queries. Clauses end in `.`. Variables are uppercase-
# leading; atoms are lowercase-leading. `:-` separates rule head from
# body; `,` is conjunction; `;` is disjunction; `\+` is negation as
# failure. Lists are `[1, 2, 3]` with head/tail patterns `[H | T]`.
# Built-in predicates include `is/2` (arithmetic), `write/1`, `nl/0`,
# `length/2`, `append/3`, `member/2`, `reverse/2`, `call/N` for
# N in {1,2,3}, `findall/3`, `\+/1`, `once/1`.
#
# v1 subset edges: no cut, no assert/retract during queries, no DCGs,
# no constraint logic, no tabling, no operator declarations, no
# read predicates, no exception machinery. See generated/prologlang/
# for the reference compiler + LOGICLANG_DESIGN.md for the full design.
# ---------------------------------------------------------------------------
_LOGIC_LIKE_BASE = {
    "comment_syntax": {"line": "%", "block_open": "/*", "block_close": "*/"},
    "statement_terminator": ".",
    "block_style": "clause-based",
    "function_definition": {
        # Predicates use `:-` to separate head from body. "function
        # definition" is a slight semantic stretch (Prolog has predicates,
        # not functions) but the syntax_example shows the family's
        # function-equivalent pattern: a predicate with last-arg-is-output.
        "keyword": ":-",
        "syntax_example": "double(X, Y) :- Y is X * 2.",
        "type_annotations": None,
    },
    "variable_declaration": {
        # Variables in Prolog don't have explicit "declarations" in the
        # imperative sense - they're introduced by unification (`X = 10`).
        # The syntax_example shows the unification idiom.
        "keyword": "=",
        "syntax_example": "X = 10",
        "type_annotations": None,
    },
    # Default print form: `write(<args>), nl.` matches the kata-harness
    # wrap shape used by katas._wrap_with_test_prints for logic_like.
    "print_form": "write(<args>), nl.",
    "boolean_keywords": {"true": "true", "false": "false"},
    "null_keyword": "[]",
    "operators": {
        # Arithmetic operators are usable INSIDE `is/2` evaluation
        # (`X is 2 + 3`). Outside `is`, `2 + 3` is just the compound
        # term `+(2, 3)` - it doesn't compute.
        "arithmetic": ["+", "-", "*", "/", "//", "mod", "**"],
        # Comparison: `=:=` and `=\\=` evaluate both sides; `<`/`>`/`=<`/`>=`
        # do too. `=` is unification (NOT comparison) - included separately
        # in `logical` because it's structurally different from numeric
        # comparison.
        "comparison": ["=:=", "=\\=", "<", ">", "=<", ">="],
        "logical": [",", ";", "\\+"],
        # No assignment operator. `is/2` evaluates; `=/2` unifies; neither
        # is "assignment" in the c_like sense.
        "assignment": [],
    },
    "literals": {
        "integer": "decimal digits",
        "float": "decimal digits with '.'",
        "string": "single-quoted atom 'like this'",
        "boolean": "true / false (atoms)",
        "list": "[1, 2, 3] or [H | T]",
    },
    "keywords": [
        # Reserved words. Note: very few keywords compared to other
        # families - Prolog is mostly operator-driven. Most "control flow"
        # is done via predicates (call, once, findall) rather than
        # keywords. `is`, `mod`, `not`, `true`, `false`, `fail` are the
        # actual reserved words.
        "is", "mod", "not", "true", "false", "fail",
    ],
}


_STACK_BASED_BASE = {
    "comment_syntax": {"line": "\\", "block_open": "(", "block_close": ")"},
    "statement_terminator": " ",
    "block_style": "concatenative",
    "function_definition": {
        "keyword": ":",
        "syntax_example": ": square ( n -- n*n ) dup * ;",
        "type_annotations": None,
    },
    "variable_declaration": {
        "keyword": "variable",
        "syntax_example": "variable counter  0 counter !",
        "type_annotations": None,
    },
    "print_form": "<args> .",
    "boolean_keywords": {"true": "true", "false": "false"},
    "null_keyword": "nil",
    "operators": {
        # Postfix - operators are just words pulled from the dictionary.
        # Listing them here lets keyword themes / overrides parameterize
        # them, but at runtime they're function calls, not infix tokens.
        "arithmetic": ["+", "-", "*", "/", "mod"],
        "comparison": ["=", "<>", "<", ">", "<=", ">="],
        "logical": ["and", "or", "not"],
        # No assignment operator at the syntax level. `!` (store) and
        # `@` (fetch) are word-form operators on declared variables.
        "assignment": [],
    },
    "literals": {
        "integer": "decimal digits (negative literals via leading `-`)",
        "float": "decimal digits with '.'",
        "string": "Forth idiom: `s\" hello\"` to push, `.\" hello\"` to print inline",
        "boolean": "true / false (unquoted symbols; some dialects use 0 / -1)",
    },
    "keywords": [
        ":", ";", "if", "else", "then", "begin", "until", "again",
        "while", "repeat", "do", "loop", "variable", "constant",
        "true", "false", "and", "or", "not",
        "dup", "drop", "swap", "over", "rot", "nip", "tuck",
        "@", "!", ".", "cr",
    ],
}


def _typing_overlay(typing: str, syntax: str) -> dict:
    if typing == "static":
        if syntax == "c_like":
            return {
                "function_definition": {"type_annotations": "func add(a: int, b: int) -> int { return a + b; }"},
                "variable_declaration": {"type_annotations": "var x: int = 10;"},
                "type_system": {
                    "primitive_types": ["int", "float", "string", "bool"],
                    "annotation_form": "name: type",
                    "inference": False,
                },
            }
        if syntax == "s_expression":
            # Typed Racket / Hy-style annotations: a separate `(: name type)`
            # form that precedes the binding. Inference is the norm in typed
            # Lisps because it matches the homoiconic philosophy.
            return {
                "function_definition": {"type_annotations": "(: add (-> Int Int Int))\n(defn add (a b) (+ a b))"},
                "variable_declaration": {"type_annotations": "(: x Int)\n(def x 10)"},
                "type_system": {
                    "primitive_types": ["Int", "Float", "String", "Bool"],
                    "annotation_form": "(: name type)",
                    "inference": True,
                },
            }
        if syntax == "stack_based":
            # Forth tradition: stack-effect comments `( a b -- c )`.
            # Static-typed Forth (rare; Joy / Cat) would attach types to
            # word definitions in the stack-effect notation: `: add ( Int Int -- Int ) + ;`.
            return {
                "function_definition": {"type_annotations": ": add ( Int Int -- Int ) + ;"},
                "variable_declaration": {"type_annotations": "variable counter ( Int )"},
                "type_system": {
                    "primitive_types": ["Int", "Float", "String", "Bool"],
                    "annotation_form": "stack-effect comment ( inputs -- outputs )",
                    "inference": True,
                },
            }
        # python_like + static → gradual typing
        return {
            "function_definition": {"type_annotations": "def add(a: int, b: int) -> int:\n    return a + b"},
            "variable_declaration": {"type_annotations": "let x: int = 10"},
            "type_system": {
                "primitive_types": ["int", "float", "string", "bool"],
                "annotation_form": "name: type",
                "inference": True,
            },
        }
    return {}


def _memory_overlay(memory: str) -> dict:
    if memory == "host_gc":
        return {"memory_model": {
            "kind": "host_gc",
            "notes": (
                "Transpiles to Python; relies on Python's reference-counting + "
                "cycle GC. Documented as host_gc since the user program cannot "
                "observe GC behavior directly."
            ),
        }}
    return {"memory_model": {
        "kind": "refcount",
        "notes": (
            "Transpiles to Python in MVP, so true refcount semantics are not "
            "exposed to user programs. The stdlib documents that resources held "
            "by values are released deterministically when the last reference "
            "is dropped."
        ),
    }}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, overlay: dict) -> dict:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _file_extension(lang_name: str, syntax: str) -> str:
    # Default: first 3 letters of lang_name; special-cased for the
    # hand-written references so their on-disk test files match their
    # canonical idiomatic extensions.
    if lang_name == "toylang":
        return ".toy"
    if lang_name == "mllang":
        return ".ml"
    if lang_name == "prologlang":
        return ".lgc"
    base = "".join(c for c in lang_name.lower() if c.isalnum())[:3] or "lng"
    return "." + base


def build_spec(options: Options, lang_name: str, *,
               customization: dict | None = None,
               persona: str | None = None,
               era: str | None = None,
               keyword_theme: str | None = None,
               feature_bans: list[str] | None = None,
               hostile_constraints: str | None = None,
               phrasebook: str | None = None,
               natural_language: dict | None = None,
               lineage: dict | None = None) -> dict:
    """Build a base spec from options + optional customization, era, persona,
    theme, feature bans, and hostile constraints.

    Layering order (last-write-wins, but user always beats the system):
      1. era_preset defaults (if era set)
      2. user options (always win)
      3. feature_bans add option overrides (only if user hasn't set the axis)
      4. customization keyword/operator overrides
      5. keyword_theme folds into customization.keyword_overrides

    Persona, hostile_constraints, and feature_bans (prompt notes) survive on
    `spec.customization.*` so the resolver and per-component prompts pick them
    up downstream.
    """
    # 0) Layer era preset under user options.
    from .presets import apply_era
    from .bans import apply_bans, BAN_DEFS
    from .themes import get_theme
    from .personas import PERSONAS

    eff_opts = apply_era(era, dict(options))
    # 1) Apply ban-derived option overrides (only fills axes the user didn't set)
    eff_opts = apply_bans(feature_bans or [], eff_opts)

    syntax = eff_opts.get("syntax")
    # Deep-copy the family base. `dict(...)` is a SHALLOW copy: nested
    # dicts (operators, comment_syntax, keywords, ...) still point at
    # the module-level original. Subsequent `_deep_merge` calls and
    # keyword-theme overlays would then mutate the shared base, leaking
    # state across calls. The Phase 1.2 batch runner exposes this by
    # calling build_spec with themed customization repeatedly. Use
    # copy.deepcopy so each spec is fully independent.
    import copy as _copy
    if syntax == "c_like":
        spec = _copy.deepcopy(_C_LIKE_BASE)
    elif syntax == "s_expression":
        spec = _copy.deepcopy(_S_EXPRESSION_BASE)
    elif syntax == "stack_based":
        spec = _copy.deepcopy(_STACK_BASED_BASE)
    elif syntax == "ml_like":
        spec = _copy.deepcopy(_ML_LIKE_BASE)
    elif syntax == "logic_like":
        spec = _copy.deepcopy(_LOGIC_LIKE_BASE)
    else:
        spec = _copy.deepcopy(_PYTHON_LIKE_BASE)
    options = eff_opts  # subsequent code uses the merged effective options

    spec = _deep_merge(spec, _typing_overlay(options["typing"], options["syntax"]))
    spec = _deep_merge(spec, _memory_overlay(options["memory"]))

    # Fill in extended-axis defaults for any not provided by the user.
    # Family-specific defaults (_SYNTAX_EXTENDED_DEFAULTS) take priority
    # over the global default (_DEFAULT_EXTENDED). Otherwise a family
    # like ml_like would silently inherit `loop_forms=['while']` from
    # the c_like-default global, corrupting any spec where the user
    # didn't explicitly say `loop_forms=[]`.
    full_opts = dict(options)
    syntax_defaults = _SYNTAX_EXTENDED_DEFAULTS.get(options["syntax"], {})
    for k, default in _DEFAULT_EXTENDED.items():
        if k in full_opts:
            continue
        if k in syntax_defaults:
            full_opts[k] = syntax_defaults[k]
        elif default is not None:
            full_opts[k] = default

    spec["lang_name"] = lang_name
    spec["options"] = full_opts
    spec["file_extension"] = _file_extension(lang_name, options["syntax"])
    spec.setdefault("design_notes", [])

    # Default stdlib first; extended options may extend it (e.g. null_model=option
    # adds Some/unwrap helpers). User customization layers on top later.
    spec.setdefault("stdlib", {"functions": list(_DEFAULT_STDLIB_FUNCTIONS)})
    _apply_extended_options(spec, full_opts)

    # ---- Apply user customization ----
    customization = dict(customization or {})

    # Fold a chosen keyword_theme into customization.keyword_overrides.
    # User-supplied keyword_overrides always win over the theme.
    theme_map = get_theme(keyword_theme)
    if theme_map:
        existing_kw = customization.get("keyword_overrides") or {}
        merged_kw = dict(theme_map)
        merged_kw.update(existing_kw)
        customization["keyword_overrides"] = merged_kw

    # Fold ban prompt-notes into per-component extra_prompt_notes.
    if feature_bans:
        from .bans import bans_prompt_block
        ban_block = bans_prompt_block(feature_bans)
        notes = dict(customization.get("extra_prompt_notes") or {})
        for comp in ("parser", "codegen", "tests", "runtime", "lexer"):
            if comp in notes:
                notes[comp] = notes[comp] + "\n" + ban_block
            else:
                notes[comp] = ban_block
        customization["extra_prompt_notes"] = notes
        # Also surface in extra_design_notes so the resolver mentions them.
        existing_notes = list(customization.get("extra_design_notes") or [])
        for ban in feature_bans:
            blurb = BAN_DEFS.get(ban, {}).get("blurb", ban)
            existing_notes.append(f"User-banned: {ban}: {blurb}")
        customization["extra_design_notes"] = existing_notes

    # Hostile constraints become a top-level passthrough field for the resolver.
    if hostile_constraints:
        customization["hostile_constraints"] = hostile_constraints.strip()

    # Persona and era are stored verbatim for downstream prompts.
    if persona and persona in PERSONAS:
        customization["persona"] = persona
    if era:
        customization["era"] = era
    if keyword_theme:
        customization["keyword_theme"] = keyword_theme
    if feature_bans:
        customization["feature_bans"] = list(feature_bans)

    # Natural-language phrasebook. If user picked a preset, look it up; if
    # they supplied raw entries, those override the preset. Result lands on
    # `customization.natural_language` for the prompts to read.
    if phrasebook or natural_language:
        from .phrasebooks import get_phrasebook
        merged = get_phrasebook(phrasebook)
        if natural_language:
            for k, v in natural_language.items():
                if v:    # skip empty strings; falls back to default
                    merged[k] = v
        if merged:
            customization["natural_language"] = merged
            # Reflect word-level overrides into spec.boolean_keywords / null_keyword
            # so codegen and runtime stay consistent.
            if "true_word" in merged:
                spec.setdefault("boolean_keywords", {})["true"] = merged["true_word"]
            if "false_word" in merged:
                spec.setdefault("boolean_keywords", {})["false"] = merged["false_word"]
            if "null_word" in merged:
                spec["null_keyword"] = merged["null_word"]

    # Note: docs_persona is forwarded by callers via customization directly;
    # it doesn't have a top-level kwarg because it only affects one prompt.

    # File extension override
    custom_ext = customization.get("file_extension")
    if custom_ext:
        if not custom_ext.startswith("."):
            custom_ext = "." + custom_ext
        spec["file_extension"] = custom_ext

    # Keyword overrides: replace in keywords list + relevant fields
    kw_over = customization.get("keyword_overrides") or {}
    if kw_over:
        spec["keywords"] = sorted(set(
            kw_over.get(k, k) for k in spec["keywords"]
        ))
        # Also patch specific structured fields the spec exposes by keyword
        if "var" in kw_over:
            spec["variable_declaration"]["keyword"] = kw_over["var"]
            spec["variable_declaration"]["syntax_example"] = (
                spec["variable_declaration"]["syntax_example"].replace("var ", kw_over["var"] + " ", 1)
                .replace("let ", kw_over["var"] + " ", 1)
            )
        if "func" in kw_over or "def" in kw_over:
            new_kw = kw_over.get("func") or kw_over.get("def")
            spec["function_definition"]["keyword"] = new_kw
            ex = spec["function_definition"]["syntax_example"]
            ex = ex.replace("func ", new_kw + " ", 1).replace("def ", new_kw + " ", 1)
            spec["function_definition"]["syntax_example"] = ex
        if "true" in kw_over:
            spec["boolean_keywords"]["true"] = kw_over["true"]
        if "false" in kw_over:
            spec["boolean_keywords"]["false"] = kw_over["false"]
        if "null" in kw_over:
            spec["null_keyword"] = kw_over["null"]

    # Operator overrides: replace category lists wholesale
    op_over = customization.get("operator_overrides") or {}
    for category in ("arithmetic", "comparison", "logical", "assignment"):
        if category in op_over:
            spec["operators"][category] = list(op_over[category])

    # Extra design notes: appended to the existing list
    extras = customization.get("extra_design_notes") or []
    if extras:
        spec["design_notes"] = list(spec["design_notes"]) + [str(e) for e in extras]

    # Pass-through customization fields stored verbatim on the spec so the
    # generator/verifier/resolver can read them later.
    passthrough: dict = {}
    # Validate additional_tests structure once
    if customization.get("additional_tests"):
        for t in customization["additional_tests"]:
            if "name" not in t or "source" not in t or "expected" not in t:
                raise ValueError(f"additional_test missing required field: {t}")
    # Forward every recognized customization key that's truthy.
    for key in (
        "extra_prompt_notes",
        "additional_tests",
        "extra_design_notes",
        "keyword_overrides",
        "operator_overrides",
        "persona",
        "era",
        "keyword_theme",
        "feature_bans",
        "hostile_constraints",
        "docs_persona",
        "natural_language",
    ):
        v = customization.get(key)
        if v:
            # Make a shallow copy for mutables to avoid sharing references.
            if isinstance(v, dict):
                passthrough[key] = dict(v)
            elif isinstance(v, list):
                passthrough[key] = list(v)
            else:
                passthrough[key] = v
    if passthrough:
        spec["customization"] = passthrough

    # Run the coherence validator against the merged options. Errors raise
    # before we burn LLM tokens; warnings get appended to design_notes.
    from .coherence import check, errors, CoherenceError, warnings
    issues = check(full_opts | {"feature_bans": list(feature_bans or [])})
    if errors(issues):
        raise CoherenceError(errors(issues))
    for w in warnings(issues):
        spec["design_notes"].append(f"[coherence] {w.message}")

    # ---- Roadmap §3.3: crossbreeding lineage ----
    # Stored verbatim so the Library can draw the family tree and the resolver
    # / readme prompts can mention "this language was crossed from X and Y".
    if lineage:
        spec["lineage"] = {
            "parents": list(lineage.get("parents") or []),
            "strategy": lineage.get("strategy") or "random",
            "generation": int(lineage.get("generation") or 1),
        }
        if lineage.get("seed") is not None:
            spec["lineage"]["seed"] = int(lineage["seed"])
        # Surface lineage in design_notes so the resolver weaves it into the
        # origin_story it generates (children of named parents read better
        # when the LLM knows it's a crossbreed).
        parents_str = " × ".join(spec["lineage"]["parents"])
        if parents_str:
            spec["design_notes"].append(
                f"[lineage] crossbred from {parents_str} "
                f"(generation {spec['lineage']['generation']}, "
                f"strategy={spec['lineage']['strategy']})"
            )

    # ---- Roadmap §3.1: per-language visual theme ----
    # Merge style_tokens from chosen presets so the generator can emit
    # `<lang>/theme.css` and the GUI knows how to dress this language.
    # Stored on spec.theme so it ALSO reaches the resolver / readme prompts.
    from .style_tokens import style_tokens_for
    spec["theme"] = {
        "tokens": style_tokens_for(
            persona=persona,
            era=era,
            theme=keyword_theme,
            phrasebook=phrasebook,
        ),
        "sources": {
            "persona": persona,
            "era": era,
            "keyword_theme": keyword_theme,
            "phrasebook": phrasebook,
        },
    }

    validate_spec(spec)
    return spec


def _apply_extended_options(spec: dict, opts: dict) -> None:
    """Mutate `spec` in place to reflect each extended-axis choice.

    Each axis here is a Tier-1 (or low-risk Tier-2) option from the EaC catalog.
    The defaults match the current MVP, so existing 8-combo end-to-end tests
    continue to pass when callers don't supply extended options.
    """
    # ---- comment_style ----
    cs = opts.get("comment_style", "both")
    if opts["syntax"] == "c_like":
        if cs == "line":
            spec["comment_syntax"] = {"line": "//", "block_open": None, "block_close": None}
        elif cs == "block":
            spec["comment_syntax"] = {"line": None, "block_open": "/*", "block_close": "*/"}
        elif cs == "nestable_block":
            spec["comment_syntax"] = {"line": "//", "block_open": "/*", "block_close": "*/", "nestable": True}
        # else: "both": leave default
    elif opts["syntax"] == "s_expression":
        # Lisps use `;` line comments; `#| ... |#` is the conventional block
        # comment in Scheme/Racket. There's no widely-used "both" idiom that
        # differs, so block / nestable_block both pick `#| |#`.
        if cs == "block":
            spec["comment_syntax"] = {"line": None, "block_open": "#|", "block_close": "|#"}
        elif cs == "both" or cs == "nestable_block":
            spec["comment_syntax"] = {"line": ";", "block_open": "#|", "block_close": "|#",
                                      "nestable": cs == "nestable_block"}
        # else: "line": leave default (`;` only)
    elif opts["syntax"] == "stack_based":
        # Forth uses `\ line` and `( paren )`. Both are idiomatic; the
        # paren form doubles as stack-effect notation. Block comments
        # are NEVER nestable in Forth (would require a different
        # tokenizer entirely).
        if cs == "line":
            spec["comment_syntax"] = {"line": "\\", "block_open": None, "block_close": None}
        elif cs == "block":
            spec["comment_syntax"] = {"line": None, "block_open": "(", "block_close": ")"}
        # else "both" / "nestable_block": leave the default (`\` + `( )`)
    elif opts["syntax"] == "ml_like":
        # ml_like (OCaml-flavored) has NO line comments and `(* *)` block
        # comments that nest in real OCaml. mllang v1 grammar treats the
        # outermost pair only; the source-level convention says nestable.
        # The "block" / "both" / "nestable_block" cases all collapse to
        # `(* *)`. There's no "line" form (real OCaml doesn't have one
        # either; the comment_style enum's "line" value isn't applicable
        # to ml_like and the base dict already sets line=null).
        if cs == "nestable_block":
            spec["comment_syntax"] = {"line": None, "block_open": "(*",
                                      "block_close": "*)", "nestable": True}
        elif cs in ("block", "both"):
            spec["comment_syntax"] = {"line": None, "block_open": "(*",
                                      "block_close": "*)", "nestable": True}
        # else: leave default ((* *) from _ML_LIKE_BASE)
    elif opts["syntax"] == "logic_like":
        # logic_like (Prolog-flavored) uses `%` for line comments and
        # `/* */` for block comments. Block comments do NOT nest in
        # standard Prolog (and prologlang's BLOCK_COMMENT regex doesn't
        # support nesting). Mirrors the Seam 8 discipline: explicit
        # branch so logic_like doesn't fall into the `python_like` else
        # and get rewritten to triple-quote comments.
        if cs == "line":
            spec["comment_syntax"] = {"line": "%", "block_open": None, "block_close": None}
        elif cs == "block":
            spec["comment_syntax"] = {"line": None, "block_open": "/*", "block_close": "*/"}
        # else "both" / "nestable_block": leave default (% + /* */)
    else:  # python_like
        if cs == "block":
            spec["comment_syntax"] = {"line": None, "block_open": '"""', "block_close": '"""'}
        elif cs == "both":
            spec["comment_syntax"] = {"line": "#", "block_open": '"""', "block_close": '"""'}

    # ---- string_literals ----
    sl = opts.get("string_literals", "double")
    forms = {"double": ['"hello"'],
             "single": ["'hello'"],
             "both": ['"hello"', "'hello'"],
             "triple_quoted": ['"hello"', '"""multi\\nline"""'],
             "raw_and_normal": ['"hello"', 'r"raw\\nstring"']}
    spec["literals"]["string"] = ", ".join(forms.get(sl, ['"hello"']))
    spec["literals"]["string_form"] = sl

    # ---- numeric_literals ----
    nl = opts.get("numeric_literals", "decimal_only")
    if nl == "c_style":
        spec["literals"]["integer"] = "decimal, hex (0x), octal (0o), binary (0b)"
        spec["literals"]["integer_form"] = "c_style"
    elif nl == "extended":
        spec["literals"]["integer"] = "decimal with optional underscores; hex/oct/bin; suffix-typed"
        spec["literals"]["integer_form"] = "extended"
    else:
        spec["literals"]["integer_form"] = "decimal_only"

    # ---- default_mutability ----
    dm = opts.get("default_mutability", "mutable")
    if dm == "immutable":
        spec["variable_declaration"]["mutability"] = "immutable_by_default"
        if opts["syntax"] == "s_expression":
            # Lisp convention: `def` is immutable, `set!` is the explicit
            # mutation operator (Scheme tradition). Reserve `set!`.
            spec["keywords"] = sorted(set(spec["keywords"]) | {"set!"})
            spec["variable_declaration"]["syntax_example"] = (
                "(def x 10)  ; immutable; mutate via (set! x 11)"
            )
        elif opts["syntax"] == "stack_based":
            # Forth convention: `constant` is immutable, `variable` is
            # mutable (and you must explicitly fetch via `@` / store via `!`).
            # When immutable is the default, prefer `constant` for new
            # bindings; `variable` is then a less-common opt-in.
            spec["keywords"] = sorted(set(spec["keywords"]) | {"constant"})
            spec["variable_declaration"]["keyword"] = "constant"
            spec["variable_declaration"]["syntax_example"] = (
                "10 constant pi-tens  \\ immutable; reuse via name"
            )
        else:
            # c_like / python_like convention: `let x = ...` is immutable;
            # mutation requires `let mut x = ...`.
            if "mut" not in spec["keywords"]:
                spec["keywords"] = sorted(set(spec["keywords"]) | {"mut"})
            spec["variable_declaration"]["syntax_example"] = (
                spec["variable_declaration"]["keyword"] + " mut x = 10" +
                (";" if opts["syntax"] == "c_like" else "")
            )
    else:
        spec["variable_declaration"]["mutability"] = "mutable_by_default"

    # ---- error_handling ----
    eh = opts.get("error_handling", "panic_only")
    spec["error_handling"] = {"kind": eh}
    if eh == "exceptions":
        spec["error_handling"]["syntax"] = "try/catch with throw"
        new_kws = {"try", "catch", "throw"}
        spec["keywords"] = sorted(set(spec["keywords"]) | new_kws)
    elif eh == "result_type":
        spec["error_handling"]["syntax"] = "Result<T, E> with .ok / .err accessors"
        # NOTE: result_type pairs with sum_types + pattern_match. We document
        # the choice but the resolver will note this as a gap in design_notes.

    # ---- loop_forms ----
    lf = list(opts.get("loop_forms", ["while"]))
    spec["loop_forms"] = lf

    # ---- multiple_returns ----
    mr = opts.get("multiple_returns", "none")
    spec["multiple_returns"] = mr

    # ---- boolean_evaluation ----
    spec["boolean_evaluation"] = opts.get("boolean_evaluation", "short_circuit")

    # ---- naming_convention ----
    nc = opts.get("naming_convention", "snake_case")
    spec["naming_convention"] = nc

    # ---- null_model ----
    nm = opts.get("null_model", "nullable")
    spec["null_model"] = nm
    if nm == "none":
        # Banish null/None entirely. The keyword stays reserved for parser
        # rejection but no values are produced. Forces error_handling to
        # something failure-aware (caller should set Result; we don't override).
        spec["null_keyword_status"] = "reserved_but_unused"
    elif nm == "option":
        # Option/Some/None style. Add Option helpers to stdlib documentation.
        existing = list(spec["stdlib"]["functions"])
        for fn in (
            {"name": "Some", "description": "Wrap a value as Some(v) :: Option<T>.", "signature": "Some(v) -> Option"},
            {"name": "None", "description": "The empty Option.", "signature": "None -> Option"},
            {"name": "is_some", "description": "True if an Option holds a value.", "signature": "is_some(o) -> bool"},
            {"name": "unwrap", "description": "Get the inner value of an Option, or panic.", "signature": "unwrap(o) -> any"},
        ):
            if fn["name"] not in {f["name"] for f in existing}:
                existing.append(fn)
        spec["stdlib"]["functions"] = existing


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_spec(spec: dict) -> None:
    schema = load_schema()
    Draft7Validator(schema).validate(spec)
