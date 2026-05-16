"""prologlang codegen — walk the parsed Tree, emit Python source.

Strategy: AST-walking visitor. The output is self-contained Python:
a prelude imports runtime + stdlib, then code asserts each clause
and runs each directive.

Key decisions (LOGICLANG_DESIGN.md §4):
  - `fact(term)` -> `_KB.add_clause(<term>, [])`
  - `rule(head, body)` -> `_KB.add_clause(<head>, [<g1>, ...])`
  - `directive(body)` -> `print_solutions(solve(<goals>, {}, _KB),
                          free_vars=<vars>)`
  - Each Var in a clause gets a clause-local integer id assigned at
    codegen time. Runtime renaming on top of these compile-time ids
    handles multiple uses of the same clause.

The codegen distinguishes term emission (Python expression building
a runtime Term value) from goal-list emission (the body of a clause
or directive). Operators inside arithmetic expressions stay as
nested `Compound` terms — runtime `is/2` evaluates them.
"""
from __future__ import annotations

from lark import Tree, Token


PRELUDE = '''\
# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_008.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_008.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)

'''


class _ClauseScope:
    """Per-clause variable namespace.

    Within a single clause, two occurrences of `X` refer to the same
    variable. Across clauses, an `X` is independent. This scope maps
    source variable names to integer ids, allocating a new id on first
    use and returning the cached one on subsequent uses.

    Clause-local ids stay distinct from runtime-fresh ids by living in
    the 0..99999 range; NameGen in runtime starts at 100000.
    """
    def __init__(self):
        self._next = 0
        self._names: dict[str, int] = {}

    def id_for(self, name: str) -> int:
        if name not in self._names:
            self._names[name] = self._next
            self._next += 1
        return self._names[name]

    def free_var_exprs(self) -> list[str]:
        """Python source for the list of Vars that appeared, in stable
        order. Used for directive output (`free_vars=[...]`).

        Skips synthetic anonymous vars (those starting with `_G`) — the
        user doesn't want their bindings printed.
        """
        return [
            f'Var({name!r}, {vid})'
            for name, vid in self._names.items()
            if not name.startswith("_G")
        ]


def generate(tree: Tree) -> str:
    """Walk the parsed Tree and produce Python source.

    Input is the Lark Tree produced by parser.parse(). Output is a
    string of Python — write it to a `.py` file and run it.
    """
    lines = [PRELUDE]
    # `tree` is the `start` rule: a list of `clause` children.
    for clause in tree.children:
        lines.append(_emit_clause(clause))
    return "\n".join(lines) + "\n"


def _emit_clause(clause: Tree) -> str:
    """Emit Python for one clause (fact, rule, or directive)."""
    # `clause` wraps one of: directive, rule, fact.
    inner = clause.children[0]
    if inner.data == "directive":
        return _emit_directive(inner)
    if inner.data == "rule":
        return _emit_rule(inner)
    if inner.data == "fact":
        return _emit_fact(inner)
    raise AssertionError(f"unknown clause type: {inner.data}")


def _emit_fact(node: Tree) -> str:
    """fact -> `_KB.add_clause(<head>, [])`."""
    scope = _ClauseScope()
    head_expr = _emit_term(node.children[0], scope)
    return f"_KB.add_clause({head_expr}, [])"


def _emit_rule(node: Tree) -> str:
    """rule -> `_KB.add_clause(<head>, [<body goals>])`."""
    scope = _ClauseScope()
    head_node, body_node = node.children
    head_expr = _emit_term(head_node, scope)
    goals = _flatten_body(body_node, scope)
    goals_str = "[" + ", ".join(goals) + "]"
    return f"_KB.add_clause({head_expr}, {goals_str})"


def _emit_directive(node: Tree) -> str:
    """directive -> `print_solutions(solve([<goals>], {}, _KB), free_vars=[...])`.

    Free variables in the directive are the ones whose bindings get
    printed. We track them via the scope's name dict; anonymous `_GN`
    vars are excluded.
    """
    scope = _ClauseScope()
    body_node = node.children[0]
    goals = _flatten_body(body_node, scope)
    goals_str = "[" + ", ".join(goals) + "]"
    free_vars_str = "[" + ", ".join(scope.free_var_exprs()) + "]"
    return f"print_solutions(solve({goals_str}, {{}}, _KB), free_vars={free_vars_str})"


def _flatten_body(body_node: Tree, scope: _ClauseScope) -> list[str]:
    """Flatten a body (which may have nested conjunction/disjunction/negation)
    into a flat list of Python goal expressions.

    For simple conjunction: `a, b, c` -> [`<a>`, `<b>`, `<c>`].
    For negation: `\\+ G` -> [`Compound("\\\\+", [<G>])`].
    For disjunction: `a ; b` is harder — Prolog disjunction in a body
    needs runtime support. v1 strategy (per design §4): codegen
    creates a Compound that the runtime treats as a special form?
    No — simpler: codegen lifts disjunction into a synthetic aux
    predicate.

    For v1, we'll handle disjunction by emitting a nested
    `Compound(";", [left, right])` and trust a runtime built-in to
    dispatch — see stdlib._b_disjunction (TBD). Until that's wired,
    canonical tests don't use disjunction so this branch isn't hit.
    """
    # Unwrap the wrapping `body` -> `disj_body` tree.
    inner = body_node.children[0] if body_node.data == "body" else body_node
    return _flatten_goal(inner, scope)


def _flatten_goal(node, scope: _ClauseScope) -> list[str]:
    """Recursively flatten conjunctions; emit single goals for others.

    Conjunction is the only operator that flattens to multiple goals in
    a body. Disjunction (`;`), if-then (`->`), and negation (`\\+`) each
    become a single compound goal that a runtime builtin dispatches.
    """
    if isinstance(node, Tree):
        if node.data == "conjunction":
            left, right = node.children
            return _flatten_goal(left, scope) + _flatten_goal(right, scope)
        if node.data == "disjunction":
            # `;`/2 - runtime _b_disjunction dispatches.
            # Special case: `(Cond -> Then ; Else)` parses as
            # `;(->(Cond, Then), Else)`. The disjunction builtin
            # detects the `->` left-child and handles the trinary
            # if-then-else; without the left being `->`, plain
            # disjunction semantics (try left; on failure, try right).
            left = _emit_goal_as_term(node.children[0], scope)
            right = _emit_goal_as_term(node.children[1], scope)
            return [f'Compound(";", [{left}, {right}])']
        if node.data == "ifthen":
            # `->`/2 - runtime _b_ifthen dispatches. Used standalone
            # (rare) or inside `;` for the if-then-else idiom.
            left = _emit_goal_as_term(node.children[0], scope)
            right = _emit_goal_as_term(node.children[1], scope)
            return [f'Compound("->", [{left}, {right}])']
        if node.data == "negation":
            inner = _emit_goal_as_term(node.children[0], scope)
            return [f'Compound("\\\\+", [{inner}])']
    # Anything else is a single term/goal.
    return [_emit_term(node, scope)]


def _emit_goal_as_term(node, scope: _ClauseScope) -> str:
    """Like _flatten_goal but returns a single term expression.

    Used inside disjunction/negation/if-then where we need to embed a
    conjunction as a single term. Multi-goal conjunctions become nested
    `,/2` compounds.
    """
    if isinstance(node, Tree):
        if node.data == "conjunction":
            left = _emit_goal_as_term(node.children[0], scope)
            right = _emit_goal_as_term(node.children[1], scope)
            return f'Compound(",", [{left}, {right}])'
        if node.data == "disjunction":
            left = _emit_goal_as_term(node.children[0], scope)
            right = _emit_goal_as_term(node.children[1], scope)
            return f'Compound(";", [{left}, {right}])'
        if node.data == "ifthen":
            left = _emit_goal_as_term(node.children[0], scope)
            right = _emit_goal_as_term(node.children[1], scope)
            return f'Compound("->", [{left}, {right}])'
        if node.data == "negation":
            inner = _emit_goal_as_term(node.children[0], scope)
            return f'Compound("\\\\+", [{inner}])'
    return _emit_term(node, scope)


def _emit_term(node, scope: _ClauseScope) -> str:
    """Emit Python source that builds a runtime Term value.

    Cases:
      - num_lit         -> Num(value)
      - var_ref         -> Var("X", id)
      - atom_or_compound -> Atom("foo") or Compound("foo", [...])
      - quoted_atom_or_compound -> Atom("Hello, World!") or compound
      - list forms      -> NIL / make_list / make_partial_list
      - is_op           -> Compound("is", [lhs, rhs])
      - binop / unary_minus / pow / etc. -> Compound("op", [args])
    """
    if isinstance(node, Token):
        # Bare tokens shouldn't typically reach here — they're wrapped
        # in atom_or_compound / var_ref / num_lit nodes. Defensive.
        if node.type == "NUMBER":
            return _emit_number_token(node)
        if node.type == "VARIABLE":
            return _emit_var_token(node, scope)
        if node.type in ("ATOM_NAME", "QUOTED_ATOM"):
            return f'Atom({_atom_name_repr(node)!r})'
        raise AssertionError(f"unexpected bare Token: {node!r}")

    if node.data == "num_lit":
        return _emit_number_token(node.children[0])

    if node.data == "var_ref":
        return _emit_var_token(node.children[0], scope)

    if node.data == "atom_or_compound":
        name_tok = node.children[0]
        atom_name = str(name_tok)
        if len(node.children) == 1:
            # Bare atom: `foo`.
            return f'Atom({atom_name!r})'
        # Compound: `foo(arg1, arg2, ...)`.
        args_node = node.children[1]
        arg_exprs = [_emit_term(a, scope) for a in _arg_terms(args_node)]
        return f'Compound({atom_name!r}, [{", ".join(arg_exprs)}])'

    if node.data == "quoted_atom_or_compound":
        name_tok = node.children[0]
        # Strip surrounding quotes and process escapes.
        raw = str(name_tok)
        atom_name = _unquote_atom(raw)
        if len(node.children) == 1:
            return f'Atom({atom_name!r})'
        args_node = node.children[1]
        arg_exprs = [_emit_term(a, scope) for a in _arg_terms(args_node)]
        return f'Compound({atom_name!r}, [{", ".join(arg_exprs)}])'

    if node.data == "nil_list":
        return "NIL"

    if node.data == "proper_list":
        elem_exprs = [_emit_term(c, scope) for c in node.children]
        return f'make_list([{", ".join(elem_exprs)}])'

    if node.data == "partial_list":
        # children: [elem1, elem2, ..., tail]
        *elems, tail = node.children
        elem_exprs = [_emit_term(e, scope) for e in elems]
        tail_expr = _emit_term(tail, scope)
        return f'make_partial_list([{", ".join(elem_exprs)}], {tail_expr})'

    if node.data == "binop":
        left, op_tok, right = node.children
        op = str(op_tok)
        l_expr = _emit_term(left, scope)
        r_expr = _emit_term(right, scope)
        return f'Compound({op!r}, [{l_expr}, {r_expr}])'

    if node.data == "is_op":
        left, right = node.children
        l_expr = _emit_term(left, scope)
        r_expr = _emit_term(right, scope)
        return f'Compound("is", [{l_expr}, {r_expr}])'

    if node.data == "unary_minus":
        # Fold `-NUM` into a negative Num literal at codegen time so
        # `write/1` prints `-1` rather than `-(1)` (which would result
        # from emitting Compound("-", [Num(1)])). Real Prolog's negative
        # literals work this way: -1 is a Num, not unary-minus(1).
        child = node.children[0]
        if isinstance(child, Tree) and child.data == "num_lit":
            tok = child.children[0]
            s = str(tok)
            if "." in s:
                return f"Num({-float(s)!r})"
            return f"Num({-int(s)})"
        # Otherwise (unary minus over an expression like `-X`), emit as
        # compound for arithmetic evaluation. `is/2` will dispatch the
        # unary `-/1` arithmetic operator.
        inner = _emit_term(child, scope)
        return f'Compound("-", [{inner}])'

    # Body operators (`,`, `;`, `->`, `\+`) parsed inside `(...)` show
    # up here as either a `body` wrapper or directly as the operator
    # tree. Used for the if-then-else idiom `(Cond -> Then ; Else)`
    # inside another goal's arg position. Re-dispatch to the goal-as-term
    # emitter so the operators become Compound goals.
    if node.data == "body":
        # `body` wraps a single child (the disj_body / conj_body / etc.)
        return _emit_goal_as_term(node.children[0], scope)
    if node.data in ("disjunction", "conjunction", "ifthen", "negation"):
        return _emit_goal_as_term(node, scope)

    raise AssertionError(f"unhandled term node: {node.data}")


def _arg_terms(args_node):
    """Pull the actual term children out of an `args` / `arg_list` tree."""
    # `args` wraps `arg_list`; `arg_list` has term children directly.
    if args_node.data == "args":
        inner = args_node.children[0]
        return inner.children
    if args_node.data == "arg_list":
        return args_node.children
    return [args_node]


def _emit_number_token(tok: Token) -> str:
    """Emit a Num(...) call for a NUMBER token."""
    s = str(tok)
    if "." in s:
        return f"Num({float(s)!r})"
    return f"Num({int(s)})"


def _emit_var_token(tok: Token, scope: _ClauseScope) -> str:
    """Emit a Var("name", id) call. The id is per-clause-scope; runtime
    rename ensures multiple uses of the same clause get fresh ids on
    top of these compile-time ids."""
    name = str(tok)
    vid = scope.id_for(name)
    return f'Var({name!r}, {vid})'


def _unquote_atom(raw: str) -> str:
    """Strip the surrounding single-quotes from a quoted atom and
    process `\\` escapes."""
    # raw includes the surrounding quotes: 'Hello, World!'
    inner = raw[1:-1]
    out = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            if nxt == "n":   out.append("\n")
            elif nxt == "t": out.append("\t")
            elif nxt == "\\": out.append("\\")
            elif nxt == "'": out.append("'")
            elif nxt == '"': out.append('"')
            else:
                out.append(nxt)  # unknown escape: keep raw char
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _atom_name_repr(tok: Token) -> str:
    """Return the source-level string name of an atom token (for ATOM_NAME
    or QUOTED_ATOM). Quoted atoms get unquoted."""
    s = str(tok)
    if tok.type == "QUOTED_ATOM":
        return _unquote_atom(s)
    return s
