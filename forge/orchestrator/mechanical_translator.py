"""Mechanical c_like -> target-language transpiler.

Pure code transformation, NO LLM call. Takes a c_like reference solution
(parses it via toylang's existing Lark grammar) and emits equivalent code
in the target language's syntax via a Backend pluggable per language type.

Why this exists: LLM-based translation is slow (~30-60s per pack) and
unreliable (some katas drop). The classics use a constrained subset of
c_like — declarations, assignments, if/while/return, function calls, basic
operators, list/dict literals. That subset is straightforward to transpile
mechanically. Mechanical = milliseconds = always works.

Backends supported now:
  - **PhrasebookBackend**: phrasebook languages (kidX-style "make x equal 0.")
  - **CLikeBackend**: vanilla c_like (toylang, democ, god, ...)

Each backend implements a small set of `emit_*` methods. The `transpile()`
entry point parses the source, walks the tree, and dispatches to the
backend.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# Use toylang's existing Lark grammar to parse c_like sources. Adding the
# generated/ root to sys.path is the same trick check_solution + the GUI
# already use to import lang modules.
_GEN_ROOT = Path(__file__).resolve().parents[2] / "generated"
if str(_GEN_ROOT) not in sys.path:
    sys.path.insert(0, str(_GEN_ROOT))


def _toylang_parse(src: str):
    """Parse a c_like source via toylang's parser. Lazy import so we don't
    hard-fail at module import time if toylang isn't available."""
    from toylang.parser import parse  # type: ignore
    return parse(src)


# ---------------------------------------------------------------------------
# Backend interface (one class per target language family)
# ---------------------------------------------------------------------------

class Backend:
    """Emits target-language code given AST-shaped input from the walker."""

    # ---- Statement emitters ----
    def emit_var_decl(self, name: str, value: str, *, indent: str) -> str:
        raise NotImplementedError
    def emit_assign(self, name: str, value: str, *, indent: str) -> str:
        raise NotImplementedError
    def emit_func_def(self, name: str, params: list[str], body: str, *, indent: str) -> str:
        raise NotImplementedError
    def emit_if(self, cond: str, then_body: str, else_body: Optional[str], *, indent: str) -> str:
        raise NotImplementedError
    def emit_while(self, cond: str, body: str, *, indent: str) -> str:
        raise NotImplementedError
    def emit_return(self, value: Optional[str], *, indent: str) -> str:
        raise NotImplementedError
    def emit_expr_stmt(self, expr: str, *, indent: str) -> str:
        raise NotImplementedError

    # ---- Expression emitters ----
    def emit_call(self, fn: str, args: list[str]) -> str:
        return f"{fn}({', '.join(args)})"
    def emit_binop(self, op: str, a: str, b: str) -> str:
        # Logical op words depend on the language; defaults are c_like.
        return f"{a} {op} {b}"
    def emit_unop(self, op: str, x: str) -> str:
        return f"{op}{x}"
    def emit_int(self, v: str) -> str: return v
    def emit_float(self, v: str) -> str: return v
    def emit_string(self, v: str) -> str: return v  # already includes quotes from lexer
    def emit_true(self) -> str: return "true"
    def emit_false(self) -> str: return "false"
    def emit_null(self) -> str: return "null"
    def emit_name(self, n: str) -> str: return n
    def emit_paren(self, inner: str) -> str: return f"({inner})"


class CLikeBackend(Backend):
    """Default c_like (toylang's exact dialect, with optional keyword
    overrides from spec.customization.keyword_overrides)."""

    def __init__(self, spec: dict):
        self.spec = spec
        kw = (spec.get("customization") or {}).get("keyword_overrides") or {}
        self.kw = {
            "var": kw.get("var", "var"),
            "func": kw.get("func", "func"),
            "return": kw.get("return", "return"),
            "if": kw.get("if", "if"),
            "else": kw.get("else", "else"),
            "while": kw.get("while", "while"),
            "true": kw.get("true", "true"),
            "false": kw.get("false", "false"),
            "null": kw.get("null", spec.get("null_keyword", "null")),
            "and": "&&", "or": "||", "not": "!",
        }
        self.term = ";"

    def emit_var_decl(self, name, value, *, indent):
        return f"{indent}{self.kw['var']} {name} = {value};"
    def emit_assign(self, name, value, *, indent):
        return f"{indent}{name} = {value};"
    def emit_func_def(self, name, params, body, *, indent):
        return f"{indent}{self.kw['func']} {name}({', '.join(params)}) {{\n{body}\n{indent}}}"
    def emit_if(self, cond, then_body, else_body, *, indent):
        out = f"{indent}{self.kw['if']} ({cond}) {{\n{then_body}\n{indent}}}"
        if else_body:
            out += f" {self.kw['else']} {{\n{else_body}\n{indent}}}"
        return out
    def emit_while(self, cond, body, *, indent):
        return f"{indent}{self.kw['while']} ({cond}) {{\n{body}\n{indent}}}"
    def emit_return(self, value, *, indent):
        return f"{indent}{self.kw['return']}{(' ' + value) if value else ''};"
    def emit_expr_stmt(self, expr, *, indent):
        return f"{indent}{expr};"
    def emit_true(self): return self.kw["true"]
    def emit_false(self): return self.kw["false"]
    def emit_null(self): return self.kw["null"]


class PythonLikeBackend(Backend):
    """Python-like languages: def + indent + colons, no semicolons, no braces.

    Syntax recipe (driven by spec fields):
      - var decl: `<var_kw> <name> = <value>` (e.g. `let x = 10`)
      - assignment: `<name> = <value>` (no keyword)
      - func def: `<func_kw> <name>(<params>):\\n<body>` (body indented)
      - if/while: `<kw> <cond>:\\n<body>` (body indented)
      - return: `<ret_kw> <value>` (no terminator)
      - bools/null: from `boolean_keywords` and `null_keyword` (e.g. True/None)
    """

    def __init__(self, spec: dict):
        self.spec = spec
        fd = spec.get("function_definition") or {}
        vd = spec.get("variable_declaration") or {}
        bk = spec.get("boolean_keywords") or {}
        kw = (spec.get("customization") or {}).get("keyword_overrides") or {}
        self.func_kw = kw.get("func", fd.get("keyword", "def"))
        self.var_kw = kw.get("var", vd.get("keyword", ""))
        self.return_kw = kw.get("return", "return")
        self.if_kw = kw.get("if", "if")
        self.else_kw = kw.get("else", "else")
        self.while_kw = kw.get("while", "while")
        self.true_kw = kw.get("true", bk.get("true", "True"))
        self.false_kw = kw.get("false", bk.get("false", "False"))
        self.null_kw = kw.get("null", spec.get("null_keyword", "None"))
        # Logical operator words for python_like — typically `and`, `or`, `not`.
        self.and_word = "and"
        self.or_word = "or"
        self.not_word = "not"

    def emit_var_decl(self, name, value, *, indent):
        if self.var_kw:
            return f"{indent}{self.var_kw} {name} = {value}"
        return f"{indent}{name} = {value}"

    def emit_assign(self, name, value, *, indent):
        return f"{indent}{name} = {value}"

    def emit_func_def(self, name, params, body, *, indent):
        return f"{indent}{self.func_kw} {name}({', '.join(params)}):\n{body}"

    def emit_if(self, cond, then_body, else_body, *, indent):
        out = f"{indent}{self.if_kw} {cond}:\n{then_body}"
        if else_body:
            out += f"\n{indent}{self.else_kw}:\n{else_body}"
        return out

    def emit_while(self, cond, body, *, indent):
        return f"{indent}{self.while_kw} {cond}:\n{body}"

    def emit_return(self, value, *, indent):
        if value is None:
            return f"{indent}{self.return_kw}"
        return f"{indent}{self.return_kw} {value}"

    def emit_expr_stmt(self, expr, *, indent):
        return f"{indent}{expr}"

    def emit_binop(self, op, a, b):
        # Map c_like logical ops to python-style words.
        word_map = {"&&": self.and_word, "||": self.or_word}
        return f"{a} {word_map.get(op, op)} {b}"

    def emit_unop(self, op, x):
        if op == "!":
            return f"{self.not_word} {x}"
        return f"{op}{x}"

    def emit_true(self): return self.true_kw
    def emit_false(self): return self.false_kw
    def emit_null(self): return self.null_kw


class PhrasebookBackend(Backend):
    """Phrasebook languages (kidX-style natural-language statement forms).

    Each construct uses the language's `customization.natural_language`
    template. Templates may have placeholders like <name>, <value>, <body>
    which we substitute. Examples (kidX):
      - var_decl: "make <name> equal <value>."
      - func_def: "the way to <name> with <params> is <body>."
      - if_stmt: "when <cond> do <body> else <else>."
      - while_stmt: "keep doing <body> while <cond>."
      - return_stmt: "the answer is <value>."
    """

    def __init__(self, spec: dict):
        self.spec = spec
        nl = (spec.get("customization") or {}).get("natural_language") or {}
        self.nl = nl
        # Statement-terminator inside natural-language templates is `.` (which
        # the templates themselves include). For non-template statements
        # (e.g. assignments), use the language's normal `;`.
        self.assign_term = spec.get("statement_terminator", ";")
        if self.assign_term == "newline":
            self.assign_term = ""
        self.true_word = nl.get("true_word", "true")
        self.false_word = nl.get("false_word", "false")
        self.null_word = nl.get("null_word", spec.get("null_keyword", "null"))
        self.and_word = nl.get("and_word", "&&")
        self.or_word = nl.get("or_word", "||")
        self.not_word = nl.get("not_word", "!")
        # Logical-op words may need spaces around them (kidX uses "and"/"or"
        # which need spaces) versus c_like operators (`&&`, `||`, no spaces
        # required but harmless).

    def _fill(self, template: str, **kw) -> str:
        out = template
        for k, v in kw.items():
            out = out.replace(f"<{k}>", v)
        return out

    def emit_var_decl(self, name, value, *, indent):
        t = self.nl.get("var_decl", "make <name> equal <value>.")
        return indent + self._fill(t, name=name, value=value)

    def emit_assign(self, name, value, *, indent):
        # No phrasebook template usually exists for plain assignments; use
        # the language's normal form. kidX accepts `count = count + 1;`.
        return f"{indent}{name} = {value}{self.assign_term}"

    def emit_func_def(self, name, params, body, *, indent):
        if params:
            params_str = " and ".join(params)  # kidX: "with a and b"
            t = self.nl.get("func_def", "the way to <name> with <params> is <body>.")
            return indent + self._fill(
                t, name=name, params=params_str,
                body=f"{{\n{body}\n{indent}}}",
            )
        # No params: kidX uses "the way to <name> is <body>." (no "with X")
        t_no_params = self.nl.get("func_def_no_params")
        if t_no_params:
            return indent + self._fill(
                t_no_params, name=name, body=f"{{\n{body}\n{indent}}}",
            )
        # Fallback: strip "with <params>" from the templated form.
        t = self.nl.get("func_def", "the way to <name> with <params> is <body>.")
        # Naive strip of "with <params>" placeholder section
        t = re.sub(r"with\s+<params>\s*", "", t)
        return indent + self._fill(t, name=name, body=f"{{\n{body}\n{indent}}}")

    def emit_if(self, cond, then_body, else_body, *, indent):
        if else_body is not None:
            t = self.nl.get("if_stmt",
                            "when <cond> do <body> else <else>.")
            return indent + self._fill(
                t, cond=cond,
                body=f"{{\n{then_body}\n{indent}}}",
                **{"else": f"{{\n{else_body}\n{indent}}}"},
            )
        # No else branch: try if_stmt_no_else, else strip the else section
        t_no_else = self.nl.get("if_stmt_no_else")
        if t_no_else:
            return indent + self._fill(
                t_no_else, cond=cond, body=f"{{\n{then_body}\n{indent}}}",
            )
        t = self.nl.get("if_stmt", "when <cond> do <body> else <else>.")
        t = re.sub(r"\s*else\s+<else>", "", t)
        return indent + self._fill(t, cond=cond, body=f"{{\n{then_body}\n{indent}}}")

    def emit_while(self, cond, body, *, indent):
        t = self.nl.get("while_stmt", "keep doing <body> while <cond>.")
        return indent + self._fill(t, cond=cond, body=f"{{\n{body}\n{indent}}}")

    def emit_return(self, value, *, indent):
        t = self.nl.get("return_stmt", "the answer is <value>.")
        return indent + self._fill(t, value=value if value else self.null_word)

    def emit_expr_stmt(self, expr, *, indent):
        return f"{indent}{expr}{self.assign_term}"

    def emit_binop(self, op, a, b):
        # Map c_like operators to phrasebook word-forms when the language
        # has them. Keep arithmetic/comparison operators as-is (they're not
        # usually word-substituted).
        word_map = {"&&": self.and_word, "||": self.or_word}
        return f"{a} {word_map.get(op, op)} {b}"

    def emit_unop(self, op, x):
        if op == "!":
            # Phrasebook languages parse `not <expr>` ambiguously when <expr>
            # is a function call — `not` lexes as NAME, then the call follows
            # adjacently. Wrap operand in parens unconditionally so it's
            # always a single primary.
            return f"{self.not_word} ({x})"
        return f"{op}{x}"

    def emit_true(self): return self.true_word
    def emit_false(self): return self.false_word
    def emit_null(self): return self.null_word


# ---------------------------------------------------------------------------
# Tree walker (toylang Lark Tree -> emitted code)
# ---------------------------------------------------------------------------

INDENT_STEP = "    "


def _walk_stmt(node, backend: Backend, indent: str) -> str:
    """Emit one statement (already prefixed with `indent`)."""
    name = getattr(node, "data", None)
    if name == "var_decl":
        var_name = str(node.children[0])
        value = _walk_expr(node.children[1], backend)
        return backend.emit_var_decl(var_name, value, indent=indent)
    if name == "func_def":
        fn_name = str(node.children[0])
        params: list[str] = []
        body_node = None
        for c in node.children[1:]:
            if getattr(c, "data", None) == "params":
                params = [str(p) for p in c.children]
            elif getattr(c, "data", None) == "block":
                body_node = c
        body_lines = _walk_block_body(body_node, backend, indent + INDENT_STEP)
        return backend.emit_func_def(fn_name, params, body_lines, indent=indent)
    if name == "if_stmt":
        cond = _walk_expr(node.children[0], backend)
        then_block = node.children[1]
        else_clause = node.children[2] if len(node.children) > 2 else None
        then_body = _walk_block_body(then_block, backend, indent + INDENT_STEP)
        else_body = None
        if else_clause is not None:
            ec = else_clause.children[0]
            if getattr(ec, "data", None) == "if_stmt":
                # else-if: emit nested if as the else body. We build the
                # nested if at the SAME indent level as the parent's children
                # would be (one step in from the else's brace).
                else_body = _walk_stmt(ec, backend, indent + INDENT_STEP)
            else:
                else_body = _walk_block_body(ec, backend, indent + INDENT_STEP)
        return backend.emit_if(cond, then_body, else_body, indent=indent)
    if name == "while_stmt":
        cond = _walk_expr(node.children[0], backend)
        body = _walk_block_body(node.children[1], backend, indent + INDENT_STEP)
        return backend.emit_while(cond, body, indent=indent)
    if name == "return_stmt":
        value = _walk_expr(node.children[0], backend) if node.children else None
        return backend.emit_return(value, indent=indent)
    if name == "expr_stmt":
        expr = _walk_expr(node.children[0], backend)
        return backend.emit_expr_stmt(expr, indent=indent)
    if name == "block":
        # Bare block (rare in classics). Just emit its body inline.
        return _walk_block_body(node, backend, indent)
    # Fallback: stringify
    return f"{indent}// unhandled stmt: {name}"


def _walk_block_body(block_node, backend: Backend, indent: str) -> str:
    """Emit statements inside a block, joined by newlines."""
    if block_node is None:
        return ""
    lines = []
    for child in block_node.children:
        if hasattr(child, "data"):
            lines.append(_walk_stmt(child, backend, indent))
    return "\n".join(lines)


def _walk_expr(node, backend: Backend) -> str:
    """Emit an expression as a single line."""
    name = getattr(node, "data", None)
    # Direct token
    if name is None:
        return str(node)
    # Pass-through wrappers
    if name in ("passthru",):
        return _walk_expr(node.children[0], backend)
    if name == "assign_op":
        var = str(node.children[0])
        val = _walk_expr(node.children[1], backend)
        return f"{var} = {val}"
    if name == "paren":
        return backend.emit_paren(_walk_expr(node.children[0], backend))
    if name in ("logical_or", "logical_and", "equality", "comparison", "term", "factor"):
        # Left-associative chain: a OP b OP c -> emit_binop(emit_binop(a,b), c)
        children = node.children
        if len(children) == 1:
            return _walk_expr(children[0], backend)
        result = _walk_expr(children[0], backend)
        i = 1
        while i < len(children):
            op = str(children[i])
            rhs = _walk_expr(children[i + 1], backend)
            result = backend.emit_binop(op, result, rhs)
            i += 2
        return result
    if name == "unary":
        # Either UNARY_OP unary, OR fallthrough to call
        if len(node.children) == 2:
            op = str(node.children[0])
            x = _walk_expr(node.children[1], backend)
            return backend.emit_unop(op, x)
        return _walk_expr(node.children[0], backend)
    if name == "call":
        # primary trailer*
        primary = _walk_expr(node.children[0], backend)
        result = primary
        for trailer in node.children[1:]:
            if getattr(trailer, "data", None) == "trailer":
                args = []
                if trailer.children:
                    args_node = trailer.children[0]
                    if getattr(args_node, "data", None) == "args":
                        args = [_walk_expr(a, backend) for a in args_node.children]
                result = backend.emit_call(result, args)
        return result
    if name == "int_lit":
        return backend.emit_int(str(node.children[0]))
    if name == "float_lit":
        return backend.emit_float(str(node.children[0]))
    if name == "string_lit":
        return backend.emit_string(str(node.children[0]))
    if name == "true_lit":
        return backend.emit_true()
    if name == "false_lit":
        return backend.emit_false()
    if name == "null_lit":
        return backend.emit_null()
    if name == "name_ref":
        return backend.emit_name(str(node.children[0]))
    # Default
    return str(node)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def ensure_runtime_string_support(lang_dir: Path) -> bool:
    """Patch the language's runtime.py so `get(string, int)` works (the way
    toylang's runtime does).

    Many generated languages have a `toy_get` that raises TypeError on
    strings, which makes string-iteration classics like valid_parens,
    anagram, and longest_unique_substring unusable. Toylang's runtime
    handles strings natively. Mirror that across other languages with a
    surgical patch so universal kata code works.

    Operates LINE-BY-LINE on the runtime source so we never get the
    indentation wrong. We find the `def toy_get(` block, walk to the line
    that raises, and insert string-handling at the function-body level
    (4-space indent) immediately before the raise.

    Returns True if the runtime was patched (or already supports strings),
    False if we couldn't find/edit it.
    """
    rt_path = lang_dir / "runtime.py"
    if not rt_path.exists():
        return False
    text = rt_path.read_text(encoding="utf-8")
    if "# string-indexing-support: forge-patch" in text:
        return True
    lines = text.splitlines(keepends=True)

    # Find `def toy_get(` line.
    fn_start = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("def toy_get("):
            fn_start = i
            break
    if fn_start is None:
        return False

    # Walk forward until we hit a line that begins at column 0 with `def `
    # or the file ends — that's the end of toy_get's body.
    fn_end = len(lines)
    for j in range(fn_start + 1, len(lines)):
        s = lines[j]
        stripped = s.lstrip()
        if s and not s[0].isspace() and not s.startswith("\n") and not s.startswith("#"):
            fn_end = j
            break
    body = lines[fn_start:fn_end]

    # If toy_get already handles strings, just add the marker and return.
    body_text = "".join(body)
    if "isinstance(coll, str)" in body_text:
        new_text = "# string-indexing-support: forge-patch (already supports str)\n" + text
        rt_path.write_text(new_text, encoding="utf-8")
        return True

    # Find the raise line WITHIN the body. Accept any TypeError raise — the
    # function name + structure is enough to identify intent.
    raise_idx_in_body = None
    for j, s in enumerate(body):
        if "raise TypeError" in s:
            raise_idx_in_body = j
            break
    if raise_idx_in_body is None:
        return False

    # Determine indent of the raise line (should be the function-body indent,
    # typically 4 spaces).
    raise_line = body[raise_idx_in_body]
    indent = raise_line[:len(raise_line) - len(raise_line.lstrip())]

    # Build the insertion using the SAME indent as the raise.
    insertion = (
        f"{indent}if isinstance(coll, str):\n"
        f"{indent}    if isinstance(k, int) and 0 <= k < len(coll):\n"
        f"{indent}        return coll[k]\n"
        f"{indent}    return default\n"
    )
    new_body = (
        body[:raise_idx_in_body]
        + [insertion]
        + body[raise_idx_in_body:]
    )
    new_lines = (
        ["# string-indexing-support: forge-patch\n"]
        + lines[:fn_start]
        + new_body
        + lines[fn_end:]
    )
    rt_path.write_text("".join(new_lines), encoding="utf-8")
    return True


def can_handle(spec: dict) -> Optional[Backend]:
    """Return a Backend instance if we can mechanically transpile c_like
    classics to this language's syntax, else None.

    We can handle:
      - vanilla c_like (CLikeBackend) — direct emit, near-identity for toylang
      - phrasebook c_like (PhrasebookBackend) — uses natural_language templates
      - vanilla python_like (PythonLikeBackend) — def + indent + colons

    We bail (return None) for:
      - statically-typed languages: would need type inference to emit
        annotations. Falls through to LLM, which can write annotations.
      - feature_bans with no_mutation / no_loops: requires algorithmic
        rewriting (loops -> recursion), too far for a syntactic transpiler.
    """
    options = spec.get("options") or {}
    syntax = options.get("syntax")
    typing = options.get("typing")
    cust = spec.get("customization") or {}
    nl = cust.get("natural_language")
    bans = cust.get("feature_bans") or []

    # Static typing requires type annotations on params/returns; we can't
    # infer those without semantic analysis. The LLM can.
    if typing == "static":
        return None

    # Mutation/loop bans require algorithmic rewriting beyond a syntactic
    # transpiler. Let the LLM handle these (with the recursion-only fix-up
    # strategy already built into translate_pack's escalation ladder).
    if "no_mutation" in bans or "no_loops" in bans:
        return None

    if syntax == "c_like":
        if nl and isinstance(nl, dict) and nl:
            return PhrasebookBackend(spec)
        return CLikeBackend(spec)

    if syntax == "python_like":
        if nl and isinstance(nl, dict) and nl:
            return None
        return PythonLikeBackend(spec)

    return None


def transpile(c_like_source: str, spec: dict) -> Optional[str]:
    """Transpile c_like source to the target language. Returns the emitted
    code, or None if we can't handle this language type."""
    backend = can_handle(spec)
    if backend is None:
        return None
    try:
        tree = _toylang_parse(c_like_source)
    except Exception:
        return None
    out_lines = []
    for stmt in tree.children:
        if hasattr(stmt, "data"):
            out_lines.append(_walk_stmt(stmt, backend, ""))
    return "\n".join(out_lines) + "\n"


def _rederive_expected(kata: dict, spec: dict, lang_dir: Path) -> Optional[dict]:
    """Run the (transpiled) reference + test calls through the language's
    actual compiler, capture stdout, and replace each test's `expected`
    with the actual output. This is safe ONLY if the reference is correct
    in spirit (same algorithm), since it makes the test agree with the
    reference by construction. Used after mechanical transpile to absorb
    print-formatter differences (e.g. kidX prints `[a]` as `['a']`).

    Returns a NEW kata dict with updated tests, or None if the run failed.
    """
    from .katas import _wrap_with_test_prints, _compile_and_run
    program = _wrap_with_test_prints(kata["reference_solution"], kata["tests"], spec)
    res = _compile_and_run(lang_dir, program, spec["file_extension"])
    if not res["ok"]:
        return None
    actual_lines = res["stdout"].splitlines()
    if len(actual_lines) != len(kata["tests"]):
        return None  # drift between number of prints and number of tests
    new_tests = []
    for actual, t in zip(actual_lines, kata["tests"]):
        new_tests.append({"call": t["call"], "expected": actual.rstrip()})
    out = dict(kata)
    out["tests"] = new_tests
    return out


def transpile_kata(kata: dict, spec: dict) -> Optional[dict]:
    """Mechanically translate a kata's reference + starter to the target
    language. Tests' calls are also transpiled (they're c_like expressions).
    Expected outputs are LEFT UNCHANGED — they should already match toylang's
    print formatter, which most c_like-derived languages share.

    Returns a new kata dict, or None if mechanical translation isn't
    possible for this language type."""
    backend = can_handle(spec)
    if backend is None:
        return None
    new_ref = transpile(kata["reference_solution"], spec)
    if new_ref is None:
        return None
    new_starter = transpile(kata.get("starter_code", ""), spec)
    new_tests = []
    for t in kata.get("tests", []):
        # The "call" is a single expression. Wrap it as `<expr>;` to feed
        # toylang's parser, then transpile, then strip the terminator.
        try:
            tree = _toylang_parse(t["call"].rstrip(";").rstrip() + ";")
            new_call = _walk_expr(tree.children[0].children[0], backend)
        except Exception:
            new_call = t["call"]  # last resort: leave it
        new_tests.append({"call": new_call, "expected": t["expected"]})
    # Helpers (LL/tree node constructors etc.) need transpiling too —
    # they're prepended to the user's solution at test time, so they must
    # be in the target language's syntax.
    new_helpers = None
    if kata.get("helpers"):
        new_helpers = transpile(kata["helpers"], spec)

    out = dict(kata)
    out["reference_solution"] = new_ref
    if new_starter:
        out["starter_code"] = new_starter
    if new_helpers is not None:
        out["helpers"] = new_helpers
    out["tests"] = new_tests
    return out


def transpile_and_validate(kata: dict, spec: dict, lang_dir: Path
                           ) -> tuple[Optional[dict], str]:
    """Full mechanical pipeline: transpile, re-derive expected outputs by
    running the reference, validate. Returns (kata or None, reason).

    A None return means mechanical translation can't handle this kata for
    this language — caller should fall back to LLM-based translation.
    """
    from .katas import _self_validate
    translated = transpile_kata(kata, spec)
    if translated is None:
        return None, "mechanical: backend doesn't support this language type"
    # Re-derive expected so formatter differences (kidX's quoted strings,
    # different list separators, etc.) absorb cleanly. The reference's
    # algorithm is the source of truth.
    rederived = _rederive_expected(translated, spec, lang_dir)
    if rederived is not None:
        translated = rederived
    ok, reason = _self_validate(translated, lang_dir, spec)
    if ok:
        return translated, "ok"
    return None, f"mechanical: {reason}"
