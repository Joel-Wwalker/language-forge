"""Tests for kata loading + checking on s_expression languages.

Background: when the user reported "s_expression doesn't work", part 2
was that katas were broken too. The classics pack ships c_like reference
solutions; loading them onto a Lisp-flavored language requires:

  1. Mechanical translation of the c_like reference -> s_expression form
     via the SExpressionBackend in mechanical_translator.
  2. Translation of test-call expressions like `factorial(5)` -> `(factorial 5)`.
  3. Re-derivation of expected outputs (Lisp prints lists as `(1 2 3)`,
     not `[1, 2, 3]`).
  4. Wrapping + running the user's solution against the test suite.

These tests pin the contract end-to-end. They use lisplang as the target
because it's the hand-written reference; if a regression slips into the
codegen, parser, or kata translator, these tests catch it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
LISPLANG_DIR = WORKSPACE_ROOT / "generated" / "lisplang"


def _spec():
    return json.loads(
        (LISPLANG_DIR / "resolved_spec.json").read_text(encoding="utf-8")
    )


# ---------- mechanical translation ----------

def test_classics_pack_all_12_translate_mechanically():
    """The mechanical path (no LLM) must translate every kata in the
    classics pack from c_like to s_expression form. This was the user-
    reported regression: if even one kata drops, the user sees a half-
    populated kata library."""
    from forge.orchestrator.kata_packs import get_pack
    from forge.orchestrator.mechanical_translator import transpile_and_validate

    pack = get_pack("classics")
    results = []
    for k in pack["katas"]:
        translated, reason = transpile_and_validate(k, _spec(), LISPLANG_DIR)
        results.append((k["id"], translated is not None, reason))

    failed = [(kid, r) for kid, ok, r in results if not ok]
    assert not failed, (
        f"{len(failed)} of {len(results)} classics katas failed mechanical "
        f"translation:\n" + "\n".join(f"  {kid}: {r[:200]}" for kid, r in failed)
    )


def test_unary_minus_translates_correctly():
    """Regression test for the bug where `(- 1)` became `_(1)` because
    `_py_name("-")` returns `_`."""
    import sys
    if str(WORKSPACE_ROOT / "generated") not in sys.path:
        sys.path.insert(0, str(WORKSPACE_ROOT / "generated"))
    # Force re-import to pick up the latest codegen
    for m in [k for k in list(sys.modules) if k.startswith("lisplang")]:
        del sys.modules[m]
    from lisplang.parser import parse
    from lisplang.codegen import generate

    src = "(def x (- 1))\n(print x)\n"
    py = generate(parse(src))
    assert "_(1)" not in py, (
        "regression: unary `-` is being routed through _py_name. "
        f"Generated:\n{py}"
    )
    assert "(-1)" in py, f"expected (-1) in output, got:\n{py}"


def test_if_arms_can_be_forms_not_just_expressions():
    """Regression test: `(if cond (return X) nil)` was failing to parse
    because if_stmt only accepted `expr` arms. Mechanical translator
    emits this shape for c_like `if (cond) { return X; }`."""
    import sys
    if str(WORKSPACE_ROOT / "generated") not in sys.path:
        sys.path.insert(0, str(WORKSPACE_ROOT / "generated"))
    from lisplang.parser import parse
    src = """\
(defn maybe (x)
  (if (> x 0)
      (return x)
      nil))
"""
    # Should parse without exception.
    tree = parse(src)
    assert tree is not None


# ---------- end-to-end via the API ----------

@pytest.fixture
def fresh_kata_cache():
    """Drop the lisplang/katas.json cache so each test starts clean."""
    cache = LISPLANG_DIR / "katas.json"
    if cache.exists():
        cache.unlink()
    yield


def test_load_classics_pack_via_api(fresh_kata_cache):
    """End-to-end: POST /api/katas/lisplang/load-pack/classics returns 200
    with all 12 katas, 0 dropped, and source = 'translated:classics'
    (mechanical, no LLM)."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.post("/api/katas/lisplang/load-pack/classics")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert len(data["katas"]) == 12, (
        f"expected 12 katas, got {len(data['katas'])}; "
        f"dropped: {data.get('dropped')}"
    )
    assert len(data.get("dropped") or []) == 0
    # source can be either 'translated:classics' (mechanical or LLM did it)
    # or 'curated:classics' (direct path picked it up). Either is fine.
    assert "classics" in data["source"]


def test_reference_solutions_pass_check_endpoint(fresh_kata_cache):
    """Every kata's reference solution must pass when submitted via the
    check endpoint. If this regresses, the user's submitted solutions
    can never be correct because the test infrastructure is broken."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    # Load the pack
    load = client.post("/api/katas/lisplang/load-pack/classics")
    assert load.status_code == 200
    data = load.get_json()

    failures = []
    for kata in data["katas"]:
        check = client.post(
            f"/api/katas/lisplang/{kata['id']}/check",
            json={"code": kata["reference_solution"], "mode": "submit"},
        )
        result = check.get_json()
        if check.status_code != 200 or not result.get("passed"):
            failures.append((kata["id"], result.get("stage"),
                             (result.get("actual") or result.get("stderr") or "")[:120]))
    assert not failures, (
        f"{len(failures)}/{len(data['katas'])} reference solutions failed:\n"
        + "\n".join(f"  {k}: {s} -> {info}" for k, s, info in failures)
    )


def test_run_mode_returns_per_test_results(fresh_kata_cache):
    """Run mode must return per-test results (not just pass/fail) so
    users can iterate. A wrong solution should clearly fail with the
    expected vs actual output visible."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    client.post("/api/katas/lisplang/load-pack/classics")

    wrong = "(defn two_sum (nums target) (return (list 999 999)))"
    r = client.post(
        "/api/katas/lisplang/two_sum/check",
        json={"code": wrong, "mode": "run"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["passed"] is False
    assert data["mode"] == "run"
    assert len(data["results"]) >= 1
    # First result should have a clear expected vs actual mismatch
    first = data["results"][0]
    assert first["expected"] != first["actual"]
    assert "999" in first["actual"]


def test_correct_solution_in_run_mode(fresh_kata_cache):
    """A correct user solution should pass in run mode."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    load = client.post("/api/katas/lisplang/load-pack/classics")
    data = load.get_json()
    two_sum = next(k for k in data["katas"] if k["id"] == "two_sum")

    r = client.post(
        "/api/katas/lisplang/two_sum/check",
        json={"code": two_sum["reference_solution"], "mode": "run"},
    )
    assert r.status_code == 200
    result = r.get_json()
    assert result["passed"] is True


# ---------- internals: _wrap_with_test_prints behavior ----------

def test_wrap_test_prints_handles_already_translated_calls():
    """The bug: `_wrap_with_test_prints` was double-translating when the
    test calls were already in s_expression form. Now it detects calls
    starting with `(` and wraps them directly."""
    from forge.orchestrator.katas import _wrap_with_test_prints

    spec = _spec()
    user_code = "(defn id (x) x)"
    tests = [{"call": "(id 42)", "expected": "42"}]
    program = _wrap_with_test_prints(user_code, tests, spec)
    assert "(print (id 42))" in program
    # Must NOT contain c_like-style print() with parens around args
    assert "print((id 42))" not in program


def test_wrap_test_prints_translates_c_like_calls():
    """When test calls are still in c_like form (e.g. direct curated
    pack against an s_expression target), _wrap should translate them."""
    from forge.orchestrator.katas import _wrap_with_test_prints

    spec = _spec()
    user_code = "(defn factorial (n) (if (<= n 1) 1 (* n (factorial (- n 1)))))"
    tests = [{"call": "factorial(5)", "expected": "120"}]
    program = _wrap_with_test_prints(user_code, tests, spec)
    # Expected: `(print (factorial 5))` after translation
    assert "(print" in program
    assert "(factorial 5)" in program or "factorial(5)" not in program


def test_helpers_included_in_rederive():
    """Regression test for the linked_list_reverse failure: _rederive_expected
    must pass kata['helpers'] through to _wrap_with_test_prints, otherwise
    katas with helper functions (linked-list/tree node constructors) fail
    to compile during expected-output re-derivation."""
    from forge.orchestrator.kata_packs import get_pack
    from forge.orchestrator.mechanical_translator import transpile_kata, _rederive_expected

    pack = get_pack("classics")
    ll_kata = next(k for k in pack["katas"] if k["id"] == "linked_list_reverse")
    assert ll_kata.get("helpers"), "fixture sanity: ll_kata should have helpers"

    spec = _spec()
    translated = transpile_kata(ll_kata, spec)
    rederived = _rederive_expected(translated, spec, LISPLANG_DIR)
    assert rederived is not None, (
        "rederive returned None; helpers may not be passed through"
    )
    # Expected outputs should be in s-expression form `(4 3 2 1)`,
    # not c_like form `[4, 3, 2, 1]`.
    first_expected = rederived["tests"][0]["expected"]
    assert "[" not in first_expected, (
        f"expected re-derivation to absorb list format; got {first_expected!r}"
    )


# ---------- per-user-reported scenario regression ----------

def test_tree_max_depth_reference_passes_via_api(fresh_kata_cache):
    """Specific regression test for the user complaint:
    'when i literally upload the solution you gave for say, binary tree
    max depth, it returns a compiler error'.

    The user pastes the reference solution into the kata editor and
    submits. The submission must compile and pass all hidden tests."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    load = client.post("/api/katas/lisplang/load-pack/classics")
    assert load.status_code == 200
    katas = load.get_json()["katas"]
    tmd = next(k for k in katas if k["id"] == "tree_max_depth")
    # Submit the literal reference text the user would see in 'Show solution'.
    r = client.post(
        "/api/katas/lisplang/tree_max_depth/check",
        json={"code": tmd["reference_solution"], "mode": "submit"},
    )
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["passed"] is True, (
        f"tree_max_depth reference solution failed:\n"
        f"stage={data.get('stage')}\n"
        f"stderr={data.get('stderr', '')[:500]}\n"
        f"program_excerpt={data.get('program_excerpt', '')[:500]}"
    )


def test_compile_error_includes_program_excerpt(fresh_kata_cache):
    """When a submission passes pre-flight (balanced parens, starts with
    `(`) but fails to compile, the response must include a `program_excerpt`
    showing what was actually compiled (helpers + user code + test prints).

    We use balanced-but-semantically-invalid code: it gets past preflight
    and into the actual Lark parser, which rejects it for some other
    reason. This is the path users hit when their solution has subtle
    grammar errors (e.g. wrong number of args to a special form)."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    client.post("/api/katas/lisplang/load-pack/classics")

    # Balanced parens, starts with `(`, BUT uses a reserved word `defn`
    # with totally wrong shape - the parser rejects it.
    r = client.post(
        "/api/katas/lisplang/tree_max_depth/check",
        json={"code": "(defn @@@ #### ----)", "mode": "submit"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["passed"] is False
    # If the parens-balanced check passed, we expect compile stage with
    # an excerpt. If preflight catches it, that's also fine for this
    # behavior - either way the user gets actionable feedback.
    if data["stage"] == "compile":
        assert data.get("program_excerpt"), (
            "expected program_excerpt in compile-error response"
        )
        assert "(defn node" in data["program_excerpt"], "helpers should be in excerpt"
        assert "@@@" in data["program_excerpt"], "user code should be in excerpt"


def test_run_mode_includes_program_excerpt_on_failure(fresh_kata_cache):
    """Same for run mode: compile failures (after preflight passes)
    should expose the wrapped program for debugging."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    client.post("/api/katas/lisplang/load-pack/classics")

    # Balanced parens but invalid lisp body
    r = client.post(
        "/api/katas/lisplang/tree_max_depth/check",
        json={"code": "(defn max_depth (root) (@@@@ root))", "mode": "run"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["passed"] is False
    # Same as above: either preflight or compile-stage error is fine,
    # but compile-stage MUST include the excerpt.
    if data["stage"] == "compile":
        assert data.get("program_excerpt")


# ---------- preflight syntax check ----------
# Catches common copy/paste corruption (missing leading paren, unbalanced
# parens) BEFORE compilation so users see a helpful message instead of a
# Lark UnexpectedCharacters traceback.

def test_preflight_catches_missing_leading_paren(fresh_kata_cache):
    """Direct regression test for the user-uploaded error1.md scenario:
    the pasted code starts with `efn max_depth` instead of `(defn ...`
    because the leading `(d` got dropped on copy. Preflight must catch
    this BEFORE compilation and surface a friendly message."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    client.post("/api/katas/lisplang/load-pack/classics")

    broken = (
        "efn max_depth (root)\n"
        "    (do\n"
        "        (if (= root nil)\n"
        "        (return 0)\n"
        "        nil)\n"
        "        (return (+ r 1))))\n"
    )
    r = client.post(
        "/api/katas/lisplang/tree_max_depth/check",
        json={"code": broken, "mode": "submit"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["passed"] is False
    assert data["stage"] == "preflight", (
        f"expected preflight stage, got {data['stage']}; stderr={data.get('stderr', '')[:200]}"
    )
    # Message should mention the user-friendly recovery path.
    assert "doesn't start with `(`" in data["stderr"]
    assert "Load into editor" in data["stderr"]
    # Should quote what they actually submitted so they can spot the
    # corruption.
    assert "efn max_depth" in data["stderr"]


def test_preflight_catches_unbalanced_parens(fresh_kata_cache):
    """A submission with the right shape but missing a close paren
    must be caught by preflight, not the Lark compiler."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    client.post("/api/katas/lisplang/load-pack/classics")

    broken = "(defn max_depth (root (return 0)"   # 3 open, 1 close
    r = client.post(
        "/api/katas/lisplang/tree_max_depth/check",
        json={"code": broken, "mode": "submit"},
    )
    data = r.get_json()
    assert data["stage"] == "preflight"
    assert "unbalanced" in data["stderr"].lower()
    assert "3 `(`" in data["stderr"] and "1 `)`" in data["stderr"]


def test_preflight_passes_well_formed_code(fresh_kata_cache):
    """Regression safety: well-formed code must NOT be caught by
    preflight. The reference solutions all start with `(` and have
    balanced parens, so they should flow through to actual compilation."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    load = client.post("/api/katas/lisplang/load-pack/classics")
    katas = load.get_json()["katas"]

    for k in katas:
        ref = k["reference_solution"]
        r = client.post(
            f"/api/katas/lisplang/{k['id']}/check",
            json={"code": ref, "mode": "submit"},
        )
        data = r.get_json()
        assert data.get("stage") != "preflight", (
            f"{k['id']}: well-formed reference was incorrectly flagged by "
            f"preflight: {data.get('stderr', '')[:200]}"
        )


def test_preflight_catches_extra_close_parens(fresh_kata_cache):
    """A submission with too many close parens must be caught with a
    clear 'extra closing paren' message."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    client.post("/api/katas/lisplang/load-pack/classics")

    broken = "(def x 5)))"   # 1 open, 3 close
    r = client.post(
        "/api/katas/lisplang/tree_max_depth/check",
        json={"code": broken, "mode": "submit"},
    )
    data = r.get_json()
    assert data["stage"] == "preflight"
    assert "extra" in data["stderr"].lower() and "closing paren" in data["stderr"]


def test_preflight_ignores_parens_inside_strings():
    """Parens inside string literals must NOT be counted in the balance
    check. Strings can contain anything."""
    from forge.orchestrator.katas import preflight_check
    spec = {"options": {"syntax": "s_expression"}}
    # 1 open, 1 close at code level; string contains extra parens.
    code = '(def s "this has (((( in it")'
    assert preflight_check(code, spec) is None


def test_preflight_ignores_parens_in_line_comments():
    """Line comments after `;` must not affect paren counting."""
    from forge.orchestrator.katas import preflight_check
    spec = {"options": {"syntax": "s_expression"}}
    code = "(def x 5)  ; (((  trailing comment with random parens"
    assert preflight_check(code, spec) is None


def test_preflight_only_runs_for_s_expression():
    """c_like and python_like submissions must skip the preflight check
    entirely. Other syntaxes have their own conventions."""
    from forge.orchestrator.katas import preflight_check
    # c_like code without parens is normal.
    c_spec = {"options": {"syntax": "c_like"}}
    assert preflight_check("var x = 5;", c_spec) is None
    p_spec = {"options": {"syntax": "python_like"}}
    assert preflight_check("let x = 5", p_spec) is None


def test_preflight_catches_empty_submission():
    """Empty / whitespace-only submissions get a friendly 'type something' message."""
    from forge.orchestrator.katas import preflight_check
    spec = {"options": {"syntax": "s_expression"}}
    for empty in ("", "   ", "\n\n", "\t  \n"):
        result = preflight_check(empty, spec)
        assert result is not None
        assert "empty" in result["stderr"].lower()


def test_all_classics_references_pass_via_api(fresh_kata_cache):
    """Comprehensive: every classics kata's reference solution must pass
    when submitted as user code. This is the user's actual workflow:
    Show Solution → copy → paste → Submit. If ANY of them produces a
    compile error, the user's experience is broken."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    load = client.post("/api/katas/lisplang/load-pack/classics")
    katas = load.get_json()["katas"]

    failures = []
    for k in katas:
        ref = k["reference_solution"]
        r = client.post(
            f"/api/katas/lisplang/{k['id']}/check",
            json={"code": ref, "mode": "submit"},
        )
        data = r.get_json()
        if not data.get("passed"):
            failures.append({
                "id": k["id"],
                "stage": data.get("stage"),
                "stderr": (data.get("stderr") or "")[:200],
                "first_excerpt_line": (data.get("program_excerpt") or "").splitlines()[:1],
            })
    assert not failures, (
        "User-facing reference solutions failed on submit:\n"
        + "\n".join(f"  {f['id']}: stage={f['stage']} stderr={f['stderr']}"
                    for f in failures)
    )
