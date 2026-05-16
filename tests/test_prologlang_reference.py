"""Tests for the hand-written prologlang reference compiler.

prologlang is the fifth syntax-family reference, parallel to:
  - toylang (c_like)
  - lisplang (s_expression)
  - forthlang (stack_based)
  - mllang (ml_like)

The family is `logic_like` (pragmatic Prolog subset; facts, rules,
queries, DFS with backtracking, no cut). See `LOGICLANG_DESIGN.md`
in the workspace root for the surface-language design + the
unification + resolution implementation.

These tests pin the Stage B acceptance gate from
logic-family-experiment-instructions.md: all canonical tests must
pass on the hand-written reference, standalone, before any
registration with the generator pipeline. They also pin specific
behaviours the design doc called out: compound-term unification,
backtracking through alternatives, list pattern matching with
`[H|T]`, and the `is/2` arithmetic boundary (Prolog's `=` is
unification, `is` is evaluation).
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
PROLOGLANG_DIR = WORKSPACE_ROOT / "generated" / "prologlang"


def _ensure_generated_on_path():
    p = str(WORKSPACE_ROOT / "generated")
    if p not in sys.path:
        sys.path.insert(0, p)


def _run_prolog(src: str) -> str:
    """Helper: compile + exec a prologlang source string, return stdout."""
    _ensure_generated_on_path()
    from prologlang.parser import parse
    from prologlang.codegen import generate
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Reference compiler file presence
# ---------------------------------------------------------------------------


def test_prologlang_reference_exists():
    """The reference compiler must ship all the files the template-from-
    reference path expects."""
    assert PROLOGLANG_DIR.exists(), "prologlang reference compiler is missing"
    for f in ("__init__.py", "parser.py", "codegen.py", "runtime.py",
              "stdlib.py", "compile.py", "resolved_spec.json", "theme.css"):
        assert (PROLOGLANG_DIR / f).exists(), f"prologlang/{f} missing"
    assert (PROLOGLANG_DIR / "tests").is_dir()


def test_prologlang_canonical_test_files_exist():
    """All canonical tests + their expected outputs must be on disk."""
    canonical = [
        "hello_world", "arithmetic", "variables", "conditionals",
        "loops", "functions", "recursion", "closures", "strings",
    ]
    for name in canonical:
        src = PROLOGLANG_DIR / "tests" / f"{name}.lgc"
        exp = PROLOGLANG_DIR / "tests" / f"{name}.expected_output.txt"
        assert src.exists(), f"missing tests/{name}.lgc"
        assert exp.exists(), f"missing tests/{name}.expected_output.txt"


# ---------------------------------------------------------------------------
# Canonical tests must all pass on the reference
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("test_name", [
    "hello_world", "arithmetic", "variables", "conditionals",
    "loops", "functions", "recursion", "closures", "strings",
])
def test_prologlang_canonical_test_runs(test_name):
    """Each canonical test compiles + runs + matches expected output.

    The Stage B acceptance gate: all canonical pass on the hand-
    written reference, standalone, before any integration. prologlang
    ships 9 canonical tests (the 8 cross-family standards plus
    `recursion.lgc` exercising factorial as a Prolog-idiomatic
    recursive predicate).
    """
    src = (PROLOGLANG_DIR / "tests" / f"{test_name}.lgc").read_text(encoding="utf-8")
    expected = (PROLOGLANG_DIR / "tests" / f"{test_name}.expected_output.txt").read_text(encoding="utf-8")
    actual = _run_prolog(src)
    assert actual == expected, (
        f"output mismatch for {test_name}.lgc\n"
        f"expected: {expected!r}\n"
        f"actual:   {actual!r}"
    )


# ---------------------------------------------------------------------------
# Unification behaviour — the heart of the runtime
# ---------------------------------------------------------------------------


def test_unify_compound_terms_with_shared_variable():
    """`p(X, X)` unifies with `p(a, a)` but not with `p(a, b)`.

    The shared variable `X` constrains both args to the same value.
    The first directive succeeds and writes 'matched'; the second
    fails silently and writes nothing.
    """
    src = """
    p(X, X) :- write(matched), nl.
    :- p(a, a).
    :- p(a, b).
    """
    assert _run_prolog(src) == "matched\n"


def test_unify_nested_compound_terms():
    """Compound terms unify structurally - functor + arity + args.

    `foo(bar(X), Y)` unifies with `foo(bar(1), 2)` binding X=1, Y=2.
    """
    src = """
    test(foo(bar(X), Y)) :- write(X), nl, write(Y), nl.
    :- test(foo(bar(1), 2)).
    """
    assert _run_prolog(src) == "1\n2\n"


def test_unify_lists_with_head_tail_pattern():
    """`[H | T]` pattern unifies with a non-empty list, binding H to
    the first element and T to the rest. Per design doc §1 list
    representation as cons cells."""
    src = """
    first(L, H) :- L = [H | _].
    rest(L, T) :- L = [_ | T].
    :- first([1, 2, 3], X), write(X), nl.
    :- rest([1, 2, 3], X), write(X), nl.
    """
    assert _run_prolog(src) == "1\n[2, 3]\n"


def test_unify_with_anonymous_underscore_doesnt_propagate():
    """Two `_`s in the same clause are independent variables.

    `pair(_, _)` matches any 2-arg compound; the two `_`s don't
    constrain each other. Per design doc §1 anonymous variables.
    """
    src = """
    pair(_, _) :- write(ok), nl.
    :- pair(1, 2).
    :- pair(a, b).
    """
    assert _run_prolog(src) == "ok\nok\n"


# ---------------------------------------------------------------------------
# Backtracking through alternatives
# ---------------------------------------------------------------------------


def test_backtracking_member_yields_all_solutions():
    """`member/2` is non-deterministic - on backtracking it yields
    each list element in turn. Using findall to materialize all
    solutions confirms the backtracking machinery works.
    """
    src = """
    :- findall(X, member(X, [a, b, c]), L), write(L), nl.
    """
    assert _run_prolog(src) == "[a, b, c]\n"


def test_backtracking_through_multi_clause_predicate():
    """A predicate with multiple matching clauses tries each in order.

    `color/1` has three clauses; findall collects all matches.
    """
    src = """
    color(red).
    color(green).
    color(blue).
    :- findall(C, color(C), L), write(L), nl.
    """
    assert _run_prolog(src) == "[red, green, blue]\n"


def test_backtracking_finds_first_solution_then_stops_in_directive():
    """A `:-` directive consumes only the first solution. Even though
    `member` could backtrack, the directive runs once.

    Verifies the run-once semantics from runtime.print_solutions.
    """
    src = """
    :- member(X, [first, second, third]), write(X), nl.
    """
    assert _run_prolog(src) == "first\n"


def test_backtracking_recursive_append_in_split_mode():
    """`append(L1, L2, [1,2,3])` enumerates all splits. The first
    yields L1=[], L2=[1,2,3]; subsequent backtracks enumerate
    further splits."""
    src = """
    :- findall(L1-L2, append(L1, L2, [1,2,3]), Splits), write(Splits), nl.
    """
    out = _run_prolog(src)
    # 4 splits: []-[1,2,3], [1]-[2,3], [1,2]-[3], [1,2,3]-[]
    assert out.strip().count("-") == 4


# ---------------------------------------------------------------------------
# `is/2` arithmetic boundary vs `=/2` unification
# ---------------------------------------------------------------------------


def test_is_evaluates_rhs_then_unifies():
    """`X is 2 + 3` evaluates the RHS to 5 then binds X to 5.

    The arithmetic boundary: `is` evaluates; `=` unifies syntactically.
    """
    src = """
    :- X is 2 + 3, write(X), nl.
    """
    assert _run_prolog(src) == "5\n"


def test_eq_is_unification_not_evaluation():
    """`X = 2 + 3` unifies X with the COMPOUND `2 + 3`, it does not
    evaluate. The output is `+(2, 3)` not `5`.

    This is the classic Prolog gotcha the canonical tests' arithmetic
    boundary specifically pins down.
    """
    src = """
    :- X = 2 + 3, write(X), nl.
    """
    # The compound term `+(2, 3)` prints in canonical form as `+(2, 3)`.
    # (Some Prologs render with operator syntax `2+3`; v1's term_to_string
    # uses functor-form.)
    assert _run_prolog(src) == "+(2, 3)\n"


def test_is_with_unbound_rhs_silently_fails():
    """`X is Y + 1` with Y unbound is a runtime error in real Prolog;
    v1 chose to silently fail (ArithError caught in _b_is). The
    directive prints nothing.
    """
    src = """
    :- X is Y + 1, write(X), nl.
    :- write(reached_after), nl.
    """
    assert _run_prolog(src) == "reached_after\n"


def test_arith_comparison_evaluates_both_sides():
    """`=:=` evaluates both sides and compares numerically.
    `2 + 3 =:= 5` succeeds; `2 + 3 =:= 6` fails."""
    src = """
    :- (2 + 3 =:= 5 -> write(eq) ; write(neq)), nl.
    """
    # No if-then-else built-in yet; emit two clauses instead.
    src = """
    test_5 :- 2 + 3 =:= 5, write(yes_5), nl.
    test_6 :- 2 + 3 =:= 6, write(yes_6), nl.
    :- test_5.
    :- test_6.
    """
    assert _run_prolog(src) == "yes_5\n"


# ---------------------------------------------------------------------------
# Call/N - closures via partial application
# ---------------------------------------------------------------------------


def test_call_2_appends_one_arg():
    """`call(add(5), 3)` builds the goal `add(5, 3)` and solves it.

    The pattern that makes the closures canonical test work.
    """
    src = """
    add(N, X, Y) :- Y is X + N.
    :- call(add(5), 3, R), write(R), nl.
    """
    assert _run_prolog(src) == "8\n"


def test_call_1_invokes_goal_term():
    """`call(member(2, [1,2,3]))` is equivalent to `member(2, [1,2,3])`."""
    src = """
    :- call(member(2, [1, 2, 3])), write(found), nl.
    """
    assert _run_prolog(src) == "found\n"


# ---------------------------------------------------------------------------
# Negation as failure
# ---------------------------------------------------------------------------


def test_negation_as_failure_succeeds_when_goal_fails():
    """`\\+ Goal` succeeds when Goal cannot be proven, fails when it can."""
    src = """
    :- \\+ member(99, [1, 2, 3]), write(not_found), nl.
    :- \\+ member(2, [1, 2, 3]), write(should_not_print), nl.
    :- write(reached), nl.
    """
    assert _run_prolog(src) == "not_found\nreached\n"


# ---------------------------------------------------------------------------
# Length / list builtins
# ---------------------------------------------------------------------------


def test_length_of_ground_list():
    """`length([a,b,c], N)` binds N to 3."""
    src = """
    :- length([a, b, c], N), write(N), nl.
    :- length([], N), write(N), nl.
    """
    assert _run_prolog(src) == "3\n0\n"


def test_reverse_ground_list():
    """`reverse([1,2,3], R)` binds R to [3,2,1]."""
    src = """
    :- reverse([1, 2, 3], R), write(R), nl.
    """
    assert _run_prolog(src) == "[3, 2, 1]\n"


# ---------------------------------------------------------------------------
# Resolved spec contract
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# If-then-else (Stage E addition - body operator for kata wrapping)
# ---------------------------------------------------------------------------


def test_ifthenelse_true_branch():
    """`(Cond -> Then ; Else)` runs Then when Cond succeeds."""
    src = """
    :- (member(2, [1, 2, 3]) -> write(yes) ; write(no)), nl.
    """
    assert _run_prolog(src) == "yes\n"


def test_ifthenelse_false_branch():
    """`(Cond -> Then ; Else)` runs Else when Cond fails."""
    src = """
    :- (member(99, [1, 2, 3]) -> write(yes) ; write(no)), nl.
    """
    assert _run_prolog(src) == "no\n"


def test_ifthenelse_commits_to_first_cond_solution():
    """The `->` cuts alternatives - even if Cond has multiple solutions,
    only the first is used (its bindings go into Then)."""
    src = """
    :- (member(X, [1, 2, 3]) -> write(X) ; write(none)), nl.
    """
    # Should write only X=1, not iterate.
    assert _run_prolog(src) == "1\n"


def test_negative_literal_prints_as_signed_number():
    """`-1` prints as `-1`, not as `-(1)`. Codegen folds unary-minus
    over a Num literal into a negative Num value at compile time."""
    src = """
    :- X = -42, write(X), nl.
    :- Y is 0 - 5, write(Y), nl.
    """
    assert _run_prolog(src) == "-42\n-5\n"


# ---------------------------------------------------------------------------
# Kata pack integration (Stage E - CLASSICS_LOGIC_LIKE)
# ---------------------------------------------------------------------------


def test_classics_logic_like_exists_and_has_expected_katas():
    """The kata pack has the 7 katas the design doc named."""
    from forge.orchestrator.kata_packs import CLASSICS_LOGIC_LIKE
    ids = {k["id"] for k in CLASSICS_LOGIC_LIKE}
    expected = {
        "factorial", "list_length", "is_member", "reverse_list",
        "append_lists", "max_list", "ancestor",
    }
    assert ids == expected, f"got {ids}, expected {expected}"


def test_get_classics_routes_logic_like_to_logic_pack():
    """`get_classics_for(logic_like spec)` returns CLASSICS_LOGIC_LIKE."""
    from forge.orchestrator.kata_packs import get_classics_for
    spec = {"options": {"syntax": "logic_like"}}
    katas = get_classics_for(spec)
    ids = {k["id"] for k in katas}
    assert "factorial" in ids and "ancestor" in ids
    assert "two_sum" not in ids  # c_like kata; should NOT be routed here


def test_wrap_with_test_prints_logic_like_result_var_shape():
    """The kata wrapper detects last-arg-is-output and emits
    `:- Goal, write(R), nl.` for tests like `factorial(5, R)`."""
    from forge.orchestrator.katas import _wrap_with_test_prints
    spec = {"options": {"syntax": "logic_like"}, "file_extension": ".lgc",
            "print_form": "write(<args>), nl."}
    tests = [{"call": "factorial(5, R)", "expected": "120"}]
    program = _wrap_with_test_prints("factorial(0, 1).\n", tests, spec)
    assert ":- factorial(5, R), write(R), nl." in program


def test_wrap_with_test_prints_logic_like_boolean_shape():
    """Tests without a free-var last arg (e.g. `is_member(2, [1,2,3])`) get
    wrapped as `:- (Goal -> write(true) ; write(false)), nl.`"""
    from forge.orchestrator.katas import _wrap_with_test_prints
    spec = {"options": {"syntax": "logic_like"}, "file_extension": ".lgc",
            "print_form": "write(<args>), nl."}
    tests = [{"call": "is_member(2, [1,2,3])", "expected": "true"}]
    program = _wrap_with_test_prints("is_member(X, [X|_]).\n", tests, spec)
    assert "is_member(2, [1,2,3]) ->" in program
    assert "write(true)" in program
    assert "write(false)" in program


# ---------------------------------------------------------------------------
# Resolved spec contract
# ---------------------------------------------------------------------------


def test_prologlang_resolved_spec_contract():
    """The resolved_spec.json declares the logic_like family and the right
    surface forms. Stage C will use this to wire up the family in the
    spec builder."""
    import json
    spec = json.loads((PROLOGLANG_DIR / "resolved_spec.json").read_text(encoding="utf-8"))
    assert spec["lang_name"] == "prologlang"
    assert spec["options"]["syntax"] == "logic_like"
    assert spec["options"]["typing"] == "dynamic"
    assert spec["options"]["memory"] == "host_gc"
    assert spec["file_extension"] == ".lgc"
    assert spec["statement_terminator"] == "."
    assert spec["comment_syntax"]["line"] == "%"
    assert spec["comment_syntax"]["block_open"] == "/*"
    assert spec["comment_syntax"]["block_close"] == "*/"
    assert spec["loop_forms"] == [], "logic_like has no while/for"
    assert "is" in spec["keywords"]
    assert "fail" in spec["keywords"]
