"""Tests for the curated stack_classics kata pack.

Per families.md item 2.2: "Pair this family with a curated kata pack
tuned to it." The c_like classics lean heavily on lists/dicts, which
are awkward in pure stack form. Stack-classics is 8 stack-friendly
problems: factorial, fib, gcd, sum-to-n, is-prime, count-digits,
reverse-digits, power-of-two.

Reference solutions are written in forthlang syntax. We pin:
  - the pack registers under `stack_classics` with syntax_family=stack_based
  - all 8 reference solutions self-validate against forthlang
  - the GUI auto-redirects `classics` -> `stack_classics` for stack_based
    languages so users never see "12 katas dropped" on Forth dialects
  - kata structure is consistent: id, title, problem, function_name,
    starter_code, reference_solution, tests, sample_test_indices, tags
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FORTHLANG_DIR = WORKSPACE_ROOT / "generated" / "forthlang"


# ---------- pack registry ----------

def test_stack_classics_pack_registered():
    from forge.orchestrator.kata_packs import list_packs, get_pack
    keys = {p["key"] for p in list_packs()}
    assert "stack_classics" in keys
    pack = get_pack("stack_classics")
    assert pack is not None
    assert pack["syntax_family"] == "stack_based"
    # 8 number-theory + 5 data-structure katas (linked-list + tree).
    assert len(pack["katas"]) == 13


def test_stack_classics_kata_ids():
    from forge.orchestrator.kata_packs import get_pack
    pack = get_pack("stack_classics")
    ids = {k["id"] for k in pack["katas"]}
    expected = {
        # Number-theory + iteration
        "factorial", "fib", "gcd", "sum_to_n", "is_prime",
        "count_digits", "reverse_digits", "power_of_two",
        # Data structures (linked list + binary tree)
        "ll_length", "ll_sum", "ll_reverse",
        "tree_max_depth", "tree_sum",
    }
    assert ids == expected


@pytest.mark.parametrize("kata_id", [
    "factorial", "fib", "gcd", "sum_to_n", "is_prime",
    "count_digits", "reverse_digits", "power_of_two",
    "ll_length", "ll_sum", "ll_reverse",
    "tree_max_depth", "tree_sum",
])
def test_stack_classics_kata_has_required_fields(kata_id):
    from forge.orchestrator.kata_packs import get_pack
    pack = get_pack("stack_classics")
    k = next(k for k in pack["katas"] if k["id"] == kata_id)
    for field in ("title", "problem", "function_name", "starter_code",
                  "reference_solution", "tests", "sample_test_indices"):
        assert k.get(field) is not None, f"{kata_id} missing {field}"
    assert len(k["tests"]) >= 3, f"{kata_id} should have at least 3 tests"


@pytest.mark.parametrize("kata_id", [
    "ll_length", "ll_sum", "ll_reverse",
    "tree_max_depth", "tree_sum",
])
def test_data_structure_katas_have_helpers(kata_id):
    """Linked-list + tree katas need helpers (ll-node, t-node, leaf, ...)
    pre-defined for the user. Without them the user would have to
    re-implement node construction in every solution."""
    from forge.orchestrator.kata_packs import get_pack
    pack = get_pack("stack_classics")
    k = next(k for k in pack["katas"] if k["id"] == kata_id)
    helpers = k.get("helpers", "")
    assert helpers, f"{kata_id} must define `helpers` (linked-list/tree constructors)"
    # ll-* katas need ll-node, vals->ll, ll->vals
    if kata_id.startswith("ll_"):
        assert "ll-node" in helpers
        assert "vals->ll" in helpers
        assert "ll->vals" in helpers
    # tree_* katas need t-node and leaf
    if kata_id.startswith("tree_"):
        assert "t-node" in helpers
        assert "leaf" in helpers


# ---------- self-validation against forthlang ----------

@pytest.fixture
def fresh_kata_cache():
    cache = FORTHLANG_DIR / "katas.json"
    if cache.exists():
        cache.unlink()
    yield


def test_load_stack_classics_via_api(fresh_kata_cache):
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.post("/api/katas/forthlang/load-pack/stack_classics")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    # 8 number-theory + 5 data-structure katas.
    assert len(data["katas"]) == 13
    assert len(data.get("dropped") or []) == 0
    assert data["source"].endswith("stack_classics")


def test_all_stack_classics_references_pass_via_api(fresh_kata_cache):
    """The user-paste flow: every reference solution must compile + run +
    pass its full test suite when submitted as user code."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    load = client.post("/api/katas/forthlang/load-pack/stack_classics")
    assert load.status_code == 200
    katas = load.get_json()["katas"]

    failures = []
    for k in katas:
        r = client.post(
            f"/api/katas/forthlang/{k['id']}/check",
            json={"code": k["reference_solution"], "mode": "submit"},
        )
        data = r.get_json()
        if not data.get("passed"):
            failures.append({
                "id": k["id"],
                "stage": data.get("stage"),
                "stderr": (data.get("stderr") or "")[:200],
                "test_index": data.get("test_index"),
            })
    assert not failures, (
        "stack_classics reference solutions failed on submit:\n"
        + "\n".join(f"  {f['id']}: stage={f['stage']} test={f['test_index']} stderr={f['stderr']}"
                    for f in failures)
    )


# ---------- auto-redirect: classics -> stack_classics on stack_based ----------

def test_classics_redirects_to_stack_classics_for_stack_based(fresh_kata_cache):
    """A user clicking 'Load classics' on a Forth-flavored language must
    transparently get the stack_classics pack instead of seeing 8/12
    drops because c_like references can't compile on Forth."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.post("/api/katas/forthlang/load-pack/classics")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    # The source should be the stack_classics pack (auto-redirected),
    # NOT the c_like classics pack.
    assert data["source"].endswith("stack_classics"), (
        f"expected auto-redirect to stack_classics, got source={data['source']}"
    )
    assert len(data["katas"]) == 13


def test_classics_does_NOT_redirect_for_c_like_languages():
    """Regression safety: c_like languages must still load the c_like
    classics, not get redirected somewhere."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    # toylang is c_like
    r = client.post("/api/katas/toylang/load-pack/classics")
    assert r.status_code == 200
    data = r.get_json()
    assert data["source"] == "curated:classics" or data["source"] == "translated:classics"
    # Has 12 katas (the c_like LeetCode classics), not 8.
    assert len(data["katas"]) == 12


# ---------- run + submit modes work ----------

def test_run_mode_returns_per_test_results(fresh_kata_cache):
    """Run mode must show per-test results with expected/actual pairs.
    Use the `gcd` kata since its sample tests use distinct inputs (so
    a wrong solution will visibly fail the visible tests, not just
    the hidden ones)."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    client.post("/api/katas/forthlang/load-pack/stack_classics")

    # Wrong gcd: just sums the inputs (clearly wrong; sample tests
    # `12 18 gcd` -> 6 and `17 5 gcd` -> 1 will both fail).
    wrong = ": gcd + ;"
    r = client.post(
        "/api/katas/forthlang/gcd/check",
        json={"code": wrong, "mode": "run"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["passed"] is False
    assert data["mode"] == "run"
    assert len(data["results"]) >= 1
    # At least one result must clearly show wrong-answer with expected/actual.
    for res in data["results"]:
        assert "expected" in res
        assert "actual" in res
        assert "call" in res
    has_fail = any(not r["passed"] for r in data["results"])
    assert has_fail, "expected at least one failing visible result"


def test_correct_solution_passes_run_mode(fresh_kata_cache):
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    load = client.post("/api/katas/forthlang/load-pack/stack_classics")
    factorial = next(k for k in load.get_json()["katas"] if k["id"] == "factorial")
    r = client.post(
        "/api/katas/forthlang/factorial/check",
        json={"code": factorial["reference_solution"], "mode": "run"},
    )
    assert r.status_code == 200
    assert r.get_json()["passed"] is True


# ---------- nested-paren stack-effect comments ----------

def test_parser_handles_nested_parens_in_stack_effect():
    """Regression test: `( n -- fib(n) )` has a nested `(n)` which
    naive find-first-`)` tokenization terminated early, leaving a
    stray `)` token that broke colon definitions. The fixed tokenizer
    counts balanced parens."""
    import sys
    if str(WORKSPACE_ROOT / "generated") not in sys.path:
        sys.path.insert(0, str(WORKSPACE_ROOT / "generated"))
    for m in [k for k in list(sys.modules) if k.startswith("forthlang")]:
        del sys.modules[m]
    from forthlang.parser import parse
    src = ": fib ( n -- fib(n) ) drop 0 ;\n5 fib .\n"
    tree = parse(src)
    # First form is the colon_def
    assert tree[0]["kind"] == "colon_def"
    assert tree[0]["name"] == "fib"
