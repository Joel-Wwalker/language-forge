"""forthlang codegen. Walks the parser's AST and emits runnable Python.

Output strategy: every Forth word becomes a Python function that mutates
a global `_stack` list. Number/string literals push directly. Calls
look up the word in a runtime dictionary. Control structures get
translated to native Python constructs (if/else, while True/break, for).

Word names that aren't valid Python identifiers (e.g. `+`, `<=`, `?`)
get mangled via `_py_name()` so they can be used as Python `def` names.
The runtime maps the canonical Forth names back during dispatch.

This codegen is COMPLETE - no `...` stubs.
"""
from __future__ import annotations


PRELUDE = """\
from forthlang.runtime import (
    _stack, _vars, _consts,
    push, pop, top,
    dup, drop, swap, over, rot, nip, tuck,
    add as _op_add,
    sub as _op_sub,
    mul as _op_mul,
    div as _op_div,
    mod as _op_mod,
    eq as _op_eq, ne as _op_ne,
    lt as _op_lt, gt as _op_gt,
    le as _op_le, ge as _op_ge,
    log_and as _op_and, log_or as _op_or, log_not as _op_not,
    print_top as _print_top,
    print_str as _print_str,
    cr as _cr,
    fetch as _fetch,
    store as _store,
    declare_variable as _declare_variable,
    declare_constant as _declare_constant,
    pushv,
    truthy as _toy_truthy,
    # Boolean / null pushes
    true, false, nil,
    # Collection words (lists, dicts, strings)
    make_list as _make_list,
    make_dict as _make_dict,
    make_range as _make_range,
    list_len as _list_len,
    list_get as _list_get,
    list_push as _list_push,
    list_pop as _list_pop,
    dict_set as _dict_set,
    dict_has as _dict_has,
)
from forthlang.runtime import (
    forge_nil as _forge_nil,
    forge_true as _forge_true,
    forge_false as _forge_false,
    forge_make_list as _forge_make_list,
    forge_make_dict as _forge_make_dict,
    forge_make_range as _forge_make_range,
    forge_list_get as _forge_list_get,
    forge_list_push as _forge_list_push,
    forge_list_pop as _forge_list_pop,
    forge_list_len as _forge_list_len,
    forge_dict_set as _forge_dict_set,
    forge_dict_has as _forge_dict_has,
)
"""


# Word names that aren't valid Python identifiers map to mangled aliases.
# The runtime exports each both ways: the original symbolic name (for
# user-facing kata test calls) and the mangled form (for codegen `def`).
_PY_NAME_MAP = {
    "+": "_op_add", "-": "_op_sub", "*": "_op_mul", "/": "_op_div",
    "mod": "_op_mod",
    "=": "_op_eq", "<>": "_op_ne",
    "<": "_op_lt", ">": "_op_gt",
    "<=": "_op_le", ">=": "_op_ge",
    "and": "_op_and", "or": "_op_or", "not": "_op_not",
    ".": "_print_top",
    "cr": "_cr",
    "@": "_fetch",
    "!": "_store",
    "dup": "dup", "drop": "drop", "swap": "swap",
    "over": "over", "rot": "rot",
    "nip": "nip", "tuck": "tuck",
    # Boolean / null literal-pushes (declared as runtime words)
    "true": "true", "false": "false", "nil": "nil",
    # Collection words
    "list": "_make_list", "dict": "_make_dict", "range": "_make_range",
    "len": "_list_len", "get": "_list_get",
    "push": "_list_push", "l_pop": "_list_pop",
    "dset": "_dict_set", "set!": "_dict_set",
    "has": "_dict_has",
    # === FORGE_STACK_CG_SHIM_BEGIN ===
    'nil':   '_forge_nil',
    'true':  '_forge_true',
    'false': '_forge_false',
    'list':  '_forge_make_list',
    'dict':  '_forge_make_dict',
    'range': '_forge_make_range',
    'get':   '_forge_list_get',
    'push':  '_forge_list_push',
    'l_pop': '_forge_list_pop',
    'len':   '_forge_list_len',
    'dset':  '_forge_dict_set',
    'set!':  '_forge_dict_set',
    'has':   '_forge_dict_has',
    # === FORGE_STACK_CG_SHIM_END ===

}


def _py_name(name: str) -> str:
    """Translate a Forth word name to a Python identifier.

    Built-in operator names and stack ops have direct mappings (above).
    User-defined words might contain `-` `?` `!` etc.; we substitute
    them consistently both at definition and call sites.
    """
    if name in _PY_NAME_MAP:
        return _PY_NAME_MAP[name]
    return (
        name
        .replace("-", "_")
        .replace("?", "_q")
        .replace("!", "_bang")
        .replace("/", "_div")
        .replace("=", "_eq")
        .replace("<", "_lt")
        .replace(">", "_gt")
    )


# ---------------------------------------------------------------------------
# Code emitter
# ---------------------------------------------------------------------------

class CodeGen:
    """Emits Python from a forthlang AST.

    State carried: `indent_level` (Python indent depth), `defined_words`
    (set of names defined at module scope, for global/local resolution).
    """

    def __init__(self):
        self.indent_level = 0
        self.defined_words: set[str] = set()
        self.declared_vars: set[str] = set()    # `variable` declarations

    def indent(self) -> str:
        return "    " * self.indent_level

    def generate(self, ast: list[dict]) -> str:
        # First pass: collect top-level word definitions + variable
        # declarations so nested calls can resolve.
        for form in ast:
            k = form.get("kind")
            if k == "colon_def":
                self.defined_words.add(form["name"])
            elif k == "variable_decl":
                self.declared_vars.add(form["name"])
            elif k == "constant_decl":
                # Constants are "named values"; we emit a Python helper
                # that pushes the value when called.
                self.defined_words.add(form["name"])

        out = [PRELUDE]
        for form in ast:
            out.extend(self.emit_form(form, top_level=True))
        return "\n".join(out) + "\n"

    def emit_form(self, form: dict, *, top_level: bool = False) -> list[str]:
        """Emit Python lines for a single form. Returns a list of lines
        already prefixed with `self.indent()`."""
        k = form.get("kind")
        method = getattr(self, f"emit_{k}", None)
        if method is None:
            return [f"{self.indent()}# unhandled form: {k}"]
        return method(form, top_level=top_level)

    # ---- literals + simple words ----

    def emit_num(self, form: dict, *, top_level: bool) -> list[str]:
        return [f"{self.indent()}push({form['value']})"]

    def emit_float(self, form: dict, *, top_level: bool) -> list[str]:
        return [f"{self.indent()}push({form['value']})"]

    def emit_strpush(self, form: dict, *, top_level: bool) -> list[str]:
        s = form["value"].replace("\\", "\\\\").replace('"', '\\"')
        return [f'{self.indent()}push("{s}")']

    def emit_strprint(self, form: dict, *, top_level: bool) -> list[str]:
        s = form["value"].replace("\\", "\\\\").replace('"', '\\"')
        return [f'{self.indent()}_print_str("{s}")']

    def emit_name(self, form: dict, *, top_level: bool) -> list[str]:
        name = form["value"]
        # Variable name (declared via `variable foo`) resolves to a push
        # of its address-equivalent (the variable name as a string key).
        if name in self.declared_vars:
            return [f'{self.indent()}pushv("{name}")']
        # Ordinary word call: look up the Python alias.
        py = _py_name(name)
        return [f"{self.indent()}{py}()"]

    # ---- declarations ----

    def emit_variable_decl(self, form: dict, *, top_level: bool) -> list[str]:
        name = form["name"]
        self.declared_vars.add(name)
        return [f'{self.indent()}_declare_variable("{name}")']

    def emit_constant_decl(self, form: dict, *, top_level: bool) -> list[str]:
        # `42 constant pi` declares pi as a constant whose value is 42.
        # The 42 is already on the stack from the preceding `num` form.
        name = form["name"]
        self.defined_words.add(name)
        py = _py_name(name)
        # Pop the value and define a function that re-pushes it.
        lines = [
            f'{self.indent()}_declare_constant("{name}", pop())',
            f"{self.indent()}def {py}():",
            f'{self.indent()}    push(_consts["{name}"])',
        ]
        return lines

    def emit_colon_def(self, form: dict, *, top_level: bool) -> list[str]:
        name = form["name"]
        py = _py_name(name)
        lines = [f"{self.indent()}def {py}():"]
        # Emit body at one extra indent.
        self.indent_level += 1
        if form["body"]:
            for child in form["body"]:
                lines.extend(self.emit_form(child))
        else:
            lines.append(f"{self.indent()}pass")
        self.indent_level -= 1
        return lines

    # ---- control structures ----

    def emit_if(self, form: dict, *, top_level: bool) -> list[str]:
        # `if` consumes the top of stack; truthy → then-body, else else-body.
        lines = [f"{self.indent()}if _toy_truthy(pop()):"]
        self.indent_level += 1
        if form["then_body"]:
            for child in form["then_body"]:
                lines.extend(self.emit_form(child))
        else:
            lines.append(f"{self.indent()}pass")
        self.indent_level -= 1
        if form["else_body"]:
            lines.append(f"{self.indent()}else:")
            self.indent_level += 1
            for child in form["else_body"]:
                lines.extend(self.emit_form(child))
            self.indent_level -= 1
        return lines

    def emit_begin_until(self, form: dict, *, top_level: bool) -> list[str]:
        # `begin body until`: execute body, then check top of stack.
        # Top is true → exit. Top is false → loop.
        lines = [f"{self.indent()}while True:"]
        self.indent_level += 1
        if form["body"]:
            for child in form["body"]:
                lines.extend(self.emit_form(child))
        lines.append(f"{self.indent()}if _toy_truthy(pop()): break")
        self.indent_level -= 1
        return lines

    def emit_begin_again(self, form: dict, *, top_level: bool) -> list[str]:
        # `begin body again` is an infinite loop. We compile it as
        # `while True:`. Forth's `leave` would need to be implemented
        # via raise + try/except; we don't ship `leave` so users should
        # prefer `begin ... until` instead.
        lines = [f"{self.indent()}while True:"]
        self.indent_level += 1
        if form["body"]:
            for child in form["body"]:
                lines.extend(self.emit_form(child))
        else:
            lines.append(f"{self.indent()}break  # empty body would spin")
        self.indent_level -= 1
        return lines

    def emit_do_loop(self, form: dict, *, top_level: bool) -> list[str]:
        # `limit start do body loop`: pop start + limit off stack,
        # run body for each value of `i` from start to limit-1.
        # Forth's `i` word fetches the loop counter; we expose it.
        lines = [
            f"{self.indent()}_do_start = pop()",
            f"{self.indent()}_do_limit = pop()",
            f"{self.indent()}for _do_i in range(_do_start, _do_limit):",
        ]
        self.indent_level += 1
        # Inside the body, `i` (lowercase) pushes the counter.
        # We handle this by overriding the dispatch: any `name` form
        # whose value is "i" inside a do_loop pushes _do_i. Simplest
        # implementation: emit a tiny shim before the body.
        lines.append(f"{self.indent()}def i(): push(_do_i)")
        if form["body"]:
            for child in form["body"]:
                lines.extend(self.emit_form(child))
        else:
            lines.append(f"{self.indent()}pass")
        self.indent_level -= 1
        return lines


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate(ast: list[dict]) -> str:
    """Walk the AST, return runnable Python source."""
    cg = CodeGen()
    return cg.generate(ast)


if __name__ == "__main__":
    import sys
    from .parser import parse
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    print(generate(parse(text)))
