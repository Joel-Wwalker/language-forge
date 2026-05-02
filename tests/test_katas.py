"""Tests for the kata system.

Self-validation, solution checking, and the API surface. These tests do
NOT call the LLM; we hand-craft kata pack dicts and exercise the
real compile+run path against the toylang reference compiler.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.orchestrator.katas import (
    _self_validate, check_solution, load_pack, _wrap_with_test_prints,
)


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


def _toylang_spec():
    return json.loads((TOYLANG_DIR / "resolved_spec.json").read_text(encoding="utf-8"))


def _kata(reference, tests, **extra):
    """Helper: build a kata dict with sensible defaults."""
    return {
        "id": "test_kata",
        "title": "Test",
        "difficulty": "easy",
        "problem": "test",
        "function_name": "test_fn",
        "starter_code": "// stub\n",
        "reference_solution": reference,
        "tests": tests,
        **extra,
    }


# ---------------------------------------------------------------------------
# Self-validation
# ---------------------------------------------------------------------------

def test_self_validate_passes_for_correct_reference():
    spec = _toylang_spec()
    kata = _kata(
        reference="func double(x) { return x * 2; }\n",
        tests=[
            {"call": "double(3)", "expected": "6"},
            {"call": "double(0)", "expected": "0"},
            {"call": "double(-5)", "expected": "-10"},
        ],
    )
    ok, reason = _self_validate(kata, TOYLANG_DIR, spec)
    assert ok is True, reason


def test_self_validate_fails_when_reference_doesnt_match_expected():
    spec = _toylang_spec()
    kata = _kata(
        reference="func double(x) { return x * 2; }\n",
        tests=[{"call": "double(3)", "expected": "999"}],   # wrong expected
    )
    ok, reason = _self_validate(kata, TOYLANG_DIR, spec)
    assert ok is False
    assert "expected" in reason and "999" in reason


def test_self_validate_fails_when_reference_doesnt_compile():
    spec = _toylang_spec()
    kata = _kata(
        reference="this is not valid syntax @!#",
        tests=[{"call": "foo()", "expected": "x"}],
    )
    ok, reason = _self_validate(kata, TOYLANG_DIR, spec)
    assert ok is False
    assert "compile" in reason or "lark" in reason.lower()


# ---------------------------------------------------------------------------
# check_solution: passing path
# ---------------------------------------------------------------------------

def test_check_solution_passes_when_correct():
    spec = _toylang_spec()
    kata = _kata(
        reference="// not used here\n",
        tests=[
            {"call": "add(2, 3)", "expected": "5"},
            {"call": "add(0, 0)", "expected": "0"},
        ],
    )
    user_code = "func add(a, b) { return a + b; }\n"
    result = check_solution(spec, TOYLANG_DIR, kata, user_code)
    assert result["passed"] is True
    assert result["passing_count"] == 2


def test_check_solution_fails_with_first_failure_only():
    """Per the doc: don't reveal all hidden tests at once."""
    spec = _toylang_spec()
    kata = _kata(
        reference="// not used\n",
        tests=[
            {"call": "buggy(1)", "expected": "1"},     # passes
            {"call": "buggy(2)", "expected": "4"},     # fails (returns 2*2=4 OK actually)
            {"call": "buggy(3)", "expected": "999"},   # fails
        ],
    )
    user_code = "func buggy(x) { return x * 2; }\n"
    # buggy(1) -> 2, expected 1: FAILS first test
    result = check_solution(spec, TOYLANG_DIR, kata, user_code)
    assert result["passed"] is False
    assert result["test_index"] == 0
    assert result["expected"] == "1"
    assert result["actual"] == "2"


def test_check_solution_reports_compile_failure():
    spec = _toylang_spec()
    kata = _kata(
        reference="// not used\n",
        tests=[{"call": "f(1)", "expected": "1"}],
    )
    bad_code = "this is not valid syntax"
    result = check_solution(spec, TOYLANG_DIR, kata, bad_code)
    assert result["passed"] is False
    assert result["stage"] == "compile"


def test_check_solution_handles_stub_rescued_kata():
    """Stub-rescued katas (translation failed, saved with empty tests +
    stub_rescued=True) should compile-check the user's code but report
    'no auto-check' instead of pass/fail."""
    spec = _toylang_spec()
    kata = _kata(
        reference="// stub: untranslatable\n",
        tests=[],
    )
    kata["stub_rescued"] = True
    user_code = "func test_fn() { return 42; }\n"
    result = check_solution(spec, TOYLANG_DIR, kata, user_code)
    assert result["passed"] is False
    assert result["stage"] == "no_tests"
    assert "auto-check" in result["stderr"].lower()


def test_check_solution_no_tests_reports_compile_errors():
    """Even on stub-rescued katas, syntax errors in the user's code should
    surface as compile failures so the user still gets feedback."""
    spec = _toylang_spec()
    kata = _kata(reference="// stub\n", tests=[])
    kata["stub_rescued"] = True
    result = check_solution(spec, TOYLANG_DIR, kata, "@@@@ not valid")
    assert result["passed"] is False
    assert result["stage"] == "compile"


# ---------------------------------------------------------------------------
# Helper: print-line wrapping uses the right terminator
# ---------------------------------------------------------------------------

def test_wrap_with_test_prints_uses_semicolons_for_c_like():
    spec = {"statement_terminator": ";"}
    user = "func add(a, b) { return a + b; }"
    program = _wrap_with_test_prints(user, [
        {"call": "add(1, 2)", "expected": "3"},
        {"call": "add(0, 0)", "expected": "0"},
    ], spec)
    assert "print(add(1, 2));" in program
    assert "print(add(0, 0));" in program


def test_wrap_with_test_prints_no_terminator_for_python_like():
    spec = {"statement_terminator": "newline"}
    program = _wrap_with_test_prints("def foo():\n    return 1", [
        {"call": "foo()", "expected": "1"},
    ], spec)
    assert "print(foo())\n" in program
    assert "print(foo());" not in program


# ---------------------------------------------------------------------------
# load_pack
# ---------------------------------------------------------------------------

def test_load_pack_returns_none_when_missing(tmp_path):
    assert load_pack(tmp_path) is None


def test_load_pack_round_trip(tmp_path):
    sample = {"katas": [_kata("// x\n", [{"call": "f()", "expected": "1"}])]}
    (tmp_path / "katas.json").write_text(json.dumps(sample), encoding="utf-8")
    loaded = load_pack(tmp_path)
    assert loaded is not None
    assert loaded["katas"][0]["id"] == "test_kata"


# ---------------------------------------------------------------------------
# Working-sample picker + fix-up retry
# ---------------------------------------------------------------------------

def test_pick_working_sample_finds_canonical_test():
    """toylang has tests/loops.toy etc. The picker should return a real
    working program to use as ground truth in the kata prompt."""
    from forge.orchestrator.katas import _pick_working_sample
    spec = _toylang_spec()
    sample = _pick_working_sample(TOYLANG_DIR, spec)
    assert sample is not None
    assert "//" in sample or "var" in sample or "func" in sample or "print" in sample


def test_pick_working_sample_returns_none_for_bare_dir(tmp_path):
    from forge.orchestrator.katas import _pick_working_sample
    spec = {"file_extension": ".toy"}
    assert _pick_working_sample(tmp_path, spec) is None


def test_generate_katas_uses_fix_up_retry(tmp_path):
    """A client that returns a broken kata then a corrected one. The
    pack should accept the kata after the fix-up succeeds."""
    from forge.orchestrator.katas import generate_katas
    import shutil

    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()

    class FakeClient:
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            if tag == "katas":
                return {"katas": [{
                    "id": "double",
                    "title": "Double a number",
                    "difficulty": "easy",
                    "problem": "Return 2*x.",
                    "function_name": "double",
                    "starter_code": "func double(x) { }",
                    "reference_solution": "this is not valid syntax @!@",
                    "tests": [
                        {"call": "double(3)", "expected": "6"},
                        {"call": "double(0)", "expected": "0"},
                    ],
                }]}
            if tag.startswith("kata-fix"):
                return {"reference_solution": "func double(x) { return x * 2; }\n"}
            raise RuntimeError(f"unexpected tag: {tag}")

    pack = generate_katas(spec, work, FakeClient(), fix_attempts=2)
    assert len(pack["katas"]) == 1
    assert pack["katas"][0]["reference_solution"].strip().startswith("func double")
    assert pack["dropped"] == []


def test_generate_katas_records_drop_when_fix_also_fails(tmp_path):
    """If every fix-up retry also fails, the kata is dropped with its
    final error and a fix_attempts count. The exception's `pack` carries
    full drop info."""
    from forge.orchestrator.katas import generate_katas, AllKatasDroppedError
    import shutil

    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()

    class StubbornlyBrokenClient:
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            if tag == "katas":
                return {"katas": [{
                    "id": "broken",
                    "title": "Broken",
                    "difficulty": "easy",
                    "problem": "broken",
                    "function_name": "f",
                    "starter_code": "func f() {}",
                    "reference_solution": "@@@ not valid",
                    "tests": [{"call": "f()", "expected": "1"}],
                }]}
            return {"reference_solution": "still @@@ not valid"}

    with pytest.raises(AllKatasDroppedError) as ei:
        generate_katas(spec, work, StubbornlyBrokenClient(), fix_attempts=2)
    pack = ei.value.pack
    assert pack is not None
    assert len(pack["katas"]) == 0
    assert len(pack["dropped"]) == 1
    assert pack["dropped"][0]["fix_attempts"] == 2


# ---------------------------------------------------------------------------
# Curated kata packs (LeetCode classics): the hand-written, no-LLM path
# ---------------------------------------------------------------------------

def test_kata_packs_listing():
    from forge.orchestrator.kata_packs import list_packs, PACKS
    listed = list_packs()
    assert len(listed) == len(PACKS)
    keys = {p["key"] for p in listed}
    assert "classics" in keys
    classics = next(p for p in listed if p["key"] == "classics")
    assert classics["kata_count"] >= 10
    assert classics["syntax_family"] == "c_like"
    assert isinstance(classics["title"], str) and classics["title"]


def test_get_pack_returns_deep_copy():
    from forge.orchestrator.kata_packs import get_pack
    a = get_pack("classics")
    b = get_pack("classics")
    assert a is not None and b is not None
    assert a is not b
    # Mutating one must not bleed into the other (deepcopy guarantee).
    a["katas"][0]["title"] = "MUTATED"
    assert b["katas"][0]["title"] != "MUTATED"


def test_get_pack_unknown_returns_none():
    from forge.orchestrator.kata_packs import get_pack
    assert get_pack("does_not_exist") is None


def test_recursive_classics_all_self_validate_on_toylang():
    """The recursive variant of the classics (used for no_mutation languages
    like love) must also pass on toylang. It uses tail recursion instead of
    loops + reassignment, which is universally portable."""
    from forge.orchestrator.kata_packs import CLASSICS_C_LIKE_RECURSIVE
    spec = _toylang_spec()
    failures = []
    for kata in CLASSICS_C_LIKE_RECURSIVE:
        ok, reason = _self_validate(kata, TOYLANG_DIR, spec)
        if not ok:
            failures.append((kata["id"], reason[:200]))
    assert not failures, "recursive variant broken: " + "; ".join(
        f"{kid}: {r}" for kid, r in failures
    )


def test_get_classics_for_picks_recursive_for_no_mutation():
    """get_classics_for(spec) should return the recursive variant when the
    spec has no_mutation in feature_bans, otherwise the iterative one."""
    from forge.orchestrator.kata_packs import (
        get_classics_for, CLASSICS_C_LIKE, CLASSICS_C_LIKE_RECURSIVE,
    )
    no_mut = {"customization": {"feature_bans": ["no_mutation"]}}
    chosen = get_classics_for(no_mut)
    # Same set of kata IDs, but the references differ: iterative uses while,
    # recursive doesn't.
    chosen_refs = {k["id"]: k["reference_solution"] for k in chosen}
    iter_refs = {k["id"]: k["reference_solution"] for k in CLASSICS_C_LIKE}
    rec_refs = {k["id"]: k["reference_solution"] for k in CLASSICS_C_LIKE_RECURSIVE}
    assert chosen_refs == rec_refs

    plain = {"customization": {}}
    chosen2 = get_classics_for(plain)
    chosen2_refs = {k["id"]: k["reference_solution"] for k in chosen2}
    assert chosen2_refs == iter_refs

    # no_loops also routes to recursive (loops banned == use recursion).
    no_loops = {"customization": {"feature_bans": ["no_loops"]}}
    chosen3 = get_classics_for(no_loops)
    assert {k["id"]: k["reference_solution"] for k in chosen3} == rec_refs


def test_recursive_variant_has_no_reassignment():
    """Sanity check: every recursive kata's reference must NOT contain
    reassignment patterns like `x = expr;` (where x was previously declared).
    Detecting this perfectly needs an AST walker, but a simple heuristic is:
    the reference must not contain `i = i +`, `lo = ...`, etc. — all the
    counter-bumping patterns the iterative variant uses."""
    from forge.orchestrator.kata_packs import CLASSICS_C_LIKE_RECURSIVE
    forbidden_patterns = [
        "i = i + 1;",      # counter increment
        "i = i - 1;",      # counter decrement
        "lo = lo +",       # two-pointer left advance
        "hi = hi -",       # two-pointer right retreat
    ]
    for k in CLASSICS_C_LIKE_RECURSIVE:
        ref = k["reference_solution"]
        for pat in forbidden_patterns:
            assert pat not in ref, (
                f"kata {k['id']} contains reassignment `{pat}` — "
                f"this won't work on no_mutation languages. Use recursion."
            )


def test_classics_all_self_validate_on_toylang():
    """Every classic kata's reference must compile + produce its own
    expected outputs on toylang. This is the single most important test —
    if it breaks, users can't load the pack."""
    from forge.orchestrator.kata_packs import CLASSICS_C_LIKE
    spec = _toylang_spec()
    failures = []
    for kata in CLASSICS_C_LIKE:
        ok, reason = _self_validate(kata, TOYLANG_DIR, spec)
        if not ok:
            failures.append((kata["id"], reason))
    assert not failures, "classics broken: " + "; ".join(
        f"{kid}: {reason[:120]}" for kid, reason in failures
    )


def test_classic_kata_shapes():
    """Every classic must satisfy the same JSON shape `generate_katas`
    produces — id, title, difficulty, problem, function_name, starter_code,
    reference_solution, tests."""
    from forge.orchestrator.kata_packs import CLASSICS_C_LIKE
    required = {"id", "title", "difficulty", "problem", "function_name",
                "starter_code", "reference_solution", "tests"}
    seen_ids = set()
    for kata in CLASSICS_C_LIKE:
        missing = required - kata.keys()
        assert not missing, f"{kata.get('id', '?')}: missing {missing}"
        assert kata["difficulty"] in ("easy", "medium", "hard")
        assert kata["id"] not in seen_ids, f"duplicate id: {kata['id']}"
        seen_ids.add(kata["id"])
        # tests array sane?
        assert len(kata["tests"]) >= 2
        for t in kata["tests"]:
            assert "call" in t and "expected" in t
            assert isinstance(t["call"], str) and t["call"].strip()
            assert isinstance(t["expected"], str)


def test_classics_cover_advertised_problem_types():
    """We promised the user: two sum, linked list, binary tree, two pointer.
    Make sure those problem categories are actually represented so the pack
    delivers what the GUI's tooltip claims."""
    from forge.orchestrator.kata_packs import CLASSICS_C_LIKE
    ids = {k["id"] for k in CLASSICS_C_LIKE}
    assert "two_sum" in ids
    assert "two_pointer_pair_sum" in ids
    assert "linked_list_reverse" in ids
    assert "tree_max_depth" in ids


# ---------------------------------------------------------------------------
# /api/kata-packs and /api/katas/<lang>/load-pack/<key> endpoints
# ---------------------------------------------------------------------------

def test_api_list_kata_packs():
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.get("/api/kata-packs")
    assert r.status_code == 200
    data = r.get_json()
    assert "packs" in data
    keys = {p["key"] for p in data["packs"]}
    assert "classics" in keys


def test_api_load_pack_into_toylang(tmp_path, monkeypatch):
    """Hit /api/katas/<lang>/load-pack/<key>. Verify it saves a katas.json
    with the curated katas, and that GET /api/katas/<lang> returns the same."""
    from forge.gui import app as app_module
    # Don't clobber the real toylang/katas.json — point WORKSPACE at a copy.
    import shutil
    fake_workspace = tmp_path / "ws"
    (fake_workspace / "generated").mkdir(parents=True)
    shutil.copytree(
        TOYLANG_DIR, fake_workspace / "generated" / "toylang",
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    app = app_module.create_app()
    client = app.test_client()

    r = client.post("/api/katas/toylang/load-pack/classics")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["source"] == "curated:classics"
    assert len(data["katas"]) >= 10
    assert data["dropped"] == []
    assert (fake_workspace / "generated" / "toylang" / "katas.json").exists()

    # GET should now return the saved pack.
    r = client.get("/api/katas/toylang")
    assert r.status_code == 200
    assert len(r.get_json()["katas"]) == len(data["katas"])


def test_api_load_pack_unknown_pack(tmp_path, monkeypatch):
    from forge.gui import app as app_module
    import shutil
    fake_workspace = tmp_path / "ws"
    (fake_workspace / "generated").mkdir(parents=True)
    shutil.copytree(
        TOYLANG_DIR, fake_workspace / "generated" / "toylang",
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    app = app_module.create_app()
    client = app.test_client()
    r = client.post("/api/katas/toylang/load-pack/nope")
    assert r.status_code == 404
    assert "no such pack" in r.get_json()["error"]


def test_api_load_pack_unknown_language():
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.post("/api/katas/no_such_lang/load-pack/classics")
    assert r.status_code == 404


def test_batch_validate_happy_path():
    """One compile+run for the entire pack. Returns (kata, True, 'ok')
    triples when every reference produces every expected output."""
    from forge.orchestrator.katas import _batch_validate
    from forge.orchestrator.kata_packs import CLASSICS_C_LIKE
    spec = _toylang_spec()
    res = _batch_validate(CLASSICS_C_LIKE, TOYLANG_DIR, spec)
    assert res is not None
    assert len(res) == len(CLASSICS_C_LIKE)
    assert all(ok for _, ok, _ in res)


def test_batch_validate_returns_none_on_any_mismatch():
    """If one kata's expected output is wrong, the WHOLE batch returns
    None so the caller falls back to per-kata to identify the bad one."""
    from forge.orchestrator.katas import _batch_validate
    spec = _toylang_spec()
    katas = [
        _kata(reference="func a(x) { return x + 1; }\n",
              tests=[{"call": "a(1)", "expected": "2"}]),
        # This one's expected output is wrong:
        _kata(reference="func b(x) { return x; }\n",
              tests=[{"call": "b(1)", "expected": "999"}]),
    ]
    katas[0]["id"] = "a"; katas[1]["id"] = "b"
    res = _batch_validate(katas, TOYLANG_DIR, spec)
    assert res is None


def test_batch_validate_returns_none_on_compile_failure():
    """A reference with a syntax error makes the whole batch fail to compile.
    Returns None so caller knows to drop into per-kata diagnosis mode."""
    from forge.orchestrator.katas import _batch_validate
    spec = _toylang_spec()
    katas = [
        _kata(reference="func a(x) { return x + 1; }\n",
              tests=[{"call": "a(1)", "expected": "2"}]),
        _kata(reference="@@@@ not valid syntax",
              tests=[{"call": "b(1)", "expected": "1"}]),
    ]
    katas[0]["id"] = "a"; katas[1]["id"] = "b"
    res = _batch_validate(katas, TOYLANG_DIR, spec)
    assert res is None


def test_batch_validate_empty_pack_returns_empty():
    """Edge case: zero katas should return [] not None or crash."""
    from forge.orchestrator.katas import _batch_validate
    spec = _toylang_spec()
    assert _batch_validate([], TOYLANG_DIR, spec) == []


def test_api_load_pack_falls_back_to_per_kata_when_batch_fails(tmp_path, monkeypatch):
    """If batch validation returns None (e.g. one bad reference poisons it),
    the endpoint must still produce the right per-kata accept/drop decisions
    via the parallel fallback path. Simulate by injecting a fake pack with
    one bad kata."""
    from forge.gui import app as app_module
    from forge.orchestrator import kata_packs
    import shutil

    fake_workspace = tmp_path / "ws"
    (fake_workspace / "generated").mkdir(parents=True)
    shutil.copytree(
        TOYLANG_DIR, fake_workspace / "generated" / "toylang",
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    # Inject a fake pack with one good + one bad kata.
    fake_pack = {
        "title": "Test pack",
        "description": "for tests",
        "syntax_family": "c_like",
        "katas": [
            {
                "id": "good_one",
                "title": "Good", "difficulty": "easy",
                "problem": "p", "function_name": "g",
                "starter_code": "func g() {}",
                "reference_solution": "func g() { return 42; }\n",
                "tests": [{"call": "g()", "expected": "42"}],
            },
            {
                "id": "bad_one",
                "title": "Bad", "difficulty": "easy",
                "problem": "p", "function_name": "b",
                "starter_code": "func b() {}",
                "reference_solution": "@@@ totally broken syntax",
                "tests": [{"call": "b()", "expected": "1"}],
            },
        ],
    }
    monkeypatch.setitem(kata_packs.PACKS, "test_mixed", fake_pack)

    app = app_module.create_app()
    client = app.test_client()
    r = client.post("/api/katas/toylang/load-pack/test_mixed")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    # Both katas appear in the output now: good_one as a normal kata,
    # bad_one as a stub-rescued kata (so the user always sees every problem
    # even when the reference can't compile in this language).
    by_id = {k["id"]: k for k in data["katas"]}
    assert "good_one" in by_id
    assert "bad_one" in by_id
    assert by_id["good_one"].get("stub_rescued") is not True
    # bad_one's reference can't compile; the fallback ladder now tries
    # case-analysis first (mechanical, always works on valid c_like) and
    # only falls back to stub_rescue if even that fails.
    rescued = by_id["bad_one"]
    assert rescued.get("case_analysis_fallback") or rescued.get("stub_rescued"), (
        f"bad_one wasn't rescued: {rescued}")
    # No drops: stub-rescue saves the bad one
    assert data["dropped"] == []


def test_api_load_pack_rejects_phrasebook_language(tmp_path, monkeypatch):
    """Pre-flight: a c_like pack against a c_like-but-phrasebook language
    (kidX-style) would drop everything because the parser expects
    'make x equal 0.' not 'var x = 0;'. Refuse early with explanation."""
    from forge.gui import app as app_module
    fake_workspace = tmp_path / "ws"
    fake_lang = fake_workspace / "generated" / "kidlike"
    fake_lang.mkdir(parents=True)
    (fake_lang / "resolved_spec.json").write_text(json.dumps({
        "lang_name": "kidlike",
        "file_extension": ".kid",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {
            "natural_language": {
                "var_decl": "make <name> equal <value>.",
                "func_def": "the way to <name> with <params> is <body>.",
            },
        },
    }), encoding="utf-8")
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)
    app = app_module.create_app()
    client = app.test_client()
    r = client.post("/api/katas/kidlike/load-pack/classics?strict=true")
    assert r.status_code == 400
    err = r.get_json()["error"]
    assert "phrasebook" in err.lower()
    assert "make <name> equal" in err


def test_api_load_pack_rejects_no_mutation_ban(tmp_path, monkeypatch):
    """Pre-flight: classics use `i = i + 1` everywhere. A language with
    `no_mutation` in feature_bans can't run any of them. Refuse early."""
    from forge.gui import app as app_module
    fake_workspace = tmp_path / "ws"
    fake_lang = fake_workspace / "generated" / "purely"
    fake_lang.mkdir(parents=True)
    (fake_lang / "resolved_spec.json").write_text(json.dumps({
        "lang_name": "purely",
        "file_extension": ".pure",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"feature_bans": ["no_mutation"]},
    }), encoding="utf-8")
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)
    app = app_module.create_app()
    client = app.test_client()
    r = client.post("/api/katas/purely/load-pack/classics?strict=true")
    assert r.status_code == 400
    err = r.get_json()["error"]
    assert "no_mutation" in err
    assert "strict=true" in err  # tells the caller how to enable translation


def test_api_load_pack_rejects_no_loops_ban(tmp_path, monkeypatch):
    from forge.gui import app as app_module
    fake_workspace = tmp_path / "ws"
    fake_lang = fake_workspace / "generated" / "loopless"
    fake_lang.mkdir(parents=True)
    (fake_lang / "resolved_spec.json").write_text(json.dumps({
        "lang_name": "loopless",
        "file_extension": ".lp",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"feature_bans": ["no_loops"]},
    }), encoding="utf-8")
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)
    app = app_module.create_app()
    client = app.test_client()
    r = client.post("/api/katas/loopless/load-pack/classics?strict=true")
    assert r.status_code == 400
    assert "no_loops" in r.get_json()["error"]


def test_api_load_pack_rejects_syntax_family_mismatch(tmp_path, monkeypatch):
    """A c_like pack against a python_like language would drop everything.
    The endpoint should refuse early with a clear error, not silently save
    an empty pack."""
    from forge.gui import app as app_module
    fake_workspace = tmp_path / "ws"
    fake_lang = fake_workspace / "generated" / "pyish"
    fake_lang.mkdir(parents=True)
    (fake_lang / "resolved_spec.json").write_text(json.dumps({
        "lang_name": "pyish",
        "file_extension": ".py",
        "options": {"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"},
    }), encoding="utf-8")
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    app = app_module.create_app()
    client = app.test_client()
    r = client.post("/api/katas/pyish/load-pack/classics?strict=true")
    assert r.status_code == 400
    msg = r.get_json()["error"]
    assert "c_like" in msg and "python_like" in msg


# ---------------------------------------------------------------------------
# kata_translator: LLM translation fallback for customized languages
# ---------------------------------------------------------------------------

def test_translate_pack_runs_llm_and_validates(tmp_path):
    """The translator should call the LLM with a translation prompt, validate
    each translated kata, and return a partitioned valid/dropped result."""
    from forge.orchestrator.kata_translator import translate_pack
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()
    pack_template = {
        "title": "Mini classics",
        "syntax_family": "c_like",
        "katas": [
            _kata(reference="func double(x) { return x * 2; }\n",
                  tests=[{"call": "double(3)", "expected": "6"}]),
        ],
    }
    pack_template["katas"][0]["id"] = "double"
    pack_template["katas"][0]["function_name"] = "double"

    class StubLLM:
        log_dir = None
        last_tag = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            StubLLM.last_tag = tag
            assert "double" in prompt and "translate" in prompt.lower(), \
                "the translator prompt should include the curated problem"
            # Return a "translation" identical to the source — works on toylang.
            return {"katas": [{
                "id": "double",
                "title": "Test",
                "difficulty": "easy",
                "problem": "test",
                "function_name": "double",
                "starter_code": "func double(x) {}",
                "reference_solution": "func double(x) { return x * 2; }\n",
                "tests": [{"call": "double(3)", "expected": "6"}],
            }]}

    out = translate_pack(pack_template, spec, work, StubLLM(), mechanical=False)
    assert out["dropped"] == []
    assert len(out["katas"]) == 1
    assert StubLLM.last_tag == "kata-translate"


def test_translate_pack_dedupes_when_llm_returns_repeated_ids(tmp_path):
    """The 'load classics on kidX returns 12 copies of two_sum' bug.
    If the LLM returns 12 entries all with id `two_sum`, we should dedup
    to 1 valid kata and record the other 11 originals as omitted drops."""
    from forge.orchestrator.kata_translator import translate_pack
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()

    pack_template = {
        "title": "Three katas",
        "syntax_family": "c_like",
        "katas": [
            {**_kata(reference="func a(x) { return x; }\n",
                     tests=[{"call": "a(1)", "expected": "1"}]),
             "id": "alpha", "function_name": "a"},
            {**_kata(reference="func b(x) { return x; }\n",
                     tests=[{"call": "b(1)", "expected": "1"}]),
             "id": "beta", "function_name": "b"},
            {**_kata(reference="func c(x) { return x; }\n",
                     tests=[{"call": "c(1)", "expected": "1"}]),
             "id": "gamma", "function_name": "c"},
        ],
    }

    class DupingClient:
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            # Confused LLM returns 5 copies of "alpha" and nothing else.
            alpha_entry = {
                "id": "alpha",
                "title": "Alpha", "difficulty": "easy",
                "problem": "p", "function_name": "a",
                "starter_code": "func a(x) {}",
                "reference_solution": "func a(x) { return x; }\n",
                "tests": [{"call": "a(1)", "expected": "1"}],
            }
            return {"katas": [alpha_entry] * 5}

    out = translate_pack(pack_template, spec, work, DupingClient(), mechanical=False,
                         fix_attempts=2)
    # Alpha translates cleanly; beta + gamma get stub-rescued (so the user
    # still SEES every kata even though their references couldn't translate).
    by_id = {k["id"]: k for k in out["katas"]}
    assert set(by_id.keys()) == {"alpha", "beta", "gamma"}
    assert by_id["alpha"].get("stub_rescued") is not True
    assert by_id["alpha"].get("case_analysis_fallback") is not True
    # Beta and gamma get rescued (case-analysis preferred; stub if that
    # also fails). Either way the kata appears, just not as the LLM's
    # original (failed) translation.
    for kid in ("beta", "gamma"):
        k = by_id[kid]
        assert k.get("case_analysis_fallback") or k.get("stub_rescued"), (
            f"{kid} wasn't rescued via fallback ladder: {k}")


def test_translate_pack_drops_unknown_ids_from_llm(tmp_path):
    """If the LLM returns a kata with an id NOT in the input pack, we
    silently drop it (it's not part of the contract). The expected
    originals are still tracked as omitted."""
    from forge.orchestrator.kata_translator import translate_pack
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()
    pack_template = {
        "title": "One kata",
        "syntax_family": "c_like",
        "katas": [
            {**_kata(reference="func real(x) { return x; }\n",
                     tests=[{"call": "real(1)", "expected": "1"}]),
             "id": "real_problem", "function_name": "real"},
        ],
    }

    class MisbehavingClient:
        log_dir = None
        def call_json(self, *a, **kw):
            return {"katas": [
                {  # not in our input list
                    "id": "made_up",
                    "title": "X", "difficulty": "easy",
                    "problem": "p", "function_name": "x",
                    "starter_code": "func x() {}",
                    "reference_solution": "func x() { return 1; }\n",
                    "tests": [{"call": "x()", "expected": "1"}],
                },
            ]}

    out = translate_pack(pack_template, spec, work, MisbehavingClient(), mechanical=False,
                         fix_attempts=2)
    # `made_up` is filtered out (not in our input list).
    valid_ids = {k["id"] for k in out["katas"]}
    assert "made_up" not in valid_ids
    # `real_problem` gets rescued (case-analysis preferred, stub fallback)
    # since the LLM never produced a usable translation for it.
    assert "real_problem" in valid_ids
    real = next(k for k in out["katas"] if k["id"] == "real_problem")
    assert real.get("case_analysis_fallback") or real.get("stub_rescued"), (
        f"real_problem wasn't rescued: {real}")


def test_stub_rescue_produces_savable_kata():
    """The mechanical stub-rescue must always produce a savable kata that
    matches the schema, with empty tests + stub_rescued=True."""
    from forge.orchestrator.kata_translator import _stub_rescue
    original = {
        "id": "tough", "title": "Tough", "difficulty": "hard",
        "problem": "Solve it.", "function_name": "solve",
        "starter_code": "func solve() {}",
        "reference_solution": "func solve() { /* algo */ }",
        "tests": [{"call": "solve()", "expected": "42"}],
    }
    spec = {"comment_syntax": {"line": "//", "block_open": None, "block_close": None}}
    rescued = _stub_rescue(original, spec)
    assert rescued is not None
    assert rescued["id"] == "tough"
    assert rescued["tests"] == []  # no auto-check possible
    assert rescued["stub_rescued"] is True
    # Problem is preserved + flagged
    assert "Solve it." in rescued["problem"]
    assert "auto-check" in rescued["problem"].lower()
    # Reference is a comment-only stub (won't compile-error since we don't
    # validate it — but it's there to satisfy the schema)
    assert rescued["reference_solution"]


def test_stub_rescue_uses_block_comments_when_no_line_comment():
    """Languages with only `/* */` block comments must still work."""
    from forge.orchestrator.kata_translator import _stub_rescue
    original = {
        "id": "x", "title": "X", "difficulty": "easy",
        "problem": "p", "function_name": "f",
        "starter_code": "", "reference_solution": "",
        "tests": [{"call": "f()", "expected": "1"}],
    }
    spec = {"comment_syntax": {"line": None,
                               "block_open": "(*", "block_close": "*)"}}
    rescued = _stub_rescue(original, spec)
    assert rescued is not None
    assert "(*" in rescued["reference_solution"]
    assert "*)" in rescued["reference_solution"]


def test_single_test_reduction_uses_first_test_only(tmp_path):
    """The single-test reduction fallback must shrink the kata to ONE
    test so the LLM only has to handle one input/output pair."""
    from forge.orchestrator.kata_translator import _single_test_reduction
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()
    original = {
        "id": "complex", "title": "C", "difficulty": "hard",
        "problem": "p", "function_name": "fc",
        "starter_code": "func fc() {}",
        "reference_solution": "func fc() { return 1; }\n",
        "tests": [
            {"call": "fc(1)", "expected": "alpha"},
            {"call": "fc(2)", "expected": "beta"},
            {"call": "fc(3)", "expected": "gamma"},
        ],
    }

    captured = {}
    class CaptureClient:
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            captured["prompt"] = prompt
            return {"kata": {
                "id": "complex", "title": "C", "difficulty": "hard",
                "problem": "p", "function_name": "fc",
                "starter_code": "func fc() {}",
                "reference_solution": "func fc(x) { return \"alpha\"; }\n",
                # LLM tries to return 3 tests; we should clamp to 1
                "tests": [
                    {"call": "fc(1)", "expected": "alpha"},
                    {"call": "fc(2)", "expected": "beta"},
                ],
            }}

    cli = CaptureClient()
    result = _single_test_reduction(original, spec, work, "sample", cli)
    assert result is not None
    # Only the FIRST test survives the reduction (matches what the prompt asked for)
    assert len(result["tests"]) == 1
    assert result["tests"][0]["expected"] == "alpha"
    # The prompt mentions "ONE test" / "single" — the LLM should know
    assert "ONE test" in captured["prompt"] or "one test" in captured["prompt"].lower()


def test_translate_pack_safety_net_rescues_omitted_katas(tmp_path):
    """When the batch LLM call only translates SOME of the problems, the
    safety net must do per-kata fresh-translation calls for the rest.
    Verifies the user's complaint: '2 dropped' should retry per-kata."""
    from forge.orchestrator.kata_translator import translate_pack
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()
    pack_template = {
        "title": "Three katas",
        "syntax_family": "c_like",
        "katas": [
            {**_kata(reference="func a(x) { return x + 1; }\n",
                     tests=[{"call": "a(1)", "expected": "2"}]),
             "id": "alpha", "function_name": "a"},
            {**_kata(reference="func b(x) { return x + 2; }\n",
                     tests=[{"call": "b(1)", "expected": "3"}]),
             "id": "beta", "function_name": "b"},
            {**_kata(reference="func c(x) { return x + 3; }\n",
                     tests=[{"call": "c(1)", "expected": "4"}]),
             "id": "gamma", "function_name": "c"},
        ],
    }

    class PartialThenFullClient:
        """Batch call returns only alpha. Per-kata calls succeed for beta + gamma."""
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            # Per-kata calls have tag=="kata-translate-one-<id>"
            if tag.startswith("kata-translate-one-"):
                kid = tag.split("-")[-1]
                refs = {
                    "beta": "func b(x) { return x + 2; }\n",
                    "gamma": "func c(x) { return x + 3; }\n",
                }
                fns = {"beta": "b", "gamma": "c"}
                expecteds = {"beta": "3", "gamma": "4"}
                if kid in refs:
                    return {"kata": {
                        "id": kid, "title": kid.title(), "difficulty": "easy",
                        "problem": "p", "function_name": fns[kid],
                        "starter_code": f"func {fns[kid]}(x) {{}}",
                        "reference_solution": refs[kid],
                        "tests": [{"call": f"{fns[kid]}(1)", "expected": expecteds[kid]}],
                    }}
                return {"kata": None}
            # Batch call: return only alpha
            return {"katas": [{
                "id": "alpha", "title": "Alpha", "difficulty": "easy",
                "problem": "p", "function_name": "a",
                "starter_code": "func a(x) {}",
                "reference_solution": "func a(x) { return x + 1; }\n",
                "tests": [{"call": "a(1)", "expected": "2"}],
            }]}

    out = translate_pack(pack_template, spec, work, PartialThenFullClient(), mechanical=False)
    # Safety net should have rescued beta and gamma. Total = 3 valid, 0 dropped.
    valid_ids = {k["id"] for k in out["katas"]}
    assert valid_ids == {"alpha", "beta", "gamma"}, \
        f"safety net failed; valid={valid_ids}, dropped={out['dropped']}"
    assert out["dropped"] == []


def test_escalating_fix_uses_attempt_specific_strategies():
    """Each fix-up attempt uses a different prompt — that's the whole point
    of escalation. Verify by inspecting the tag the LLM is called with."""
    from forge.orchestrator.kata_translator import _escalating_fix
    spec = {"options": {"syntax": "c_like"}}
    kata = {"id": "test", "function_name": "f",
            "tests": [{"call": "f()", "expected": "1"}],
            "reference_solution": "broken"}

    captured_tags = []
    captured_prompts = []
    class Inspector:
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            captured_tags.append(tag)
            captured_prompts.append(prompt)
            return {"reference_solution": f"// attempt {len(captured_tags)}"}

    cli = Inspector()
    for n in (1, 2, 3, 4, 5):
        _escalating_fix(kata, "syntax error", spec, "sample", cli, n)
    # Each attempt uses a DIFFERENT prompt
    for i in range(1, 5):
        assert captured_prompts[i] != captured_prompts[0], \
            f"attempt {i+1} prompt is identical to attempt 1"
    # Tags carry the attempt number
    for n, tag in enumerate(captured_tags, start=1):
        assert f"a{n}" in tag, f"expected tag to contain a{n}, got {tag}"
    # The 5th (safety-net) prompt mentions case analysis — that's the
    # turing-completeness fallback.
    assert "case analysis" in captured_prompts[4].lower() or \
           "hardcoded" in captured_prompts[4].lower()


def test_translate_pack_drops_when_everything_fails(tmp_path):
    """Sanity check: if both batch AND per-kata translation can't produce
    valid output, the kata still appears in `dropped` (no silent loss)."""
    from forge.orchestrator.kata_translator import translate_pack
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()
    pack_template = {
        "title": "One kata",
        "syntax_family": "c_like",
        "katas": [
            {**_kata(reference="func t() { return 1; }\n",
                     tests=[{"call": "t()", "expected": "1"}]),
             "id": "stubborn", "function_name": "t"},
        ],
    }

    class AlwaysBrokenClient:
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            if tag.startswith("kata-translate-one-"):
                # Per-kata also returns broken syntax
                return {"kata": {
                    "id": "stubborn", "title": "X", "difficulty": "easy",
                    "problem": "p", "function_name": "t",
                    "starter_code": "func t() {}",
                    "reference_solution": "@@@@ broken syntax @@@@",
                    "tests": [{"call": "t()", "expected": "1"}],
                }}
            if tag.startswith("kata-fix-"):
                return {"reference_solution": "@@@@ still broken @@@@"}
            # Batch: also broken
            return {"katas": [{
                "id": "stubborn", "title": "X", "difficulty": "easy",
                "problem": "p", "function_name": "t",
                "starter_code": "func t() {}",
                "reference_solution": "@@@@ broken @@@@",
                "tests": [{"call": "t()", "expected": "1"}],
            }]}

    out = translate_pack(pack_template, spec, work, AlwaysBrokenClient(), mechanical=False,
                         fix_attempts=2)  # speed up the test
    # New rescue policy: even when EVERYTHING fails, the kata is saved via
    # the fallback ladder (case-analysis preferred; stub_rescue as last
    # resort) so the user still SEES the problem. Dropping a kata entirely
    # is the absolute last resort.
    assert len(out["katas"]) == 1
    k = out["katas"][0]
    assert k["id"] == "stubborn"
    assert k.get("case_analysis_fallback") or k.get("stub_rescued"), (
        f"kata wasn't rescued: {k}")
    # No drops: rescue ladder saves it.
    assert out["dropped"] == []


def test_case_analysis_fallback_produces_working_kata(tmp_path):
    """The case-analysis fallback should always produce a kata with a
    reference solution that passes self-validation, by hardcoding the
    answer for each test."""
    from forge.orchestrator.case_analysis import build_case_analysis_kata
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()

    # A simple kata with primitive args: discriminator works trivially
    kata = {
        **_kata(reference="func double(x) { return x * 2; }\n",
                tests=[
                    {"call": "double(3)", "expected": "6"},
                    {"call": "double(5)", "expected": "10"},
                ]),
        "id": "double_test", "function_name": "double",
    }
    result = build_case_analysis_kata(kata, spec, work, TOYLANG_DIR)
    assert result is not None
    assert result.get("case_analysis_fallback") is True
    # Reference must be different from the canonical (it's a case-analysis
    # not the algorithm)
    assert result["reference_solution"] != kata["reference_solution"]
    # Tests survive
    assert len(result["tests"]) == 2


def test_case_analysis_returns_none_for_unparseable_reference(tmp_path):
    """If we can't extract function params from the canonical reference,
    case-analysis bails (returns None) so caller falls back to stub-rescue."""
    from forge.orchestrator.case_analysis import build_case_analysis_kata
    spec = _toylang_spec()
    kata = {
        **_kata(reference="@@@@ totally broken syntax",
                tests=[{"call": "x()", "expected": "1"}]),
        "id": "broken", "function_name": "x",
    }
    result = build_case_analysis_kata(kata, spec, TOYLANG_DIR, TOYLANG_DIR)
    assert result is None


def test_mechanical_transpile_emits_phrasebook_form():
    """c_like → phrasebook transpile via the spec's natural_language templates.
    A simple `func double(x) { return x * 2; }` should emit the kidX form."""
    from forge.orchestrator.mechanical_translator import transpile
    spec = {
        "options": {"syntax": "c_like"},
        "statement_terminator": ";",
        "customization": {
            "natural_language": {
                "var_decl": "make <name> equal <value>.",
                "func_def": "the way to <name> with <params> is <body>.",
                "if_stmt": "when <cond> do <body> else <else>.",
                "while_stmt": "keep doing <body> while <cond>.",
                "return_stmt": "the answer is <value>.",
                "true_word": "true", "false_word": "false",
                "null_word": "nope",
                "and_word": "and", "or_word": "or", "not_word": "not",
            },
        },
    }
    out = transpile("func double(x) { return x * 2; }\n", spec)
    assert out is not None
    assert "the way to double with x is" in out
    assert "the answer is x * 2." in out


def test_mechanical_transpile_emits_clike_for_vanilla():
    """Vanilla c_like (no phrasebook) round-trips identically up to formatting."""
    from forge.orchestrator.mechanical_translator import transpile
    spec = {"options": {"syntax": "c_like"}, "statement_terminator": ";",
            "customization": {}}
    src = "func add(a, b) { return a + b; }\n"
    out = transpile(src, spec)
    assert out is not None
    assert "func add(a, b)" in out
    assert "return a + b" in out


def test_mechanical_python_like_emit():
    """PythonLikeBackend should emit def/return/colon/indent style with the
    spec's keywords for var/null/booleans."""
    from forge.orchestrator.mechanical_translator import transpile
    spec = {
        "options": {"syntax": "python_like", "typing": "dynamic"},
        "statement_terminator": "newline",
        "function_definition": {"keyword": "def"},
        "variable_declaration": {"keyword": "let"},
        "boolean_keywords": {"true": "True", "false": "False"},
        "null_keyword": "None",
        "customization": {},
    }
    src = (
        "func add(a, b) {\n"
        "    var c = a + b;\n"
        "    if (c > 0) { return c; }\n"
        "    return 0;\n"
        "}\n"
    )
    out = transpile(src, spec)
    assert out is not None
    # def keyword + colon + no semicolons + indented body
    assert "def add(a, b):" in out
    assert "let c = a + b" in out
    assert "if c > 0:" in out
    assert "return c" in out
    # No braces or semicolons leaked through
    assert "{" not in out and "}" not in out
    assert ";" not in out


def test_mechanical_can_handle_returns_backend_for_supported():
    """can_handle returns a Backend for supported language types."""
    from forge.orchestrator.mechanical_translator import (
        can_handle, CLikeBackend, PhrasebookBackend, PythonLikeBackend,
    )
    # vanilla c_like + dynamic
    c_spec = {"options": {"syntax": "c_like", "typing": "dynamic"},
              "customization": {}}
    assert isinstance(can_handle(c_spec), CLikeBackend)

    # phrasebook c_like + dynamic
    pb_spec = {"options": {"syntax": "c_like", "typing": "dynamic"},
               "customization": {"natural_language": {"var_decl": "make x."}}}
    assert isinstance(can_handle(pb_spec), PhrasebookBackend)

    # python_like + dynamic (no phrasebook)
    py_spec = {"options": {"syntax": "python_like", "typing": "dynamic"},
               "customization": {}}
    assert isinstance(can_handle(py_spec), PythonLikeBackend)


def test_mechanical_can_handle_returns_none_for_unsupported():
    """Static-typed and feature-banned languages bail out so caller falls back to LLM."""
    from forge.orchestrator.mechanical_translator import can_handle

    # Static typing requires type annotations; mechanical can't infer them.
    static_spec = {"options": {"syntax": "c_like", "typing": "static"},
                   "customization": {}}
    assert can_handle(static_spec) is None

    no_mut_spec = {"options": {"syntax": "c_like", "typing": "dynamic"},
                   "customization": {"feature_bans": ["no_mutation"]}}
    assert can_handle(no_mut_spec) is None

    no_loops_spec = {"options": {"syntax": "c_like", "typing": "dynamic"},
                     "customization": {"feature_bans": ["no_loops"]}}
    assert can_handle(no_loops_spec) is None

    # python_like + phrasebook = bail (rare combo, LLM is safer)
    py_pb_spec = {"options": {"syntax": "python_like", "typing": "dynamic"},
                  "customization": {"natural_language": {"var_decl": "make x."}}}
    assert can_handle(py_pb_spec) is None


def test_mechanical_transpile_rederives_expected_outputs(tmp_path):
    """After transpile, expected outputs are re-derived by running the
    reference. Absorbs print-formatter differences (e.g. kidX prints
    list("a") as ['a'] instead of toylang's [a])."""
    from forge.orchestrator.mechanical_translator import transpile_and_validate
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()
    # Kata with deliberately WRONG expected outputs — re-derivation should
    # replace them with the actual stdout from the reference.
    kata = _kata(
        reference="func double(x) { return x * 2; }\n",
        tests=[
            {"call": "double(3)", "expected": "WRONG_VALUE"},
            {"call": "double(5)", "expected": "ALSO_WRONG"},
        ],
    )
    kata["function_name"] = "double"
    translated, reason = transpile_and_validate(kata, spec, work)
    assert translated is not None, reason
    # Expected outputs got re-derived from the actual run.
    assert translated["tests"][0]["expected"] == "6"
    assert translated["tests"][1]["expected"] == "10"


def test_ensure_runtime_string_support_patches_unsupported(tmp_path):
    """Generated languages whose toy_get raises on strings should be
    patched to handle them like toylang's runtime does. Without this, the
    string-iteration classics (valid_parens, anagram, longest_unique) drop."""
    from forge.orchestrator.mechanical_translator import ensure_runtime_string_support
    rt = tmp_path / "runtime.py"
    rt.write_text(
        "def toy_get(coll, k, default=None):\n"
        "    if isinstance(coll, list):\n"
        "        return coll[k]\n"
        "    if isinstance(coll, dict):\n"
        "        return coll.get(k, default)\n"
        "    raise TypeError(f\"get(): unsupported type {type(coll).__name__}\")\n",
        encoding="utf-8",
    )
    patched = ensure_runtime_string_support(tmp_path)
    assert patched is True
    new = rt.read_text(encoding="utf-8")
    assert "isinstance(coll, str)" in new
    assert "forge-patch" in new
    # Indentation must match — block at 4-space indent inside the function
    assert "    if isinstance(coll, str):\n" in new
    assert "        if isinstance(k, int) and 0 <= k < len(coll):\n" in new


def test_ensure_runtime_string_support_idempotent(tmp_path):
    """Running the patcher twice should be a no-op (matched marker)."""
    from forge.orchestrator.mechanical_translator import ensure_runtime_string_support
    rt = tmp_path / "runtime.py"
    rt.write_text(
        "def toy_get(coll, k, default=None):\n"
        "    if isinstance(coll, list):\n"
        "        return coll[k]\n"
        "    raise TypeError('nope')\n",
        encoding="utf-8",
    )
    assert ensure_runtime_string_support(tmp_path) is True
    first = rt.read_text(encoding="utf-8")
    assert ensure_runtime_string_support(tmp_path) is True
    second = rt.read_text(encoding="utf-8")
    assert first == second  # second pass changes nothing


def test_ensure_runtime_string_support_skips_already_supported(tmp_path):
    """A runtime that already handles strings should be marked + left alone."""
    from forge.orchestrator.mechanical_translator import ensure_runtime_string_support
    rt = tmp_path / "runtime.py"
    rt.write_text(
        "def toy_get(coll, k, default=None):\n"
        "    if isinstance(coll, str):\n"
        "        return coll[k]\n"
        "    raise TypeError('nope')\n",
        encoding="utf-8",
    )
    assert ensure_runtime_string_support(tmp_path) is True
    # Marker added, body untouched
    new = rt.read_text(encoding="utf-8")
    assert "forge-patch" in new
    assert new.count("if isinstance(coll, str):") == 1


def test_ensure_runtime_string_support_returns_false_for_missing_runtime(tmp_path):
    """If runtime.py doesn't exist, return False instead of raising."""
    from forge.orchestrator.mechanical_translator import ensure_runtime_string_support
    assert ensure_runtime_string_support(tmp_path / "nope") is False


def test_translate_pack_skips_llm_when_mechanical_succeeds_for_all(tmp_path):
    """If mechanical handles every kata, the LLM should not be called."""
    from forge.orchestrator.kata_translator import translate_pack
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()
    pack_template = {
        "title": "Trivial",
        "syntax_family": "c_like",
        "katas": [
            {**_kata(reference="func a() { return 1; }\n",
                     tests=[{"call": "a()", "expected": "1"}]),
             "id": "ax", "function_name": "a"},
        ],
    }

    class ShouldNeverCall:
        log_dir = None
        def call_json(self, *a, **kw):
            raise AssertionError("LLM was called when mechanical should suffice")

    out = translate_pack(pack_template, spec, work, ShouldNeverCall())
    assert len(out["katas"]) == 1
    assert out["katas"][0]["id"] == "ax"
    assert out["dropped"] == []


def test_translate_pack_uses_dynamic_schema_size(tmp_path):
    """The translator must NOT use the 8-item cap from KATA_PACK_SCHEMA.
    It must build a schema sized for the input pack, otherwise the LLM is
    told its 12-item response is over the limit and the bug returns."""
    from forge.orchestrator.kata_translator import translate_pack
    from forge.orchestrator.kata_packs import CLASSICS_C_LIKE
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()
    pack_template = {"title": "Big", "syntax_family": "c_like",
                     "katas": CLASSICS_C_LIKE}

    captured_schema = {}
    class SchemaInspector:
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            captured_schema["max"] = schema["properties"]["katas"].get("maxItems")
            captured_schema["min"] = schema["properties"]["katas"].get("minItems")
            return {"katas": []}

    translate_pack(pack_template, spec, work, SchemaInspector(), mechanical=False)
    # 12 classics → schema must allow at least 12.
    assert captured_schema["max"] >= len(CLASSICS_C_LIKE), (
        f"schema cap {captured_schema['max']} < {len(CLASSICS_C_LIKE)} classics — "
        "this is the bug that caused '12 of two_sum'"
    )


def test_translate_pack_drops_when_llm_omits_a_problem(tmp_path):
    """If the LLM forgets to translate a kata, that kata should appear in
    `dropped` with a 'model omitted' reason."""
    from forge.orchestrator.kata_translator import translate_pack
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(
        TOYLANG_DIR, work,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    spec = _toylang_spec()

    pack_template = {
        "title": "Two katas",
        "syntax_family": "c_like",
        "katas": [
            {**_kata(reference="func a(x) { return x + 1; }\n",
                     tests=[{"call": "a(1)", "expected": "2"}]),
             "id": "kept", "function_name": "a"},
            {**_kata(reference="func b(x) { return x; }\n",
                     tests=[{"call": "b(1)", "expected": "1"}]),
             "id": "missing", "function_name": "b"},
        ],
    }

    class HalfClient:
        log_dir = None
        def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
            return {"katas": [{
                "id": "kept",
                "title": "kept", "difficulty": "easy",
                "problem": "test", "function_name": "a",
                "starter_code": "func a(x) {}",
                "reference_solution": "func a(x) { return x + 1; }\n",
                "tests": [{"call": "a(1)", "expected": "2"}],
            }]}

    out = translate_pack(pack_template, spec, work, HalfClient(), mechanical=False,
                         fix_attempts=2)
    # `kept` translates cleanly. `missing` gets rescued via the fallback
    # ladder (case-analysis preferred, stub if that fails too).
    by_id = {k["id"]: k for k in out["katas"]}
    assert set(by_id.keys()) == {"kept", "missing"}
    assert by_id["kept"].get("stub_rescued") is not True
    assert by_id["kept"].get("case_analysis_fallback") is not True
    miss = by_id["missing"]
    assert miss.get("case_analysis_fallback") or miss.get("stub_rescued"), (
        f"missing kata wasn't rescued: {miss}")


def test_api_load_pack_falls_through_to_translation(tmp_path, monkeypatch):
    """End-to-end: posting load-pack against a phrasebook language (without
    strict=true) should trigger LLM translation. The handler must route
    to translate_pack rather than refuse with 400."""
    from forge.gui import app as app_module
    from forge.orchestrator import providers, kata_translator

    # Minimal fake language: spec only, no compile.py — we stub the
    # translator so no real validation runs either.
    fake_workspace = tmp_path / "ws"
    fake_lang = fake_workspace / "generated" / "kidlike"
    fake_lang.mkdir(parents=True)
    spec = {
        "lang_name": "kidlike",
        "file_extension": ".kid",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {
            "natural_language": {"var_decl": "make <name> equal <value>."},
        },
    }
    (fake_lang / "resolved_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    class FakeClient:
        log_dir = None
        def call_json(self, *a, **kw): return {"katas": []}

    monkeypatch.setattr(providers, "make_client", lambda *a, **kw: FakeClient())

    # Stub translate_pack to confirm routing without firing an LLM. Returns
    # one fake-validated kata.
    translate_calls = []
    def fake_translate(pack_template, _spec, _lang_dir, _client, **kw):
        translate_calls.append(pack_template["title"])
        return {"katas": [{"id": "fake_kata", "title": "Fake"}], "dropped": []}
    monkeypatch.setattr(kata_translator, "translate_pack", fake_translate)

    app = app_module.create_app()
    client = app.test_client()
    r = client.post("/api/katas/kidlike/load-pack/classics")
    assert r.status_code == 200, r.get_json()
    data = r.get_json()
    assert data["source"].startswith("translated:"), data["source"]
    assert len(translate_calls) == 1, "translate_pack should have been called"
    assert data["katas"][0]["id"] == "fake_kata"


def test_api_load_pack_caches_translated_pack(tmp_path, monkeypatch):
    """The second load-pack call for the same pack/lang should return the
    cached katas.json without re-running translation. The translator must
    NOT be invoked on the second call."""
    from forge.gui import app as app_module
    from forge.orchestrator import providers, kata_translator

    fake_workspace = tmp_path / "ws"
    fake_lang = fake_workspace / "generated" / "kidlike"
    fake_lang.mkdir(parents=True)
    (fake_lang / "resolved_spec.json").write_text(json.dumps({
        "lang_name": "kidlike",
        "file_extension": ".kid",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"natural_language": {"var_decl": "make X."}},
    }), encoding="utf-8")
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    class FakeClient:
        log_dir = None
        def call_json(self, *a, **kw): return {"katas": []}
    monkeypatch.setattr(providers, "make_client", lambda *a, **kw: FakeClient())

    translate_invocations = []
    def fake_translate(*a, **kw):
        translate_invocations.append(1)
        return {"katas": [{"id": "t1", "title": "T1"}], "dropped": []}
    monkeypatch.setattr(kata_translator, "translate_pack", fake_translate)

    app = app_module.create_app()
    client = app.test_client()

    # First call: translation runs.
    r1 = client.post("/api/katas/kidlike/load-pack/classics")
    assert r1.status_code == 200
    assert len(translate_invocations) == 1
    assert r1.get_json().get("cached") is not True

    # Second call: cache hit, translation does NOT run again.
    r2 = client.post("/api/katas/kidlike/load-pack/classics")
    assert r2.status_code == 200
    assert len(translate_invocations) == 1, "cache hit should skip translation"
    assert r2.get_json().get("cached") is True

    # ?force=true: bypass cache, translation runs again.
    r3 = client.post("/api/katas/kidlike/load-pack/classics?force=true")
    assert r3.status_code == 200
    assert len(translate_invocations) == 2, "?force=true should bypass cache"


def test_api_load_pack_cache_only_matches_same_pack_key(tmp_path, monkeypatch):
    """Cache should only fire on the same pack key — loading a different
    pack must not return the previous one."""
    from forge.gui import app as app_module
    from forge.orchestrator import providers, kata_translator, kata_packs
    import shutil

    fake_workspace = tmp_path / "ws"
    fake_lang = fake_workspace / "generated" / "toylang"
    shutil.copytree(
        TOYLANG_DIR, fake_lang,
        ignore=shutil.ignore_patterns(".forge_log", "__pycache__",
                                      "_playground", "*.out.py", "katas.json"),
    )
    # Pre-seed katas.json with a "previous" pack so we can verify the new
    # pack key forces a fresh load.
    (fake_lang / "katas.json").write_text(json.dumps({
        "lang": "toylang", "source": "curated:other",
        "katas": [{"id": "prev_kata"}], "dropped": [],
    }), encoding="utf-8")
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    # Defense: stub make_client + translate_pack so a misrouted call won't
    # fire a real LLM.
    class FakeClient:
        log_dir = None
        def call_json(self, *a, **kw): return {"katas": []}
    monkeypatch.setattr(providers, "make_client", lambda *a, **kw: FakeClient())
    monkeypatch.setattr(kata_translator, "translate_pack",
                        lambda *a, **kw: {"katas": [], "dropped": []})

    # Inject a tiny but VALID c_like pack (one trivial kata that compiles).
    monkeypatch.setitem(kata_packs.PACKS, "minimal", {
        "title": "Minimal",
        "description": "test pack",
        "syntax_family": "c_like",
        "katas": [{
            "id": "tiny_kata",
            "title": "Tiny",
            "difficulty": "easy",
            "problem": "p",
            "function_name": "tiny",
            "starter_code": "func tiny() {}",
            "reference_solution": "func tiny() { return 7; }\n",
            "tests": [{"call": "tiny()", "expected": "7"}],
        }],
    })

    app = app_module.create_app()
    client = app.test_client()
    # Ask for "minimal" — should NOT return prev_kata (different source key).
    r = client.post("/api/katas/toylang/load-pack/minimal")
    data = r.get_json()
    assert r.status_code == 200, data
    ids = [k.get("id") for k in data.get("katas", [])]
    assert "prev_kata" not in ids
    assert "tiny_kata" in ids
    # Should not have served the "curated:other" pack from cache.
    assert data.get("cached") is not True


def test_api_load_pack_falls_through_for_no_mutation(tmp_path, monkeypatch):
    """Same routing check for a feature-banned language: no_mutation must
    trigger translation, not pre-flight rejection."""
    from forge.gui import app as app_module
    from forge.orchestrator import providers, kata_translator

    fake_workspace = tmp_path / "ws"
    fake_lang = fake_workspace / "generated" / "purely"
    fake_lang.mkdir(parents=True)
    (fake_lang / "resolved_spec.json").write_text(json.dumps({
        "lang_name": "purely",
        "file_extension": ".pure",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"feature_bans": ["no_mutation"]},
    }), encoding="utf-8")
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    class FakeClient:
        log_dir = None
        def call_json(self, *a, **kw): return {"katas": []}
    monkeypatch.setattr(providers, "make_client", lambda *a, **kw: FakeClient())

    monkeypatch.setattr(kata_translator, "translate_pack",
                        lambda *a, **kw: {"katas": [{"id": "ok"}], "dropped": []})

    app = app_module.create_app()
    client = app.test_client()
    r = client.post("/api/katas/purely/load-pack/classics")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["source"].startswith("translated:")
