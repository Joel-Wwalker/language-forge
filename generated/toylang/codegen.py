"""Toylang codegen — walk the Lark Tree, emit Python source.

The generated Python is self-contained: a small prelude imports the toylang
runtime helpers (toy_print as `print`, toy_truthy, etc.) and then user code
follows in transpiled form.

The trickiest piece is closure handling: when a nested function assigns to a
name from an enclosing function scope, we must emit a Python `nonlocal`
declaration. We do this with a small scope-analysis pass per function:

  declared = parameters ∪ var-decls ∪ inner-func-defs in this body
  assigned = names appearing as LHS of `assign_op` (no `var`) in this body
  free_assigned = assigned − declared
  for each name in free_assigned:
    if name is in any enclosing function's `declared` → emit `nonlocal name`
    else → emit `global name`
"""
from __future__ import annotations

from lark import Tree, Token


PRELUDE = '''\
# --- toylang generated python ---
from toylang.runtime import (
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

'''


# ---------------------------------------------------------------------------
# Scope analysis helpers
# ---------------------------------------------------------------------------

def _declared_in_stmts(stmts):
    """Names that this scope declares at the given list of statements.

    Walks into control-flow blocks (if/while/bare block) but NOT into nested
    func_def bodies — those introduce their own scope.
    """
    out = set()
    for stmt in stmts:
        if not isinstance(stmt, Tree):
            continue
        if stmt.data == "var_decl":
            out.add(str(stmt.children[0]))
        elif stmt.data == "func_def":
            # `func name(...) { ... }` binds `name` in the enclosing scope.
            out.add(str(stmt.children[0]))
        elif stmt.data == "if_stmt":
            out |= _declared_in_stmts(stmt.children[1].children)
            if len(stmt.children) > 2:
                out |= _declared_in_else(stmt.children[2])
        elif stmt.data == "while_stmt":
            out |= _declared_in_stmts(stmt.children[1].children)
        elif stmt.data == "block":
            out |= _declared_in_stmts(stmt.children)
    return out


def _declared_in_else(else_tree):
    inner = else_tree.children[0]
    if inner.data == "block":
        return _declared_in_stmts(inner.children)
    if inner.data == "if_stmt":
        out = _declared_in_stmts(inner.children[1].children)
        if len(inner.children) > 2:
            out |= _declared_in_else(inner.children[2])
        return out
    return set()


def _assigned_in_stmts(stmts):
    """Names that appear as LHS of plain assignment (assign_op).

    Recurses through control-flow constructs, but stops at nested func_def
    bodies (their assignments belong to a deeper scope).
    """
    out = set()

    def walk(node):
        if not isinstance(node, Tree):
            return
        if node.data == "func_def":
            return
        if node.data == "assign_op":
            out.add(str(node.children[0]))
        for c in node.children:
            walk(c)

    for s in stmts:
        walk(s)
    return out


# ---------------------------------------------------------------------------
# Codegen
# ---------------------------------------------------------------------------

class Codegen:
    def __init__(self):
        self.lines: list[str] = []
        self.indent: int = 0
        # Stack of declared-locals sets, one per active scope. scopes[0] is the
        # module scope; new scopes are pushed for each function body.
        self.scopes: list[set[str]] = [set()]

    def emit(self, line: str) -> None:
        self.lines.append("    " * self.indent + line)

    def generate(self, tree: Tree) -> str:
        # Prepopulate module scope with all top-level declarations so nested
        # functions can attribute free assignments to globals correctly.
        self.scopes[0] |= _declared_in_stmts(tree.children)
        for stmt in tree.children:
            self.visit_stmt(stmt)
        return "\n".join(self.lines) + "\n"

    # ---- statement visitors -------------------------------------------------

    def visit_stmt(self, t):
        method = getattr(self, f"visit_{t.data}", None)
        if method is None:
            raise SyntaxError(f"codegen: unknown stmt {t.data!r}")
        method(t)

    def visit_var_decl(self, t):
        name = str(t.children[0])
        rhs = self.expr(t.children[1])
        self.emit(f"{name} = {rhs}")

    def visit_func_def(self, t):
        name = str(t.children[0])
        params_tree = None
        block_tree = None
        for c in t.children[1:]:
            if isinstance(c, Tree) and c.data == "params":
                params_tree = c
            elif isinstance(c, Tree) and c.data == "block":
                block_tree = c

        param_names = [str(p) for p in params_tree.children] if params_tree else []
        body_stmts = block_tree.children

        declared = set(param_names) | _declared_in_stmts(body_stmts)
        assigned = _assigned_in_stmts(body_stmts)
        free_assigns = assigned - declared

        nonlocals: list[str] = []
        globals_: list[str] = []
        for nm in sorted(free_assigns):
            found_enclosing = False
            # Walk enclosing function scopes (skip module scope at index 0).
            for sc in reversed(self.scopes[1:]):
                if nm in sc:
                    nonlocals.append(nm)
                    found_enclosing = True
                    break
            if not found_enclosing:
                globals_.append(nm)
                # Record at module scope so subsequent free-assignments resolve.
                self.scopes[0].add(nm)

        self.emit(f"def {name}({', '.join(param_names)}):")
        self.indent += 1
        self.scopes.append(declared)

        if nonlocals:
            self.emit(f"nonlocal {', '.join(nonlocals)}")
        if globals_:
            self.emit(f"global {', '.join(globals_)}")

        if not body_stmts:
            self.emit("pass")
        else:
            for s in body_stmts:
                self.visit_stmt(s)

        self.scopes.pop()
        self.indent -= 1

    def visit_if_stmt(self, t):
        cond = self.expr(t.children[0])
        self.emit(f"if _toy_truthy({cond}):")
        self._emit_block(t.children[1])
        if len(t.children) > 2:
            self._emit_else(t.children[2])

    def _emit_else(self, else_tree):
        inner = else_tree.children[0]
        if inner.data == "if_stmt":
            cond = self.expr(inner.children[0])
            self.emit(f"elif _toy_truthy({cond}):")
            self._emit_block(inner.children[1])
            if len(inner.children) > 2:
                self._emit_else(inner.children[2])
        else:
            self.emit("else:")
            self._emit_block(inner)

    def visit_while_stmt(self, t):
        cond = self.expr(t.children[0])
        self.emit(f"while _toy_truthy({cond}):")
        self._emit_block(t.children[1])

    def _emit_block(self, block_tree: Tree) -> None:
        self.indent += 1
        if not block_tree.children:
            self.emit("pass")
        else:
            for s in block_tree.children:
                self.visit_stmt(s)
        self.indent -= 1

    def visit_return_stmt(self, t):
        if t.children:
            self.emit(f"return {self.expr(t.children[0])}")
        else:
            self.emit("return")

    def visit_block(self, t):
        # Bare block as a statement. Python has no anonymous blocks, so we
        # inline its contents at the current indent.
        for s in t.children:
            self.visit_stmt(s)

    def visit_expr_stmt(self, t):
        inner = t.children[0]
        # Top-level assignment becomes a Python assignment statement.
        if isinstance(inner, Tree) and inner.data == "assign_op":
            target = str(inner.children[0])
            rhs = self.expr(inner.children[1])
            self.emit(f"{target} = {rhs}")
            return
        self.emit(self.expr(inner))

    # ---- expression visitors ------------------------------------------------

    def expr(self, n):
        if isinstance(n, Token):
            return str(n)
        method = getattr(self, f"e_{n.data}", None)
        if method:
            return method(n)
        # Passthrough for any single-child rule we forgot to special-case.
        if len(n.children) == 1:
            return self.expr(n.children[0])
        raise SyntaxError(f"codegen: unknown expr node {n.data!r}")

    def e_passthru(self, n):
        return self.expr(n.children[0])

    def e_assign_op(self, n):
        # Assignment as a sub-expression isn't allowed in MVP. Tests don't
        # need it; emit walrus as a defensive fallback so tools see something.
        target = str(n.children[0])
        rhs = self.expr(n.children[1])
        return f"({target} := {rhs})"

    # Binary operators: the grammar shape is `lhs (OP rhs)*` so we fold left.
    def _binop(self, n, op_translate=lambda op: op):
        if len(n.children) == 1:
            return self.expr(n.children[0])
        result = self.expr(n.children[0])
        i = 1
        while i < len(n.children):
            op = op_translate(str(n.children[i]))
            rhs = self.expr(n.children[i + 1])
            result = f"({result} {op} {rhs})"
            i += 2
        return result

    def e_logical_or(self, n):  return self._binop(n, lambda _o: "or")
    def e_logical_and(self, n): return self._binop(n, lambda _o: "and")
    def e_equality(self, n):    return self._binop(n)
    def e_comparison(self, n):  return self._binop(n)
    def e_term(self, n):        return self._binop(n)
    def e_factor(self, n):      return self._binop(n)

    def e_unary(self, n):
        if len(n.children) == 1:
            return self.expr(n.children[0])
        op = str(n.children[0])
        rhs = self.expr(n.children[1])
        if op == "!":
            return f"(not {rhs})"
        return f"(-{rhs})"

    def e_call(self, n):
        result = self.expr(n.children[0])
        for tr in n.children[1:]:
            args_str = ""
            if tr.children:
                args_tree = tr.children[0]
                args_str = ", ".join(self.expr(a) for a in args_tree.children)
            result = f"{result}({args_str})"
        return result

    def e_int_lit(self, n):    return str(n.children[0])
    def e_float_lit(self, n):  return str(n.children[0])
    def e_string_lit(self, n): return str(n.children[0])
    def e_true_lit(self, n):   return "True"
    def e_false_lit(self, n):  return "False"
    def e_null_lit(self, n):   return "None"
    def e_name_ref(self, n):   return str(n.children[0])
    def e_paren(self, n):      return f"({self.expr(n.children[0])})"


def generate(tree: Tree) -> str:
    return PRELUDE + Codegen().generate(tree)
