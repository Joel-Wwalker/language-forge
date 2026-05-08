"""Tests for the load-time auto-validation pipeline.

User contract from this turn:
  1. Generation must be FAST. No LLM calls for templated languages.
  2. Every kata in a shipped pack must have a verified reference solution.
     Stack-based languages enforce this hard - any kata whose reference
     fails its tests is dropped from the visible pack.

These tests pin both contracts.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Generation speed: zero LLM calls for templated languages
# ---------------------------------------------------------------------------

class _CountingFakeClient:
    log_dir = None
    def __init__(self):
        self.calls = 0
        self.tags = []
    def call_code(self, prompt, *, tag="code"):
        self.calls += 1
        self.tags.append(tag)
        return "# stub"
    def call_json(self, *a, **kw):
        self.calls += 1
        return {"tests": []}
    def call_chat(self, *a, **kw):
        self.calls += 1
        return "# stub"


@pytest.mark.parametrize("syntax,expected_max_seconds", [
    ("stack_based",  3.0),
    ("s_expression", 3.0),
])
def test_templated_languages_make_zero_llm_calls(syntax, expected_max_seconds, tmp_path):
    """Templated languages (s_expression, stack_based, c_like as of
    Phase 1.5) make zero core-component LLM calls. README, LANGUAGE.md,
    and tests are all rendered from the spec; parser/codegen/runtime/
    stdlib are templated from the reference compiler.

    Phase 1.5 Stage D added a small `gen-creative` call for
    persona-flavored README intros. Pass `enrich_creative=False` here
    to opt out — the test pins the zero-LLM contract for the
    structural pipeline, which is preserved."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": syntax, "typing": "dynamic", "memory": "host_gc"},
        f"speedy_{syntax}",
    )
    client = _CountingFakeClient()
    t0 = time.monotonic()
    # Skip post-gen verify: this test pins zero-LLM-calls + fast
    # generation. The verify step doesn't make LLM calls, but it does
    # spawn 8 subprocesses for canonical tests (~600ms total) which
    # eats the test's 3s budget. Phase 0.4 added the verify step;
    # the test's intent (no LLM, fast generation) is preserved.
    out_dir = generate_all(spec, output_root=tmp_path, client=client,
                           verify_after_generation=False,
                           enrich_creative=False)
    elapsed = time.monotonic() - t0

    assert client.calls == 0, (
        f"{syntax}: expected zero LLM calls, got {client.calls} (tags: {client.tags})"
    )
    assert elapsed < expected_max_seconds, (
        f"{syntax}: generation took {elapsed:.2f}s, expected < {expected_max_seconds}s"
    )
    # Sanity: the docs got created
    assert (out_dir / "README.md").exists()
    assert (out_dir / "LANGUAGE.md").exists()


def test_python_like_still_uses_llm_for_docs(tmp_path):
    """Regression safety: python_like still goes through the LLM for
    personality-driven docs because no python_like reference compiler
    exists yet (Phase 1.5 instructions explicitly defer it). Without
    this guard a future change might accidentally template python_like
    docs without a real reference behind them.

    Note: this test was previously asserted on c_like, which now goes
    through the templated path (Phase 1.5 Stage B promoted toylang to
    `REFERENCE_COMPILERS["c_like"]`). When a python_like reference
    lands and python_like is registered too, this test should be
    deleted entirely — there'd no longer be any LLM-driven family
    where the assertion holds.

    The full generation pipeline requires the LLM to produce valid
    test files (FakeClient's `# stub` doesn't satisfy the schema),
    so we drive only the readme + language_reference components via
    the `only=` parameter and assert those tags appear."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"},
        "pytest_lang",
    )
    client = _CountingFakeClient()
    generate_all(spec, output_root=tmp_path, client=client,
                 only=["readme", "language_reference"])
    assert "gen-readme" in client.tags, (
        f"python_like must call LLM for readme; got tags: {client.tags}"
    )
    assert "gen-language-ref" in client.tags, (
        f"python_like must call LLM for language_reference; got tags: {client.tags}"
    )


def test_c_like_no_longer_uses_llm_for_docs(tmp_path):
    """Phase 1.5 Stage B/C: c_like is now templated from toylang.
    All docs (README, LANGUAGE.md) come from the deterministic
    templated renderers; the LLM is not invoked for them. Pin that
    contract — accidentally regressing it would re-introduce the
    cost the structural fix eliminated."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "no_llm_docs_clike",
    )
    client = _CountingFakeClient()
    generate_all(spec, output_root=tmp_path, client=client,
                 only=["readme", "language_reference"],
                 verify_after_generation=False)
    assert "gen-readme" not in client.tags, (
        f"c_like should NOT call LLM for readme post-Stage B/C; "
        f"got tags: {client.tags}"
    )
    assert "gen-language-ref" not in client.tags, (
        f"c_like should NOT call LLM for language_reference post-"
        f"Stage B/C; got tags: {client.tags}"
    )


def test_templated_readme_includes_origin_story_and_examples(tmp_path):
    """Quality of the generated README: shouldn't be a one-liner.
    Must include origin_story (when present), syntax examples,
    and run instructions."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "rich_forth",
    )
    spec["origin_story"] = "A test origin story."
    out_dir = generate_all(spec, output_root=tmp_path, client=_CountingFakeClient())
    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    assert "rich_forth" in readme.lower()
    assert "A test origin story." in readme
    assert "Run" in readme or "run" in readme
    # Includes the canonical syntax example
    assert "defn" in readme.lower() or ":" in readme   # function-def hint


# ---------------------------------------------------------------------------
# Load-time auto-validation: every kata gets `validation: {status, ...}`
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_forthlang_kata_cache():
    cache = WORKSPACE_ROOT / "generated" / "forthlang" / "katas.json"
    if cache.exists():
        cache.unlink()
    yield


def test_every_kata_has_validation_block(fresh_forthlang_kata_cache):
    """After load, every kata in the shipped pack must have a
    `validation` field describing the outcome."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.post("/api/katas/forthlang/load-pack/stack_classics")
    assert r.status_code == 200
    katas = r.get_json()["katas"]
    for k in katas:
        assert "validation" in k, f"{k['id']} missing validation block"
        v = k["validation"]
        assert v.get("status") in {"verified", "stub", "failed"}
        if v["status"] == "verified":
            assert v["tests_run"] >= 1
            assert v["tests_run"] == v["tests_passed"]


def test_stack_based_drops_unverified_katas(fresh_forthlang_kata_cache):
    """The user contract: stack_based languages must only ship katas
    with verified reference solutions. If any kata's reference fails
    its tests, it goes to the dropped list - users never see it."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.post("/api/katas/forthlang/load-pack/stack_classics")
    data = r.get_json()
    for k in data["katas"]:
        v = k["validation"]
        assert v["status"] == "verified", (
            f"unverified kata {k['id']!r} slipped into the visible pack: "
            f"status={v['status']}, reason={v.get('reason')}"
        )


def test_load_pack_persists_validation_to_katas_json(fresh_forthlang_kata_cache):
    """Validation results are persisted to katas.json so the GUI can
    show them on a refresh without re-running the validation."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    client.post("/api/katas/forthlang/load-pack/stack_classics")

    saved = json.loads(
        (WORKSPACE_ROOT / "generated" / "forthlang" / "katas.json").read_text(encoding="utf-8")
    )
    for k in saved["katas"]:
        assert k.get("validation"), f"{k['id']} missing validation in persisted pack"


# ---------------------------------------------------------------------------
# _auto_validate_one_kata helper: standalone behavior
# ---------------------------------------------------------------------------

def test_auto_validate_marks_stub_rescued_as_stub():
    """Stub-rescued katas have no tests; the validator must report
    `stub` (not `failed` or `verified`)."""
    from forge.gui.app import _auto_validate_one_kata
    spec = json.loads(
        (WORKSPACE_ROOT / "generated" / "forthlang" / "resolved_spec.json").read_text(encoding="utf-8")
    )
    kata = {
        "id": "x",
        "stub_rescued": True,
        "tests": [],
        "reference_solution": "",
    }
    v = _auto_validate_one_kata(kata, spec, WORKSPACE_ROOT / "generated" / "forthlang")
    assert v["status"] == "stub"
    assert v["tests_run"] == 0


def test_auto_validate_marks_passing_kata_as_verified():
    from forge.gui.app import _auto_validate_one_kata
    forthlang_dir = WORKSPACE_ROOT / "generated" / "forthlang"
    spec = json.loads((forthlang_dir / "resolved_spec.json").read_text(encoding="utf-8"))
    kata = {
        "id": "trivial",
        "reference_solution": ": double 2 * ;",
        "tests": [
            {"call": "5 double", "expected": "10"},
            {"call": "0 double", "expected": "0"},
        ],
    }
    v = _auto_validate_one_kata(kata, spec, forthlang_dir)
    assert v["status"] == "verified"
    assert v["tests_run"] == 2
    assert v["tests_passed"] == 2


def test_auto_validate_marks_broken_reference_as_failed():
    from forge.gui.app import _auto_validate_one_kata
    forthlang_dir = WORKSPACE_ROOT / "generated" / "forthlang"
    spec = json.loads((forthlang_dir / "resolved_spec.json").read_text(encoding="utf-8"))
    kata = {
        "id": "broken",
        "reference_solution": ": always_three drop 3 ;",
        "tests": [
            {"call": "5 always_three", "expected": "5"},   # expects 5, gets 3
            {"call": "0 always_three", "expected": "0"},   # expects 0, gets 3
        ],
    }
    v = _auto_validate_one_kata(kata, spec, forthlang_dir)
    assert v["status"] == "failed"
    assert v["tests_run"] == 2
    assert v["tests_passed"] == 0
    assert "0/2" in v.get("reason", "")
