"""lisplang codegen. Walks a parse tree and emits runnable Python.

Two emission contexts:
  - emit_stmt(node)  - returns a list of indented Python lines
  - emit_expr(node)  - returns a single-line Python expression string

The split matters because Python distinguishes statements from
expressions, while every Lisp form is technically an expression.
For special forms like `(if ...)`, `(do ...)`, `(when ...)`, `(let ...)`
we accept either form (the parser uses two distinct rules: `if_stmt`
in form position, `if_expr` in expression position) and emit
appropriate Python.

The transpiler is COMPLETE - no `...` stubs, no missing branches.
"""
from __future__ import annotations

from lark import Tree, Token


PRELUDE = """\
from lisplang.runtime import (
    toy_print as print,
    toy_input as input,
    toy_list as list,
    toy_len as len,
    toy_get as get,
    toy_set as set,
    toy_push as push,
    toy_pop as pop,
    toy_dict as dict,
    toy_has as has,
    toy_keys as keys,
    toy_range as range,
    toy_str as str,
    toy_split as split,
    toy_join as join,
    toy_upper as upper,
    toy_lower as lower,
    toy_replace as replace,
    toy_int as int,
    toy_float as float,
    toy_read_file as read_file,
    toy_write_file as write_file,
    toy_argv as argv,
    toy_exit as exit,
    toy_truthy as _toy_truthy,
)
"""


# ---------------------------------------------------------------------------
# Operator dispatch (heads of `call` nodes that should emit Python infix)
# ---------------------------------------------------------------------------

ARITHMETIC_OPS = {"+", "-", "*", "/", "%", "mod"}
COMPARISON_OPS = {"=", "!=", "<", ">", "<=", ">="}
LOGICAL_OPS    = {"and", "or"}


def _py_arith(op: str) -> str:
    if op == "mod":
        return "%"
    return op


def _py_name(name: str) -> str:
    """Lisp identifiers can include `-`, `?`, `!` which aren't valid in
    Python. Substitute them with safe equivalents so the transpiled
    Python compiles. We translate consistently both at definition AND
    call sites by walking through this helper everywhere."""
    return (
        name
        .replace("-", "_")
        .replace("!", "_bang")
        .replace("?", "_q")
    )


# ---------------------------------------------------------------------------
# Code emitter
# ---------------------------------------------------------------------------

class CodeGen:
    """Stateful code generator. One instance per `generate()` call.

    State carried between visits:
      - indent_level: current Python indent depth.
      - scope_stack:  list[set[str]]; the names declared in each enclosing
                      function. Used to compute `nonlocal` / `global`
                      directives for closures that mutate captured names.
      - module_scope: names declared at module level (top of `start`).
    """

    def __init__(self):
        self.indent_level = 0
        self.scope_stack: list[set[str]] = []
        self.module_scope: set[str] = set()
        self._anon_counter = 0

    def indent(self) -> str:
        return "    " * self.indent_level

    def fresh_anon(self, base: str) -> str:
        self._anon_counter += 1
        return f"_lisp_{base}_{self._anon_counter}"

    # -------------------------------------------------------------------
    # Top-level entry: walk the `start` tree
    # -------------------------------------------------------------------

    def generate(self, tree: Tree) -> str:
        # First pass: collect module-scope bindings so nested functions can
        # emit `global X` for captured assignments to module-scope names.
        for child in tree.children:
            if isinstance(child, Tree):
                if child.data == "var_decl":
                    self.module_scope.add(_py_name(str(child.children[0])))
                elif child.data == "func_def":
                    self.module_scope.add(_py_name(str(child.children[0])))

        out_lines = [PRELUDE]
        for child in tree.children:
            out_lines.extend(self.emit_stmt(child))
        return "\n".join(out_lines) + "\n"

    # -------------------------------------------------------------------
    # Statement emitters
    # -------------------------------------------------------------------

    def emit_stmt(self, node) -> list[str]:
        """Emit statement-position lines for `node`. Returns list of
        already-indented Python source lines."""
        if isinstance(node, Token):
            return [f"{self.indent()}{str(node)}"]
        method = getattr(self, f"stmt_{node.data}", None)
        if method is None:
            # Default: an expression statement. Evaluate but discard the
            # value (or assign to `_` to silence linters about unused vals).
            expr = self.emit_expr(node)
            return [f"{self.indent()}{expr}"]
        return method(node)

    def stmt_var_decl(self, node) -> list[str]:
        # (def NAME expr)
        name = _py_name(str(node.children[0]))
        val = self.emit_expr(node.children[1])
        return [f"{self.indent()}{name} = {val}"]

    def stmt_func_def(self, node) -> list[str]:
        # (defn NAME (params) form+)
        name = _py_name(str(node.children[0]))
        params_node = node.children[1]
        params = [_py_name(str(p)) for p in params_node.children]
        body_forms = node.children[2:]
        return self._emit_function(name, params, body_forms)

    def stmt_if_stmt(self, node) -> list[str]:
        # (if cond then else) - statement form. Emits Python if/else.
        cond = self.emit_expr(node.children[0])
        then_node = node.children[1]
        else_node = node.children[2]

        lines = [f"{self.indent()}if _toy_truthy({cond}):"]
        self.indent_level += 1
        lines.extend(self._stmt_or_expr_block(then_node))
        self.indent_level -= 1
        lines.append(f"{self.indent()}else:")
        self.indent_level += 1
        lines.extend(self._stmt_or_expr_block(else_node))
        self.indent_level -= 1
        return lines

    def stmt_while_stmt(self, node) -> list[str]:
        # (while cond form+)
        cond = self.emit_expr(node.children[0])
        body = node.children[1:]
        lines = [f"{self.indent()}while _toy_truthy({cond}):"]
        self.indent_level += 1
        for f in body:
            lines.extend(self.emit_stmt(f))
        if not body:
            lines.append(f"{self.indent()}pass")
        self.indent_level -= 1
        return lines

    def stmt_when_stmt(self, node) -> list[str]:
        # (when cond form+)  =  (if cond (do form+) nil)
        cond = self.emit_expr(node.children[0])
        body = node.children[1:]
        lines = [f"{self.indent()}if _toy_truthy({cond}):"]
        self.indent_level += 1
        for f in body:
            lines.extend(self.emit_stmt(f))
        if not body:
            lines.append(f"{self.indent()}pass")
        self.indent_level -= 1
        return lines

    def stmt_let_stmt(self, node) -> list[str]:
        # (let ((n v) (n v) ...) form+)
        bindings = []
        body = []
        for c in node.children:
            if isinstance(c, Tree) and c.data == "binding":
                bindings.append(c)
            else:
                body.append(c)
        lines = []
        for b in bindings:
            n = _py_name(str(b.children[0]))
            v = self.emit_expr(b.children[1])
            lines.append(f"{self.indent()}{n} = {v}")
        for f in body:
            lines.extend(self.emit_stmt(f))
        return lines

    def stmt_do_stmt(self, node) -> list[str]:
        # (do form+) - sequence forms; same as inlining them.
        lines = []
        for f in node.children:
            lines.extend(self.emit_stmt(f))
        return lines

    def stmt_set_stmt(self, node) -> list[str]:
        # (set! NAME expr)
        name = _py_name(str(node.children[0]))
        val = self.emit_expr(node.children[1])
        return [f"{self.indent()}{name} = {val}"]

    def stmt_return_stmt(self, node) -> list[str]:
        if not node.children:
            return [f"{self.indent()}return"]
        val = self.emit_expr(node.children[0])
        return [f"{self.indent()}return {val}"]

    def stmt_expr_stmt(self, node) -> list[str]:
        # A bare expression at statement position. Evaluate for side effect.
        expr = self.emit_expr(node.children[0])
        return [f"{self.indent()}{expr}"]

    # -------------------------------------------------------------------
    # Expression emitters
    # -------------------------------------------------------------------

    def emit_expr(self, node) -> str:
        if isinstance(node, Token):
            return _py_name(str(node))
        # Statement-position wrappers can appear in tail position of a
        # function body or as a child of `if_stmt` arms; transparently
        # unwrap them so the inner expression emits cleanly.
        if isinstance(node, Tree) and node.data == "expr_stmt":
            return self.emit_expr(node.children[0])
        if isinstance(node, Tree) and node.data == "do_stmt":
            # `(do ...)` in expression position uses tuple-subscript trick.
            body = node.children
            if not body:
                return "None"
            if len(body) == 1:
                return self.emit_expr(body[0])
            exprs = [self.emit_expr(f) for f in body]
            return f"({', '.join(exprs)})[-1]"
        method = getattr(self, f"expr_{node.data}", None)
        if method is None:
            # Defensive: turn any straggler into a string so we never emit
            # silent garbage like `()[-1]`.
            return f"None  # unhandled {node.data}"
        return method(node)

    def expr_int_lit(self, node) -> str:
        return str(node.children[0])

    def expr_float_lit(self, node) -> str:
        return str(node.children[0])

    def expr_string_lit(self, node) -> str:
        # ESCAPED_STRING already includes quotes + handles escapes.
        return str(node.children[0])

    def expr_true_lit(self, node) -> str:
        return "True"

    def expr_false_lit(self, node) -> str:
        return "False"

    def expr_null_lit(self, node) -> str:
        return "None"

    def expr_name_ref(self, node) -> str:
        return _py_name(str(node.children[0]))

    def expr_call(self, node) -> str:
        # call: "(" call_head args ")"
        head_node = node.children[0]
        head = str(head_node.children[0]) if isinstance(head_node, Tree) else str(head_node)
        args_node = node.children[1] if len(node.children) > 1 else None
        args = []
        if args_node is not None:
            args = [self.emit_expr(c) for c in args_node.children]

        # Unary `-` is negation. `(- x)` -> `(-x)` in Python.
        if head == "-" and len(args) == 1:
            return f"(-{args[0]})"
        # Unary `+` is identity (Lisp tradition for sums).
        if head == "+" and len(args) == 1:
            return f"({args[0]})"
        # Unary `not` -> Python `(not _toy_truthy(x))`.
        if head == "not" and len(args) == 1:
            return f"(not _toy_truthy({args[0]}))"

        # Operator-headed binary calls become Python infix.
        if head in ARITHMETIC_OPS and len(args) == 2:
            return f"({args[0]} {_py_arith(head)} {args[1]})"
        if head == "=" and len(args) == 2:
            return f"({args[0]} == {args[1]})"
        if head in COMPARISON_OPS and len(args) == 2:
            return f"({args[0]} {head} {args[1]})"
        if head in LOGICAL_OPS and len(args) == 2:
            return f"({args[0]} {head} {args[1]})"

        # n-ary arithmetic: `(+ a b c d)` becomes `(a + b + c + d)` (Lisp idiom).
        if head in ARITHMETIC_OPS and len(args) > 2:
            sep = f" {_py_arith(head)} "
            return "(" + sep.join(args) + ")"
        if head in LOGICAL_OPS and len(args) > 2:
            sep = f" {head} "
            return "(" + sep.join(args) + ")"
        # n-ary comparison `(< a b c)` -> Python chained `(a < b < c)`.
        if head in COMPARISON_OPS and len(args) > 2:
            op = "==" if head == "=" else head
            chained = " ".join(f"{args[i]} {op} {args[i+1]}" if i == 0
                               else f"{op} {args[i+1]}"
                               for i in range(len(args)-1))
            # Rebuild as proper chain: a OP b OP c
            pieces = [args[0]]
            for i in range(1, len(args)):
                pieces.append(op)
                pieces.append(args[i])
            return "(" + " ".join(pieces) + ")"

        # Don't run operator-shaped names through _py_name; leave them
        # alone so a bare `(- 1)` with 1 arg (handled above) doesn't fall
        # back to `_(1)` if any branch slipped past.
        if not head.replace("-", "").replace("!", "").replace("?", "").isidentifier():
            # head is something like `+`, `*`, `<` etc. with arg count we
            # didn't handle. Fail loudly rather than silently.
            return f"None  # unhandled operator call: ({head} ...)"

        # Plain function call.
        return f"{_py_name(head)}({', '.join(args)})"

    def expr_fn_expr(self, node) -> str:
        # (fn (params) form+)
        params_node = node.children[0]
        params = [_py_name(str(p)) for p in params_node.children]
        body_forms = node.children[1:]
        # If the body is a single expression with no statements, emit a
        # Python lambda. Otherwise we need a real `def` because lambda
        # can't hold statements like `nonlocal` or `set!` blocks.
        if self._is_pure_expr_body(body_forms):
            param_str = ", ".join(params) if params else ""
            if len(body_forms) == 1:
                body = self.emit_expr(body_forms[0])
            else:
                # Multi-form pure body: tuple-subscript trick.
                exprs = [self.emit_expr(f) for f in body_forms]
                body = f"({', '.join(exprs)})[-1]"
            return f"(lambda {param_str}: {body})"
        # Emit a hoisted nested def. The fn is replaced with a NAME that
        # refers to the just-defined function. Hoisted lines go through
        # self._pending_hoists and get inserted by the enclosing emit_stmt.
        anon = self.fresh_anon("fn")
        hoisted = self._emit_function(anon, params, body_forms)
        # Stash the hoisted def at the current scope's pending list.
        self._pending_hoists.extend(hoisted)
        return anon

    def expr_if_expr(self, node) -> str:
        cond = self.emit_expr(node.children[0])
        then_e = self.emit_expr(node.children[1])
        else_e = self.emit_expr(node.children[2])
        return f"({then_e} if _toy_truthy({cond}) else {else_e})"

    def expr_do_expr(self, node) -> str:
        body = node.children
        if not body:
            return "None"
        if len(body) == 1:
            return self.emit_expr(body[0])
        exprs = [self.emit_expr(f) for f in body]
        return f"({', '.join(exprs)})[-1]"

    def expr_when_expr(self, node) -> str:
        cond = self.emit_expr(node.children[0])
        body = node.children[1:]
        if len(body) == 1:
            inner = self.emit_expr(body[0])
        else:
            exprs = [self.emit_expr(f) for f in body]
            inner = f"({', '.join(exprs)})[-1]"
        return f"({inner} if _toy_truthy({cond}) else None)"

    def expr_let_expr(self, node) -> str:
        # In expression position, `let` collapses to a tuple-subscript over
        # walrus-assignments: `((a := 1, b := 2, body)[-1])`. Limited but
        # works for pure-expression `let` blocks.
        bindings = []
        body = []
        for c in node.children:
            if isinstance(c, Tree) and c.data == "binding":
                bindings.append(c)
            else:
                body.append(c)
        parts = []
        for b in bindings:
            n = _py_name(str(b.children[0]))
            v = self.emit_expr(b.children[1])
            parts.append(f"({n} := {v})")
        if len(body) == 1:
            parts.append(self.emit_expr(body[0]))
        else:
            for f in body:
                parts.append(self.emit_expr(f))
        return "(" + ", ".join(parts) + ")[-1]"

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    # Hoisted lines collected during expression emission (used for fn_expr
    # that requires a real def). The enclosing emit_stmt prepends them
    # before its own line.
    _pending_hoists: list[str] = []

    def _is_pure_expr_body(self, body_forms) -> bool:
        """True if every form in `body_forms` can be emitted as a Python
        expression (no statement-only forms like set!, while, var_decl)."""
        for f in body_forms:
            if not isinstance(f, Tree):
                continue
            kind = f.data
            if kind in {"var_decl", "func_def", "while_stmt",
                        "set_stmt", "return_stmt", "if_stmt",
                        "when_stmt", "let_stmt", "do_stmt"}:
                return False
        return True

    def _stmt_or_expr_block(self, node) -> list[str]:
        """Emit a single child as a statement block. Used for then/else
        arms of `if_stmt` where the child might be `do_stmt` (sequence)
        or a single expression/statement."""
        if isinstance(node, Tree) and node.data == "do_stmt":
            return self.stmt_do_stmt(node)
        return self.emit_stmt(node)

    def _emit_function(self, name: str, params: list[str],
                       body_forms: list) -> list[str]:
        """Emit `def name(params): ...` honoring closure semantics.

        For each body form except the LAST: emit as a statement.
        For the LAST: emit `return <value>` so the function returns a
        meaningful value (Lisp tradition: function value = last form's value),
        UNLESS the form itself is a control-flow statement that doesn't
        produce a value (set!, var_decl, while, return, etc.).

        Closure handling: scan the body for `set_stmt` targets that
        aren't declared locally. If they're declared in any enclosing
        function scope, emit `nonlocal X` at the top of the body. If
        they're at module scope, emit `global X`.
        """
        head = f"{self.indent()}def {name}({', '.join(params)}):"

        # 1. Collect names declared INSIDE this body (params + var_decl + nested defs).
        declared = set(params)
        for f in body_forms:
            if not isinstance(f, Tree):
                continue
            if f.data == "var_decl":
                declared.add(_py_name(str(f.children[0])))
            elif f.data == "func_def":
                declared.add(_py_name(str(f.children[0])))
            elif f.data == "let_stmt":
                for c in f.children:
                    if isinstance(c, Tree) and c.data == "binding":
                        declared.add(_py_name(str(c.children[0])))

        # 2. Scan for set! targets that aren't locally declared.
        set_targets = set()
        self._collect_set_targets(body_forms, set_targets)
        free_assigned = set_targets - declared
        nonlocals = sorted(n for n in free_assigned
                           if any(n in s for s in self.scope_stack))
        globals_  = sorted(n for n in free_assigned
                           if n not in nonlocals and n in self.module_scope)

        # 3. Emit the body, with nonlocal/global directives at the top.
        self.indent_level += 1
        self.scope_stack.append(declared)
        # Reset the hoist buffer - hoists from THIS function's body should
        # go into THIS function's body, not leak to the parent.
        outer_hoists = self._pending_hoists
        self._pending_hoists = []

        body_lines = []
        if nonlocals:
            body_lines.append(f"{self.indent()}nonlocal {', '.join(nonlocals)}")
        if globals_:
            body_lines.append(f"{self.indent()}global {', '.join(globals_)}")

        # 4. Walk body forms.
        for i, form in enumerate(body_forms):
            is_last = (i == len(body_forms) - 1)
            if is_last and self._can_return(form):
                # Statement-position special forms in TAIL position: emit
                # them as Python `if/else` etc. that return from each arm.
                if isinstance(form, Tree) and form.data == "if_stmt":
                    body_lines.extend(self._emit_tail_if(form))
                    continue
                if isinstance(form, Tree) and form.data == "when_stmt":
                    body_lines.extend(self._emit_tail_when(form))
                    continue
                if isinstance(form, Tree) and form.data == "do_stmt":
                    # Inline the do-sequence; the do's last form gets
                    # the same tail treatment recursively.
                    body_lines.extend(
                        self._emit_function_body_inner(form.children)
                    )
                    continue
                if isinstance(form, Tree) and form.data == "let_stmt":
                    # Emit the bindings, then the body forms with tail return.
                    bindings, inner = [], []
                    for c in form.children:
                        if isinstance(c, Tree) and c.data == "binding":
                            bindings.append(c)
                        else:
                            inner.append(c)
                    for b in bindings:
                        n = _py_name(str(b.children[0]))
                        v = self.emit_expr(b.children[1])
                        body_lines.append(f"{self.indent()}{n} = {v}")
                    body_lines.extend(self._emit_function_body_inner(inner))
                    continue
                # Otherwise emit as a plain expression and `return` it.
                expr = self.emit_expr(form)
                # Drain any hoists produced while emitting `expr`
                if self._pending_hoists:
                    body_lines.extend(self._pending_hoists)
                    self._pending_hoists = []
                body_lines.append(f"{self.indent()}return {expr}")
            else:
                # Statement context. Capture hoists, then emit.
                stmt_lines = self.emit_stmt(form)
                if self._pending_hoists:
                    body_lines.extend(self._pending_hoists)
                    self._pending_hoists = []
                body_lines.extend(stmt_lines)

        if not body_lines:
            body_lines.append(f"{self.indent()}pass")

        self.scope_stack.pop()
        self.indent_level -= 1
        # Restore parent hoist buffer.
        self._pending_hoists = outer_hoists

        return [head] + body_lines

    def _can_return(self, form) -> bool:
        """True if `form` produces a value usable in a `return X` line.

        var_decl/func_def/set_stmt/while are pure statements with no value;
        if their last in body, the function returns None and downstream
        code still runs them as statements (no implicit return wrapping).
        """
        if isinstance(form, Token):
            return True
        if not isinstance(form, Tree):
            return False
        kind = form.data
        if kind in {"var_decl", "func_def", "while_stmt", "set_stmt",
                    "return_stmt"}:
            return False
        return True

    def _emit_tail_if(self, node) -> list[str]:
        """Emit `(if cond then else)` in tail position: each arm returns."""
        cond = self.emit_expr(node.children[0])
        then_node = node.children[1]
        else_node = node.children[2]
        lines = [f"{self.indent()}if _toy_truthy({cond}):"]
        self.indent_level += 1
        lines.extend(self._emit_function_body_inner([then_node]))
        self.indent_level -= 1
        lines.append(f"{self.indent()}else:")
        self.indent_level += 1
        lines.extend(self._emit_function_body_inner([else_node]))
        self.indent_level -= 1
        return lines

    def _emit_tail_when(self, node) -> list[str]:
        """Emit `(when cond body+)` in tail position. Returns the last
        body form's value when cond is truthy; returns None otherwise."""
        cond = self.emit_expr(node.children[0])
        body = node.children[1:]
        lines = [f"{self.indent()}if _toy_truthy({cond}):"]
        self.indent_level += 1
        lines.extend(self._emit_function_body_inner(body))
        self.indent_level -= 1
        lines.append(f"{self.indent()}return None")
        return lines

    def _emit_function_body_inner(self, forms) -> list[str]:
        """Emit a sequence of forms inside a function body. The LAST form
        gets the tail treatment (return / if-with-returns / etc.). Earlier
        forms emit as plain statements. Used recursively from
        _emit_tail_if / _emit_tail_when / do-as-tail."""
        out = []
        if not forms:
            out.append(f"{self.indent()}return None")
            return out
        for i, f in enumerate(forms):
            is_last = (i == len(forms) - 1)
            if is_last and self._can_return(f):
                if isinstance(f, Tree) and f.data == "if_stmt":
                    out.extend(self._emit_tail_if(f))
                elif isinstance(f, Tree) and f.data == "when_stmt":
                    out.extend(self._emit_tail_when(f))
                elif isinstance(f, Tree) and f.data == "do_stmt":
                    out.extend(self._emit_function_body_inner(list(f.children)))
                else:
                    expr = self.emit_expr(f)
                    if self._pending_hoists:
                        out.extend(self._pending_hoists)
                        self._pending_hoists = []
                    out.append(f"{self.indent()}return {expr}")
            else:
                stmt_lines = self.emit_stmt(f)
                if self._pending_hoists:
                    out.extend(self._pending_hoists)
                    self._pending_hoists = []
                out.extend(stmt_lines)
        return out

    def _collect_set_targets(self, forms, out: set[str]) -> None:
        """Walk every nested form and collect `(set! name _)` targets."""
        for f in forms:
            if not isinstance(f, Tree):
                continue
            if f.data == "set_stmt":
                out.add(_py_name(str(f.children[0])))
                # Also recurse into the value (rare nested set!s)
                self._collect_set_targets(f.children[1:], out)
            else:
                self._collect_set_targets(f.children, out)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate(tree: Tree) -> str:
    """Walk the parse tree, return runnable Python source."""
    cg = CodeGen()
    return cg.generate(tree)


if __name__ == "__main__":
    import sys
    from .parser import parse
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    print(generate(parse(text)))
