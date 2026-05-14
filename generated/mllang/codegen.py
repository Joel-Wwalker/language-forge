"""mllang codegen — walk the Lark Tree, emit Python source.

Strategy: AST-walking visitor, similar shape to toylang's codegen. The
output is self-contained Python: a prelude pulls in runtime + stdlib
helpers, then transpiled mllang source follows.

Key decisions (per MLLANG_DESIGN.md Section 3):
  - Top-level `let x = expr` -> Python `x = expr`
  - Top-level `let rec f x = expr` -> Python `def f(x): return expr`
  - Curried `let f x y = expr` -> `def f(x, y): return expr` (multi-arg
    shortcut; partial application not preserved in v1)
  - `let ... in expr` -> immediately-invoked lambda in expression
    context; multi-statement block in statement context (top level)
  - `match` -> if/elif cascade ending in `raise _MLMatchError(_v)`
  - ADT constructors -> calls into runtime `_MLConstructor(tag, payload)`
  - `(e1; e2; e3)` -> tuple-discard `(e1, e2, e3)[-1]`
  - `h :: t` -> `_ml_cons(h, t)` from runtime
  - Most operators map 1:1 to Python operators

The codegen distinguishes EXPRESSION context from STATEMENT context.
Top-level items go through `emit_top` which can produce multi-line
statements. Sub-expressions go through `emit_expr` which produces a
single Python expression (using lambdas for `let-in` and helper
functions for nested `match` when necessary).
"""
from __future__ import annotations

from lark import Tree, Token


PRELUDE = '''\
# --- mllang generated python ---
from mllang.runtime import (
    _MLMatchError,
    _MLConstructor,
    _ml_cons,
    print_int,
    print_string,
    print_float,
    print_newline,
    print_endline,
    print_any,
    string_length,
    string_upper,
    string_lower,
    string_concat,
    list_length,
    list_head,
    list_tail,
    list_is_empty,
    string_of_int,
    int_of_string,
)
from mllang.stdlib import (
    list_map,
    list_filter,
    list_fold_left,
    list_fold_right,
    list_reverse,
    list_range,
    list_concat,
)

'''


# Counter for generated fresh names (for match-discriminator binding,
# let-in lambdas, etc.). Reset per `generate()` call.
class _NameGen:
    def __init__(self):
        self._n = 0

    def fresh(self, hint: str) -> str:
        self._n += 1
        return f"_ml_{hint}_{self._n}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_tree(node, name=None):
    if not isinstance(node, Tree):
        return False
    if name is None:
        return True
    return node.data == name


def _token_str(tok):
    return str(tok)


def _indent(text: str, level: int) -> str:
    pad = "    " * level
    return "\n".join(pad + line if line else "" for line in text.split("\n"))


# ---------------------------------------------------------------------------
# Pattern lowering
# ---------------------------------------------------------------------------
#
# Patterns appear in two contexts:
#   - `match` arms (`| pat -> body`)
#   - destructuring `let` bindings (`let (x, y) = pair in ...`)
#
# For each pattern we emit:
#   - a `condition`: a Python expression that is True if the pattern
#     matches the discriminator named `disc`.
#   - a list of `bindings`: (var_name, python_expr) pairs to evaluate
#     once the pattern has matched.

def _lower_pattern(pat, disc_expr, ngen):
    """Return (condition_str, bindings_list).

    `disc_expr` is a Python expression string evaluating to the value
    being matched (typically a fresh variable name).
    `bindings_list` is [(name, expr_str), ...] in order.
    """
    if isinstance(pat, Token):
        raise NotImplementedError(f"bare token pattern: {pat}")
    d = pat.data

    if d == "pat_wild":
        return ("True", [])
    if d == "pat_var":
        name = _token_str(pat.children[0])
        return ("True", [(name, disc_expr)])
    if d == "pat_int":
        v = int(_token_str(pat.children[0]))
        return (f"({disc_expr} == {v})", [])
    if d == "pat_float":
        v = float(_token_str(pat.children[0]))
        return (f"({disc_expr} == {v})", [])
    if d == "pat_string":
        s = _token_str(pat.children[0])  # already includes quotes
        return (f"({disc_expr} == {s})", [])
    if d == "pat_true":
        return (f"({disc_expr} is True)", [])
    if d == "pat_false":
        return (f"({disc_expr} is False)", [])
    if d == "pat_unit":
        return (f"({disc_expr} is None)", [])
    if d == "pat_nil":
        return (f"(isinstance({disc_expr}, list) and len({disc_expr}) == 0)", [])
    if d == "pat_paren":
        return _lower_pattern(pat.children[0], disc_expr, ngen)
    if d == "pat_cons":
        # h :: t   -- head + non-empty list
        head_pat = pat.children[0]
        tail_pat = pat.children[1]
        # Head condition: list with >= 1 element
        list_check = f"(isinstance({disc_expr}, list) and len({disc_expr}) >= 1)"
        head_disc = f"{disc_expr}[0]"
        tail_disc = f"{disc_expr}[1:]"
        h_cond, h_binds = _lower_pattern(head_pat, head_disc, ngen)
        t_cond, t_binds = _lower_pattern(tail_pat, tail_disc, ngen)
        cond = f"({list_check} and {h_cond} and {t_cond})"
        return (cond, h_binds + t_binds)
    if d == "pat_list":
        # [p1; p2; p3]  -- list of exactly N elements
        sub_pats = list(pat.children)
        n = len(sub_pats)
        list_check = f"(isinstance({disc_expr}, list) and len({disc_expr}) == {n})"
        conds = [list_check]
        binds = []
        for i, sp in enumerate(sub_pats):
            sp_disc = f"{disc_expr}[{i}]"
            sp_cond, sp_binds = _lower_pattern(sp, sp_disc, ngen)
            conds.append(sp_cond)
            binds.extend(sp_binds)
        return (f"({' and '.join(conds)})", binds)
    if d == "pat_tuple":
        sub_pats = list(pat.children)
        n = len(sub_pats)
        tup_check = f"(isinstance({disc_expr}, tuple) and len({disc_expr}) == {n})"
        conds = [tup_check]
        binds = []
        for i, sp in enumerate(sub_pats):
            sp_disc = f"{disc_expr}[{i}]"
            sp_cond, sp_binds = _lower_pattern(sp, sp_disc, ngen)
            conds.append(sp_cond)
            binds.extend(sp_binds)
        return (f"({' and '.join(conds)})", binds)
    if d == "pat_ctor":
        # Constructor pattern: `Circle r` or `Red` (nullary).
        ctor_name = _token_str(pat.children[0])
        ctor_check = (
            f"(isinstance({disc_expr}, _MLConstructor) "
            f"and {disc_expr}.tag == {ctor_name!r})"
        )
        if len(pat.children) == 1:
            # Nullary
            return (f"({ctor_check} and {disc_expr}.payload is None)", [])
        payload_pat = pat.children[1]
        payload_disc = f"{disc_expr}.payload"
        p_cond, p_binds = _lower_pattern(payload_pat, payload_disc, ngen)
        return (f"({ctor_check} and {p_cond})", p_binds)
    if d == "pat_or":
        # OR-patterns deferred in v1 design; if we hit one, fall through
        # to TODO error.
        raise NotImplementedError("OR-patterns (`p1 | p2`) deferred in v1")
    raise NotImplementedError(f"pattern: {d}")


# ---------------------------------------------------------------------------
# Expression emission
# ---------------------------------------------------------------------------
#
# emit_expr returns (header_lines, expr_str). The header lines are
# statements (function defs, intermediate assignments) that must precede
# the emitted expression. expr_str is a Python expression usable in
# expression context.
#
# This split is needed because:
#   - `match` and `let-in` produce multi-line Python (helper functions)
#   - But mllang expressions can be sub-expressions inside other
#     expressions, where only a single Python expression fits.
#
# When sub-expression has header lines, we emit a helper function that
# takes no args and call it immediately: `(lambda: (header; return
# expr))()`. The lambda-with-statements pattern uses our `_seq` helper.


def emit_expr(node, ngen):
    """Return (header_lines, expr_str)."""
    if isinstance(node, Token):
        raise NotImplementedError(f"bare token expr: {node}")

    d = node.data

    # Pass-through wrappers from grammar
    if d == "seq_expr":
        return emit_expr(node.children[0], ngen)

    # --- literals ---
    if d == "int_lit":
        return ([], _token_str(node.children[0]))
    if d == "float_lit":
        return ([], _token_str(node.children[0]))
    if d == "string_lit":
        return ([], _token_str(node.children[0]))
    if d == "true_lit":
        return ([], "True")
    if d == "false_lit":
        return ([], "False")
    if d == "unit_lit":
        return ([], "None")
    if d == "nil_lit":
        return ([], "[]")

    # --- references ---
    if d == "name_ref":
        return ([], _token_str(node.children[0]))
    if d == "ctor_ref":
        # A bare constructor reference. Nullary constructors are
        # bound at top-level as `Red = _MLConstructor("Red", None)`.
        # When the user writes `Red` we just emit the name. When they
        # write `Circle 5` the `app` rule handles it as a function call,
        # and we emit `Circle(5)` which calls the constructor function
        # defined at top level.
        return ([], _token_str(node.children[0]))

    # --- collections ---
    if d == "list_lit":
        headers = []
        elems = []
        for ch in node.children:
            h, e = emit_expr(ch, ngen)
            headers.extend(h)
            elems.append(e)
        return (headers, f"[{', '.join(elems)}]")
    if d == "tuple_lit":
        headers = []
        elems = []
        for ch in node.children:
            h, e = emit_expr(ch, ngen)
            headers.extend(h)
            elems.append(e)
        return (headers, f"({', '.join(elems)})")
    if d == "paren":
        return emit_expr(node.children[0], ngen)
    if d == "seq_paren":
        # `(e1; e2; e3)` -> evaluate all left-to-right, return last.
        # Use a tuple constructor + last-index: `(e1, e2, e3)[-1]`.
        headers = []
        elems = []
        for ch in node.children:
            h, e = emit_expr(ch, ngen)
            headers.extend(h)
            elems.append(e)
        return (headers, f"({', '.join(elems)})[-1]")

    # --- operators ---
    if d == "add":
        return _emit_binop(node, ngen, _add_op)
    if d == "mul":
        return _emit_binop(node, ngen, _mul_op)
    if d == "cmp":
        return _emit_binop(node, ngen, _cmp_op)
    if d == "cons":
        h, e1 = emit_expr(node.children[0], ngen)
        h2, e2 = emit_expr(node.children[1], ngen)
        return (h + h2, f"_ml_cons({e1}, {e2})")
    if d == "concat":
        h1, e1 = emit_expr(node.children[0], ngen)
        h2, e2 = emit_expr(node.children[1], ngen)
        return (h1 + h2, f"({e1} + {e2})")
    if d == "bin_and":
        h1, e1 = emit_expr(node.children[0], ngen)
        h2, e2 = emit_expr(node.children[1], ngen)
        return (h1 + h2, f"({e1} and {e2})")
    if d == "bin_or":
        h1, e1 = emit_expr(node.children[0], ngen)
        h2, e2 = emit_expr(node.children[1], ngen)
        return (h1 + h2, f"({e1} or {e2})")
    if d == "bool_not":
        h, e = emit_expr(node.children[0], ngen)
        return (h, f"(not {e})")
    if d == "neg":
        h, e = emit_expr(node.children[0], ngen)
        return (h, f"(-{e})")

    # --- function application ---
    if d == "app":
        # Left-associative chain. Collect the call chain so curried apps
        # (e.g. `f x y`) emit `f(x, y)` in the multi-arg-def shortcut.
        # However, mllang allows partial application at the source
        # level only — codegen accepts it. The shortcut emits multi-arg
        # calls; if the callee was defined as multi-arg `def`, this works.
        # If the callee is itself a returned closure (single-arg lambda
        # returned from a function), we'd need single-arg calls. To
        # support BOTH patterns cleanly, we emit `f(x)(y)` for chained
        # applications by default — Python accepts this for multi-arg
        # functions if they return callables, which would NOT work for
        # `def f(x, y)` accepting two args. So we collapse: emit `f(x, y)`
        # when the chain head is a name (the common case for our v1
        # canonical tests), else emit `f(x)(y)` for higher-order chains.
        #
        # Actually, simplest: ALWAYS chain as `f(x)(y)`. For a multi-arg
        # `def f(x, y)`, calling `f(1)(2)` doesn't work. So we collect
        # the chain and emit the all-at-once call.
        args = []
        head = node
        headers = []
        while _is_tree(head, "app"):
            arg_h, arg_e = emit_expr(head.children[1], ngen)
            headers = arg_h + headers
            args.insert(0, arg_e)
            head = head.children[0]
        # `head` is now the function expression (typically a name_ref).
        head_h, head_e = emit_expr(head, ngen)
        headers = head_h + headers
        return (headers, f"{head_e}({', '.join(args)})")

    # --- conditionals ---
    if d == "if_form":
        cond = node.children[0]
        then_branch = node.children[1]
        else_branch = node.children[2]
        h1, e1 = emit_expr(cond, ngen)
        h2, e2 = emit_expr(then_branch, ngen)
        h3, e3 = emit_expr(else_branch, ngen)
        return (h1 + h2 + h3, f"({e2} if {e1} else {e3})")

    # --- fun ---
    if d == "fun_form":
        # `fun x y -> expr` -> `(lambda x, y: expr)`. Multi-arg lambdas
        # are Python's `lambda x, y: body`. Note: lambdas can't contain
        # statements, so if the body needs header lines, hoist them into
        # a named def instead.
        params_node = node.children[0]
        body = node.children[1]
        param_names = _collect_param_names(params_node)
        h, e = emit_expr(body, ngen)
        if not h:
            # Pure lambda is fine.
            return ([], f"(lambda {', '.join(param_names)}: {e})")
        # Body had header lines -- emit a named fresh def, return name.
        fname = ngen.fresh("fun")
        lines = [f"def {fname}({', '.join(param_names)}):"]
        for hl in h:
            lines.append(f"    {hl}")
        lines.append(f"    return {e}")
        return (lines, fname)

    # --- let-in ---
    if d == "let_in":
        # `let pat = e1 in e2`. Compile to an immediately-called lambda
        # so it works in expression context: `(lambda pat: e2)(e1)`.
        # For non-trivial patterns (tuple), use a fresh def.
        pat_node = node.children[0]
        rhs = node.children[1]
        body = node.children[2]
        # If pat is a simple NAME (most common), use lambda.
        if pat_node.data == "pattern_param":
            # Simple `let x = ...`
            name = _token_str(pat_node.children[0])
            h_rhs, e_rhs = emit_expr(rhs, ngen)
            h_body, e_body = emit_expr(body, ngen)
            if not h_body:
                return (h_rhs, f"(lambda {name}: {e_body})({e_rhs})")
            # Body has header lines -- need a fresh def
            fname = ngen.fresh("letin")
            lines = h_rhs + [f"def {fname}({name}):"]
            for hl in h_body:
                lines.append(f"    {hl}")
            lines.append(f"    return {e_body}")
            return (lines, f"{fname}({e_rhs})")
        if pat_node.data == "tuple_param":
            param_names = [_token_str(c) for c in pat_node.children]
            h_rhs, e_rhs = emit_expr(rhs, ngen)
            h_body, e_body = emit_expr(body, ngen)
            arglist = ", ".join(param_names)
            if not h_body:
                return (h_rhs, f"(lambda {arglist}: {e_body})(*({e_rhs}))")
            fname = ngen.fresh("letin")
            lines = h_rhs + [f"def {fname}({arglist}):"]
            for hl in h_body:
                lines.append(f"    {hl}")
            lines.append(f"    return {e_body}")
            return (lines, f"{fname}(*({e_rhs}))")
        if pat_node.data == "unit_param":
            # `let () = e1 in e2` -- evaluate e1 for side effects, discard.
            h_rhs, e_rhs = emit_expr(rhs, ngen)
            h_body, e_body = emit_expr(body, ngen)
            if not h_body:
                return (h_rhs, f"({e_rhs}, {e_body})[-1]")
            fname = ngen.fresh("letin")
            lines = h_rhs + [f"def {fname}():"]
            for hl in h_body:
                lines.append(f"    {hl}")
            lines.append(f"    return {e_body}")
            return (lines + [f"_ = {e_rhs}"], f"{fname}()")
        raise NotImplementedError(f"let-in pattern: {pat_node.data}")

    if d == "let_fun_in":
        # `let f x y = e1 in e2`. Same shape as let_rec_in but the
        # function isn't recursive at the source level. Codegen-wise
        # we emit identical Python (Python def is always visible
        # inside itself).
        name = _token_str(node.children[0])
        params_node = node.children[1]
        rhs = node.children[2]
        body = node.children[3]
        param_names = _collect_param_names(params_node)
        h_rhs, e_rhs = emit_expr(rhs, ngen)
        h_body, e_body = emit_expr(body, ngen)
        def_lines = [f"def {name}({', '.join(param_names)}):"]
        for hl in h_rhs:
            def_lines.append(f"    {hl}")
        def_lines.append(f"    return {e_rhs}")
        if not h_body:
            return (def_lines, e_body)
        body_fname = ngen.fresh("letfun_body")
        lines = def_lines + [f"def {body_fname}():"]
        for hl in h_body:
            lines.append(f"    {hl}")
        lines.append(f"    return {e_body}")
        return (lines, f"{body_fname}()")

    if d == "let_rec_in":
        # `let rec f params = e1 in e2`. Compile to a def for f, then
        # an immediately-called lambda for body.
        name = _token_str(node.children[0])
        params_node = node.children[1]
        rhs = node.children[2]
        body = node.children[3]
        param_names = _collect_param_names(params_node)
        h_rhs, e_rhs = emit_expr(rhs, ngen)
        h_body, e_body = emit_expr(body, ngen)
        # Emit def, then call lambda.
        def_lines = [f"def {name}({', '.join(param_names)}):"]
        for hl in h_rhs:
            def_lines.append(f"    {hl}")
        def_lines.append(f"    return {e_rhs}")
        if not h_body:
            return (def_lines, e_body)
        body_fname = ngen.fresh("letrec_body")
        lines = def_lines + [f"def {body_fname}():"]
        for hl in h_body:
            lines.append(f"    {hl}")
        lines.append(f"    return {e_body}")
        return (lines, f"{body_fname}()")

    # --- match ---
    if d == "match_form":
        disc = node.children[0]
        arms = node.children[1:]
        h_disc, e_disc = emit_expr(disc, ngen)
        # Always emit a helper function -- match cascades can't easily
        # collapse to a single Python expression with multi-line bindings.
        disc_var = ngen.fresh("disc")
        fname = ngen.fresh("match")
        lines = h_disc + [f"def {fname}({disc_var}):"]
        for arm in arms:
            pat = arm.children[0]
            arm_body = arm.children[1]
            cond, binds = _lower_pattern(pat, disc_var, ngen)
            h_body, e_body = emit_expr(arm_body, ngen)
            lines.append(f"    if {cond}:")
            for name, expr in binds:
                lines.append(f"        {name} = {expr}")
            for hl in h_body:
                lines.append(f"        {hl}")
            lines.append(f"        return {e_body}")
        lines.append(f"    raise _MLMatchError({disc_var})")
        return (lines, f"{fname}({e_disc})")

    raise NotImplementedError(f"emit_expr for {d}")


def _emit_binop(node, ngen, op_map):
    """Generic binary op emission. node.children is [lhs, op_tok, rhs]."""
    lhs = node.children[0]
    op_tok = node.children[1]
    rhs = node.children[2]
    h1, e1 = emit_expr(lhs, ngen)
    h2, e2 = emit_expr(rhs, ngen)
    py_op = op_map(_token_str(op_tok))
    return (h1 + h2, f"({e1} {py_op} {e2})")


def _add_op(tok):
    if tok in ("+", "+."):
        return "+"
    if tok in ("-", "-."):
        return "-"
    raise NotImplementedError(f"add op: {tok}")


def _mul_op(tok):
    if tok == "*" or tok == "*.":
        return "*"
    if tok == "/":
        return "//"      # int division for mllang's `/`
    if tok == "/.":
        return "/"       # float division for mllang's `/.`
    if tok == "mod":
        return "%"
    raise NotImplementedError(f"mul op: {tok}")


def _cmp_op(tok):
    return {
        "=": "==",
        "<>": "!=",
        "<=": "<=",
        ">=": ">=",
        "<": "<",
        ">": ">",
    }[tok]


def _collect_param_names(params_node):
    """`params` tree -> list of Python parameter names."""
    out = []
    for ch in params_node.children:
        if ch.data == "pattern_param":
            out.append(_token_str(ch.children[0]))
        elif ch.data == "tuple_param":
            # Tuple-destructured arg. Use a fresh name + emit
            # destructuring inside the body. For v1 simplicity, just
            # bind the tuple to a single fresh name and let user reference
            # it -- but this loses ergonomics. Better: name each
            # component, and the codegen of the body would need to know.
            # For now, take the tuple components' names directly; the
            # called context unpacks via `*` (we don't support this for
            # top-level def params yet; just plain names).
            raise NotImplementedError("tuple params at function top deferred")
        elif ch.data == "unit_param":
            out.append("_unit")
        elif ch.data == "wild_param":
            out.append("_")
        else:
            raise NotImplementedError(f"param kind: {ch.data}")
    return out


# ---------------------------------------------------------------------------
# Top-level item emission
# ---------------------------------------------------------------------------

def emit_top(node, ngen):
    """Emit Python statements for a top-level item.

    Returns a list of Python source lines (no leading indent; emit_top
    is always at module scope).
    """
    if node.data == "top_let_fun":
        # `let f x y = expr` -- top-level non-rec function binding.
        # Same emission as top_let_rec but without the implicit
        # self-reference (Python defs are visible in their own scope
        # regardless, so the codegen is identical; the distinction in
        # the source is purely an OCaml convention).
        name = _token_str(node.children[0])
        params_node = node.children[1]
        rhs = node.children[2]
        param_names = _collect_param_names(params_node)
        h, e = emit_expr(rhs, ngen)
        lines = [f"def {name}({', '.join(param_names)}):"]
        for hl in h:
            lines.append(f"    {hl}")
        lines.append(f"    return {e}")
        return lines

    if node.data == "top_let_val":
        pat_node = node.children[0]
        rhs = node.children[1]
        if pat_node.data == "pattern_param":
            # `let x = expr` -- simple name binding.
            name = _token_str(pat_node.children[0])
            h, e = emit_expr(rhs, ngen)
            return h + [f"{name} = {e}"]
        if pat_node.data == "tuple_param":
            names = [_token_str(c) for c in pat_node.children]
            h, e = emit_expr(rhs, ngen)
            return h + [f"({', '.join(names)},) = ({e},)" if len(names) == 1
                        else f"({', '.join(names)}) = {e}"]
        if pat_node.data == "unit_param":
            h, e = emit_expr(rhs, ngen)
            return h + [f"_ = {e}"]
        raise NotImplementedError(f"top_let_val pattern: {pat_node.data}")

    if node.data == "top_let_rec":
        name = _token_str(node.children[0])
        params_node = node.children[1]
        rhs = node.children[2]
        param_names = _collect_param_names(params_node)
        h, e = emit_expr(rhs, ngen)
        lines = [f"def {name}({', '.join(param_names)}):"]
        for hl in h:
            lines.append(f"    {hl}")
        lines.append(f"    return {e}")
        return lines

    if node.data == "top_type":
        return _emit_type_decl(node)

    if node.data == "top_expr":
        e_node = node.children[0]
        h, e = emit_expr(e_node, ngen)
        return h + [f"{e}"]

    raise NotImplementedError(f"top_item: {node.data}")


def _emit_type_decl(node):
    """Emit ADT constructor definitions.

    `type shape = Circle of int | Square of int` ->
        def Circle(payload): return _MLConstructor("Circle", payload)
        def Square(payload): return _MLConstructor("Square", payload)

    `type color = Red | Green` ->
        Red = _MLConstructor("Red", None)
        Green = _MLConstructor("Green", None)
    """
    # Children: optional type_params, NAME (type name), type_arm+ (and DSEMI)
    # Skip the type name and type_params; they're not used semantically in v1.
    arms = [ch for ch in node.children if _is_tree(ch, "type_arm")]
    lines = []
    for arm in arms:
        ctor_name = _token_str(arm.children[0])
        has_payload = len(arm.children) > 1
        if has_payload:
            lines.append(f"def {ctor_name}(payload):")
            lines.append(f"    return _MLConstructor({ctor_name!r}, payload)")
        else:
            lines.append(f"{ctor_name} = _MLConstructor({ctor_name!r}, None)")
    return lines


# ---------------------------------------------------------------------------
# Top-level entrypoint
# ---------------------------------------------------------------------------


def generate(tree):
    """Walk the Lark Tree, emit complete transpiled Python source.

    The output is a single Python file with:
      - the runtime/stdlib prelude
      - one or more Python statements for each top-level mllang item

    Returns the full source as a string.
    """
    ngen = _NameGen()
    out = [PRELUDE.rstrip() + "\n\n"]

    # Top-level: tree.data == "start", children are top_item wrappers.
    for child in tree.children:
        # top_item wraps the actual item (top_let, top_let_rec, etc.)
        if _is_tree(child, "top_item"):
            inner = child.children[0]
        else:
            inner = child
        lines = emit_top(inner, ngen)
        out.append("\n".join(lines))
        out.append("\n")

    return "".join(out)
