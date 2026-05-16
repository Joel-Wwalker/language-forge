"""prologlang stdlib — built-in predicates registered into a KnowledgeBase.

Each built-in is a generator function with the signature:

    impl(args: list, rest: list, subs: dict, kb: KnowledgeBase)
        -> Generator[dict, None, None]

  - `args` are the goal's arguments (walked-once at call time may be
    needed; impls walk again locally as appropriate).
  - `rest` are the subsequent goals in the current resolution; the
    impl yields successful subs to `solve(rest, subs, kb)` so the rest
    of the body proceeds under each binding.
  - `subs` is the current substitution.
  - `kb` is the knowledge base, passed through so impls can call
    `solve` recursively (used by `\\+/1`, `once/1`, `findall/3`).

Built-ins that have side effects (`write/1`, `nl/0`) yield exactly
once with `subs` unchanged. Built-ins that are deterministic on their
inputs yield at most once. Non-deterministic ones (`member/2`,
`append/3` in some modes) yield multiple times.

See LOGICLANG_DESIGN.md §3 builtins and §10 open questions for which
predicates are in v1 and which are deferred.
"""
from __future__ import annotations

from .runtime import (
    Var, Atom, Num, Compound, NIL,
    walk, walk_deep, unify, solve,
    make_list, term_to_string, write_term, write_nl,
)


# ---------------------------------------------------------------------------
# Arithmetic evaluation — used by is/2 and the comparison operators
# ---------------------------------------------------------------------------


class ArithError(Exception):
    """Raised when an arithmetic expression contains an unbound var or
    a non-evaluable term. Surfaces as a runtime error in the compiled
    program (rather than silently failing) so users see why their
    `is/2` call didn't bind."""


def _eval_arith(term, subs: dict):
    """Recursively evaluate an arithmetic expression term to a Python number.

    Supported operators: + - * / // mod, unary -, abs/1. Operands must
    resolve to fully-ground Num terms; an unbound Var raises ArithError.
    """
    term = walk(term, subs)
    if isinstance(term, Num):
        return term.value
    if isinstance(term, Var):
        raise ArithError(f"unbound variable in arithmetic expression: {term.name}")
    if isinstance(term, Atom):
        # Some atoms are arithmetic constants (e.g. `pi`, `e`). v1 doesn't
        # ship any but the dispatch is here for forward-compat.
        raise ArithError(f"atom {term.name} is not an arithmetic value")
    if isinstance(term, Compound):
        if term.functor == "-" and len(term.args) == 1:  # unary minus
            return -_eval_arith(term.args[0], subs)
        if term.functor == "abs" and len(term.args) == 1:
            return abs(_eval_arith(term.args[0], subs))
        if len(term.args) == 2:
            a = _eval_arith(term.args[0], subs)
            b = _eval_arith(term.args[1], subs)
            op = term.functor
            if op == "+":   return a + b
            if op == "-":   return a - b
            if op == "*":   return a * b
            if op == "/":
                # Prolog `/` is float division when either operand is
                # float, else integer division returning a float? Real
                # Prolog rules are dialect-dependent. v1: Python `/`
                # semantics. Use `//` for explicit integer divide.
                return a / b
            if op == "//":  return a // b
            if op == "mod": return a % b
            if op == "**":  return a ** b
        raise ArithError(f"unknown arithmetic operator: {term.functor}/{len(term.args)}")
    raise ArithError(f"non-evaluable term in arithmetic: {term!r}")


# ---------------------------------------------------------------------------
# Built-ins: equality / unification family
# ---------------------------------------------------------------------------


def _b_unify(args, rest, subs, kb):
    """=/2 — unify two terms. Standard Prolog `=`."""
    a, b = args
    new_subs = unify(a, b, subs)
    if new_subs is not None:
        yield from solve(rest, new_subs, kb)


def _b_not_unify(args, rest, subs, kb):
    """\\=/2 — succeed iff the two terms do NOT unify (and don't bind)."""
    a, b = args
    if unify(a, b, subs) is None:
        yield from solve(rest, subs, kb)


def _b_strict_eq(args, rest, subs, kb):
    """==/2 — succeed iff the two terms are structurally equal AFTER
    walking, without performing any new unification."""
    a, b = args
    a_resolved = walk_deep(a, subs)
    b_resolved = walk_deep(b, subs)
    if _structural_eq(a_resolved, b_resolved):
        yield from solve(rest, subs, kb)


def _b_strict_neq(args, rest, subs, kb):
    """\\==/2 — succeed iff structurally NOT equal."""
    a, b = args
    a_resolved = walk_deep(a, subs)
    b_resolved = walk_deep(b, subs)
    if not _structural_eq(a_resolved, b_resolved):
        yield from solve(rest, subs, kb)


def _structural_eq(a, b) -> bool:
    """Structural equality (used by ==/2 / \\==/2).

    Unlike unification, this does NOT bind unbound variables; two
    unbound vars are equal only if they have the same id.
    """
    if isinstance(a, Var) and isinstance(b, Var):
        return a.id == b.id
    if isinstance(a, Var) or isinstance(b, Var):
        return False
    if isinstance(a, Atom) and isinstance(b, Atom):
        return a.name == b.name
    if isinstance(a, Num) and isinstance(b, Num):
        return a.value == b.value
    if isinstance(a, Compound) and isinstance(b, Compound):
        return (a.functor == b.functor
                and len(a.args) == len(b.args)
                and all(_structural_eq(x, y) for x, y in zip(a.args, b.args)))
    return False


# ---------------------------------------------------------------------------
# Built-ins: arithmetic evaluation
# ---------------------------------------------------------------------------


def _b_is(args, rest, subs, kb):
    """is/2 — evaluate RHS, unify with LHS.

    `X is 2 + 3` evaluates `2 + 3` to `5` and unifies `X` with `5`.
    LHS can be an unbound Var (gets bound) or a Num (must match).
    """
    lhs, rhs = args
    try:
        value = _eval_arith(rhs, subs)
    except ArithError:
        return  # silent fail on bad arithmetic; matches Prolog default
    result_term = Num(value)
    new_subs = unify(lhs, result_term, subs)
    if new_subs is not None:
        yield from solve(rest, new_subs, kb)


def _make_arith_cmp(py_op):
    """Build a numeric-comparison built-in: =:=, =\\=, <, >, =<, >=.

    Each takes two arith expressions, evaluates both, and succeeds iff
    `py_op(a, b)` holds. No unification side effects.
    """
    def _b(args, rest, subs, kb):
        a_expr, b_expr = args
        try:
            a = _eval_arith(a_expr, subs)
            b = _eval_arith(b_expr, subs)
        except ArithError:
            return
        if py_op(a, b):
            yield from solve(rest, subs, kb)
    return _b


# ---------------------------------------------------------------------------
# Built-ins: I/O (write + nl)
# ---------------------------------------------------------------------------


def _b_write(args, rest, subs, kb):
    """write/1 — print the term in canonical form, no newline."""
    write_term(args[0], subs)
    yield from solve(rest, subs, kb)


def _b_nl(args, rest, subs, kb):
    """nl/0 — print a newline."""
    write_nl()
    yield from solve(rest, subs, kb)


# ---------------------------------------------------------------------------
# Built-ins: lists
# ---------------------------------------------------------------------------


def _b_length(args, rest, subs, kb):
    """length/2 — `length(List, N)` binds N to the length of List.

    v1 supports the (+List, ?Int) mode: given a fully-ground list,
    compute its length. The (+Int, ?List) mode (generating a list of
    fresh vars of given length) is also supported.
    """
    lst, n = args
    lst = walk(lst, subs)
    n = walk(n, subs)

    # Mode 1: list is ground (or partial-ground) — walk it, count.
    if (isinstance(lst, Compound) and lst.functor == ".") or \
       (isinstance(lst, Atom) and lst.name == "[]"):
        count = 0
        current = lst
        while isinstance(current, Compound) and current.functor == "." and len(current.args) == 2:
            count += 1
            current = walk(current.args[1], subs)
        if isinstance(current, Atom) and current.name == "[]":
            new_subs = unify(n, Num(count), subs)
            if new_subs is not None:
                yield from solve(rest, new_subs, kb)
        # Partial list (tail is a Var): v1 doesn't handle "generate
        # length up to the tail" mode; treat as fail.
        return

    # Mode 2: n is a ground integer — generate a list of N fresh vars.
    if isinstance(n, Num) and isinstance(n.value, int) and n.value >= 0:
        fresh_vars = [Var("_L", kb.name_gen.fresh()) for _ in range(n.value)]
        new_subs = unify(lst, make_list(fresh_vars), subs)
        if new_subs is not None:
            yield from solve(rest, new_subs, kb)
        return
    # Both unbound: v1 doesn't enumerate all lengths.
    return


def _b_append(args, rest, subs, kb):
    """append/3 — `append(L1, L2, L3)`. Non-deterministic in general;
    v1 supports any combination of input modes that terminate naturally.

    Implementation: recursive Prolog-style. Two clauses, applied via
    in-runtime backtracking:
        append([], L, L).
        append([H|T], L, [H|R]) :- append(T, L, R).
    """
    l1, l2, l3 = args
    # Clause 1: append([], L, L).
    s1 = unify(l1, NIL, subs)
    if s1 is not None:
        s2 = unify(l2, l3, s1)
        if s2 is not None:
            yield from solve(rest, s2, kb)
    # Clause 2: append([H|T], L, [H|R]) :- append(T, L, R).
    h = Var("_H", kb.name_gen.fresh())
    t = Var("_T", kb.name_gen.fresh())
    r = Var("_R", kb.name_gen.fresh())
    cons_l1 = Compound(".", [h, t])
    cons_l3 = Compound(".", [h, r])
    s1 = unify(l1, cons_l1, subs)
    if s1 is None:
        return
    s2 = unify(l3, cons_l3, s1)
    if s2 is None:
        return
    recursive_goal = Compound("append", [t, l2, r])
    yield from solve([recursive_goal] + rest, s2, kb)


def _b_member(args, rest, subs, kb):
    """member/2 — `member(Elem, List)` succeeds once per occurrence.

    Non-deterministic: yields each successful binding as backtracking
    advances. On a list `[1, 2, 3]`, `member(X, [1, 2, 3])` yields
    X = 1, X = 2, X = 3 in turn.
    """
    elem, lst = args
    current = walk(lst, subs)
    while isinstance(current, Compound) and current.functor == "." and len(current.args) == 2:
        head, tail = current.args
        new_subs = unify(elem, head, subs)
        if new_subs is not None:
            yield from solve(rest, new_subs, kb)
        current = walk(tail, subs)
    # `current` is `[]` or unbound — stop yielding.


def _b_reverse(args, rest, subs, kb):
    """reverse/2 — `reverse(List, R)`. v1 only supports +List mode."""
    lst, r = args
    current = walk(lst, subs)
    elements = []
    while isinstance(current, Compound) and current.functor == "." and len(current.args) == 2:
        elements.append(current.args[0])
        current = walk(current.args[1], subs)
    if not (isinstance(current, Atom) and current.name == "[]"):
        return  # partial / non-list; fail
    reversed_term = make_list(list(reversed(elements)))
    new_subs = unify(r, reversed_term, subs)
    if new_subs is not None:
        yield from solve(rest, new_subs, kb)


# ---------------------------------------------------------------------------
# Built-ins: type tests
# ---------------------------------------------------------------------------


def _b_atom(args, rest, subs, kb):
    """atom/1 — succeed iff the argument is an Atom (after walking)."""
    t = walk(args[0], subs)
    if isinstance(t, Atom):
        yield from solve(rest, subs, kb)


def _b_number(args, rest, subs, kb):
    """number/1 — succeed iff the argument is a Num."""
    t = walk(args[0], subs)
    if isinstance(t, Num):
        yield from solve(rest, subs, kb)


def _b_integer(args, rest, subs, kb):
    """integer/1 — succeed iff the argument is an integer Num."""
    t = walk(args[0], subs)
    if isinstance(t, Num) and isinstance(t.value, int) and not isinstance(t.value, bool):
        yield from solve(rest, subs, kb)


def _b_var(args, rest, subs, kb):
    """var/1 — succeed iff the argument is an unbound Var."""
    t = walk(args[0], subs)
    if isinstance(t, Var):
        yield from solve(rest, subs, kb)


def _b_nonvar(args, rest, subs, kb):
    """nonvar/1 — succeed iff the argument is bound (not a Var)."""
    t = walk(args[0], subs)
    if not isinstance(t, Var):
        yield from solve(rest, subs, kb)


def _b_is_list(args, rest, subs, kb):
    """is_list/1 — succeed iff the argument is a proper list (ends in [])."""
    t = walk(args[0], subs)
    while isinstance(t, Compound) and t.functor == "." and len(t.args) == 2:
        t = walk(t.args[1], subs)
    if isinstance(t, Atom) and t.name == "[]":
        yield from solve(rest, subs, kb)


# ---------------------------------------------------------------------------
# Built-ins: control
# ---------------------------------------------------------------------------


def _b_true(args, rest, subs, kb):
    """true/0 — always succeeds."""
    yield from solve(rest, subs, kb)


def _b_fail(args, rest, subs, kb):
    """fail/0 — always fails."""
    return
    yield  # unreachable, but keeps this a generator


def _b_once(args, rest, subs, kb):
    """once/1 — succeed at most once for the inner Goal.

    Commits to the first solution of `Goal` and discards alternatives.
    Used in lieu of cut for "I only want one answer" cases.
    """
    inner = args[0]
    for s in solve([inner], subs, kb):
        yield from solve(rest, s, kb)
        return  # commit


def _b_negation(args, rest, subs, kb):
    """\\+/1 — negation as failure. Succeed iff Goal cannot be proven."""
    inner = args[0]
    for _ in solve([inner], subs, kb):
        return  # at least one solution: \+ fails
    # No solutions: \+ succeeds, current subs unchanged
    yield from solve(rest, subs, kb)


def _b_conjunction(args, rest, subs, kb):
    """,/2 — conjunction as a single compound term.

    Codegen flattens conjunctions in clause bodies into a Python list of
    goals (handled directly by solve), so this builtin only fires when
    `,` appears nested inside another operator (e.g. inside a `->` or
    `;` arm). Treat it as solving both subgoals in sequence.
    """
    left, right = args
    yield from solve([left, right] + rest, subs, kb)


def _b_disjunction(args, rest, subs, kb):
    """;/2 — disjunction. Standard Prolog: try left; on failure, try right.

    Standard if-then-else shape: `(Cond -> Then ; Else)`. Parses as
    `;(->(Cond, Then), Else)`. Detect the `->` left-child and dispatch
    accordingly: solve Cond; if it succeeds, commit and solve Then (no
    backtracking into Else); if Cond fails, solve Else.

    Without the `->` left-child, behaves as plain disjunction: yield
    solutions from left, then from right.
    """
    left, right = args
    # If-then-else detection: walk the left term (it may be Compound)
    # and check for `->` shape.
    if isinstance(left, Compound) and left.functor == "->" and len(left.args) == 2:
        cond, then = left.args
        # Try Cond. If it succeeds at least once, commit to Then and
        # ignore Else. If it fails on all alternatives, run Else.
        cond_solved = False
        for cond_subs in solve([cond], subs, kb):
            cond_solved = True
            yield from solve([then] + rest, cond_subs, kb)
            return  # commit: don't try Else even if Then fails
        if not cond_solved:
            yield from solve([right] + rest, subs, kb)
        return

    # Plain disjunction: yield from each branch.
    yield from solve([left] + rest, subs, kb)
    yield from solve([right] + rest, subs, kb)


def _b_ifthen(args, rest, subs, kb):
    """->/2 — if-then WITHOUT an else branch.

    Standalone `(Cond -> Then)` (no `;` after) succeeds iff Cond succeeds
    AND Then succeeds. If Cond fails, the whole thing fails (no Else
    fallback). Rare standalone; usually appears inside `;` as if-then-else.
    """
    cond, then = args
    for cond_subs in solve([cond], subs, kb):
        yield from solve([then] + rest, cond_subs, kb)
        return  # commit to first Cond solution


def _b_call_1(args, rest, subs, kb):
    """call/1 — invoke a goal term. `call(member(X, [1,2,3]))` ≡ `member(X, [1,2,3])`."""
    inner = walk(args[0], subs)
    yield from solve([inner] + rest, subs, kb)


def _b_call_2(args, rest, subs, kb):
    """call/2 — `call(Goal, X)` constructs a new goal by appending X
    to Goal's arg list, then solves it.

    Example: `call(add(5), 3)` becomes `add(5, 3)`. This is how
    closures-via-partial-application work in v1 (see LOGICLANG_DESIGN.md
    §6 closures.lgc).
    """
    goal_term, extra = args
    new_goal = _append_args_to_goal(walk(goal_term, subs), [extra])
    if new_goal is None:
        return
    yield from solve([new_goal] + rest, subs, kb)


def _b_call_3(args, rest, subs, kb):
    """call/3 — same as call/2 but with two extra args."""
    goal_term, e1, e2 = args
    new_goal = _append_args_to_goal(walk(goal_term, subs), [e1, e2])
    if new_goal is None:
        return
    yield from solve([new_goal] + rest, subs, kb)


def _append_args_to_goal(goal, extras: list):
    """Combine a partial goal with extra args into a full goal.

    `add(5)` + `[3]` -> `add(5, 3)`
    `add` (atom) + `[5, 3]` -> `add(5, 3)`
    Returns None on bad shapes (e.g. number used as goal).
    """
    if isinstance(goal, Atom):
        return Compound(goal.name, list(extras))
    if isinstance(goal, Compound):
        return Compound(goal.functor, list(goal.args) + list(extras))
    return None


def _b_findall(args, rest, subs, kb):
    """findall/3 — `findall(Template, Goal, List)` collects all `Template`
    instantiations across every solution of `Goal` into `List`.

    Standard Prolog semantics: produces `[]` if Goal has no solutions
    (does NOT fail). Variable scoping is by binding-at-solve time.
    """
    template, goal, result_list = args
    collected = []
    for s in solve([goal], subs, kb):
        # Walk the template under each solution's subs.
        collected.append(_freeze_term(template, s, kb))
    result_term = make_list(collected)
    new_subs = unify(result_list, result_term, subs)
    if new_subs is not None:
        yield from solve(rest, new_subs, kb)


def _freeze_term(term, subs, kb):
    """Walk a term deeply and replace any remaining unbound vars with
    fresh vars (so the result is independent of `subs` and safe to
    embed in a collected list).

    Used by findall/3 — without freezing, a later substitution could
    "mutate" already-collected results because Vars share ids.
    """
    term = walk(term, subs)
    if isinstance(term, Var):
        # Unbound var in a finalized result: rename to a fresh id so it
        # doesn't accidentally unify with future bindings.
        return Var(term.name, kb.name_gen.fresh())
    if isinstance(term, Compound):
        return Compound(term.functor, [_freeze_term(a, subs, kb) for a in term.args])
    return term


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_builtins(kb) -> None:
    """Register the v1 built-in predicate set into a KnowledgeBase."""
    # Unification / equality
    kb.register_builtin("=",  2, _b_unify)
    kb.register_builtin("\\=", 2, _b_not_unify)
    kb.register_builtin("==", 2, _b_strict_eq)
    kb.register_builtin("\\==", 2, _b_strict_neq)

    # Arithmetic
    kb.register_builtin("is", 2, _b_is)
    kb.register_builtin("=:=", 2, _make_arith_cmp(lambda a, b: a == b))
    kb.register_builtin("=\\=", 2, _make_arith_cmp(lambda a, b: a != b))
    kb.register_builtin("<",  2, _make_arith_cmp(lambda a, b: a < b))
    kb.register_builtin(">",  2, _make_arith_cmp(lambda a, b: a > b))
    kb.register_builtin("=<", 2, _make_arith_cmp(lambda a, b: a <= b))
    kb.register_builtin(">=", 2, _make_arith_cmp(lambda a, b: a >= b))

    # I/O
    kb.register_builtin("write", 1, _b_write)
    kb.register_builtin("nl", 0, _b_nl)

    # Lists
    kb.register_builtin("length", 2, _b_length)
    kb.register_builtin("append", 3, _b_append)
    kb.register_builtin("member", 2, _b_member)
    kb.register_builtin("reverse", 2, _b_reverse)

    # Type tests
    kb.register_builtin("atom",    1, _b_atom)
    kb.register_builtin("number",  1, _b_number)
    kb.register_builtin("integer", 1, _b_integer)
    kb.register_builtin("var",     1, _b_var)
    kb.register_builtin("nonvar",  1, _b_nonvar)
    kb.register_builtin("is_list", 1, _b_is_list)

    # Control
    kb.register_builtin("true",  0, _b_true)
    kb.register_builtin("fail",  0, _b_fail)
    kb.register_builtin("once",  1, _b_once)
    kb.register_builtin("\\+",   1, _b_negation)
    kb.register_builtin("call",  1, _b_call_1)
    kb.register_builtin("call",  2, _b_call_2)
    kb.register_builtin("call",  3, _b_call_3)
    # Body operators that appear as goal compounds (when a body
    # operator is nested inside another, codegen emits them as
    # Compound terms rather than as direct list-of-goals). The
    # builtins below dispatch them so `(Cond -> Then ; Else)` and
    # similar nested forms execute correctly.
    kb.register_builtin(",",  2, _b_conjunction)
    kb.register_builtin(";",  2, _b_disjunction)
    kb.register_builtin("->", 2, _b_ifthen)

    # Meta
    kb.register_builtin("findall", 3, _b_findall)
