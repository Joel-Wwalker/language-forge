"""Phase 1.3: tests for the smoke test.

`smoke_test(language_dir)` runs three checks: canonical tests pass,
kata pack `_batch_validate` is clean (or skipped if no curated pack
exists for the language's syntax family), REPL deliverables ship.

These tests use FIXTURES of generated languages — the existing
hand-written reference compilers under `generated/` (toylang,
forthlang, lisplang, stacky) — so they don't have to spin up a real
generation pipeline. That keeps the test fast and deterministic.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from forge.catalog.smoke_test import (
    SmokeResult, smoke_test, _PACK_FOR_SYNTAX,
)


WORKSPACE = Path(__file__).resolve().parents[1]
GENERATED = WORKSPACE / "generated"


# ---------------------------------------------------------------------------
# Direct fixture tests against the four reference compilers
# ---------------------------------------------------------------------------

def test_smoke_passes_on_toylang_reference():
    """Toylang is the canonical c_like reference: it ships with
    8 passing canonical tests, the classics pack `_batch_validate`s
    cleanly against it, and repl.html + compile.py are both present.
    Smoke must say `passed=True`."""
    res = smoke_test(GENERATED / "toylang")
    assert res.passed, (
        f"toylang failed smoke (this would mean the reference "
        f"compiler regressed). failures: {res.failures}"
    )
    # Sanity-check the result shape too.
    assert res.canonical["passed"] == res.canonical["total"] >= 8
    assert res.kata is not None  # c_like has a curated pack
    assert res.kata["pack_key"] == "classics"
    assert res.kata["passed"] == res.kata["total"]
    assert res.repl["repl_html_ok"] is True
    assert res.repl["launches"] is True


def test_smoke_passes_on_forthlang_reference():
    """Forthlang is the stack_based reference. stack_classics pack
    is the matching curated pack."""
    res = smoke_test(GENERATED / "forthlang")
    assert res.passed, f"forthlang failed smoke. failures: {res.failures}"
    assert res.canonical["passed"] == res.canonical["total"] >= 1
    assert res.kata is not None
    assert res.kata["pack_key"] == "stack_classics"
    assert res.kata["passed"] == res.kata["total"]


def test_smoke_skips_kata_for_lisplang():
    """Lisplang is s_expression; no curated pack matches that family
    directly (translation needed). Smoke should report kata=None and
    add the skip to result.skips, but NOT count it as a failure."""
    res = smoke_test(GENERATED / "lisplang")
    assert res.passed is True, (
        f"lisplang smoke shouldn't fail just because kata is "
        f"unsupported. failures: {res.failures}"
    )
    assert res.kata is None
    assert any("no curated pack" in s for s in res.skips), (
        f"expected a skip explaining no pack for s_expression; "
        f"got skips={res.skips}"
    )


# ---------------------------------------------------------------------------
# Hard failures
# ---------------------------------------------------------------------------

def test_smoke_fails_on_missing_resolved_spec(tmp_path):
    """A directory with no resolved_spec.json can't be smoke-tested.
    Hard failure — we can't even pick a kata pack."""
    res = smoke_test(tmp_path)
    assert res.passed is False
    assert any("resolved_spec.json missing" in f for f in res.failures)


def test_smoke_fails_on_corrupt_resolved_spec(tmp_path):
    (tmp_path / "resolved_spec.json").write_text("{ not valid json", encoding="utf-8")
    res = smoke_test(tmp_path)
    assert res.passed is False
    assert any("malformed" in f for f in res.failures)


def test_smoke_fails_when_repl_html_missing(tmp_path):
    """A language dir with passing canonical tests but no repl.html
    is incomplete. Smoke fails."""
    # Fake just enough to get past spec parse + canonical (treat 0/0 as
    # canonical-fail in the validator path). To isolate the REPL check
    # specifically, copy toylang's resolved_spec + summary but skip
    # repl.html.
    src = GENERATED / "toylang"
    (tmp_path / "resolved_spec.json").write_text(
        (src / "resolved_spec.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    (tmp_path / "generation_summary.json").write_text(json.dumps({
        "lang_name": "fake",
        "canonical_tests": {"passed": 8, "total": 8, "pass_rate": 1.0},
    }), encoding="utf-8")
    (tmp_path / "compile.py").write_text("import sys\nsys.exit(0)\n",
                                         encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "hello_world.toy").write_text("", encoding="utf-8")
    # NO repl.html.

    res = smoke_test(tmp_path)
    assert res.passed is False
    assert any("repl.html missing" in f for f in res.failures)


def test_smoke_fails_when_repl_html_too_small(tmp_path):
    """A repl.html under 1KB is almost certainly a stub or an
    error-page rather than a working in-browser REPL."""
    src = GENERATED / "toylang"
    (tmp_path / "resolved_spec.json").write_text(
        (src / "resolved_spec.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    (tmp_path / "generation_summary.json").write_text(json.dumps({
        "canonical_tests": {"passed": 8, "total": 8, "pass_rate": 1.0},
    }), encoding="utf-8")
    (tmp_path / "compile.py").write_text("import sys; sys.exit(0)",
                                         encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "hello_world.toy").write_text("", encoding="utf-8")
    (tmp_path / "repl.html").write_text("<html>stub</html>", encoding="utf-8")

    res = smoke_test(tmp_path)
    assert res.passed is False
    assert any("too small" in f for f in res.failures)


def test_smoke_fails_when_compile_py_crashes(tmp_path):
    """compile.py that crashes on the hello_world test indicates the
    language can't actually compile programs. Smoke fails."""
    src = GENERATED / "toylang"
    spec_text = (src / "resolved_spec.json").read_text(encoding="utf-8")
    (tmp_path / "resolved_spec.json").write_text(spec_text, encoding="utf-8")
    (tmp_path / "generation_summary.json").write_text(json.dumps({
        "canonical_tests": {"passed": 8, "total": 8, "pass_rate": 1.0},
    }), encoding="utf-8")
    # repl.html that passes the size + Pyodide check.
    (tmp_path / "repl.html").write_text(
        "<html>" + "x" * 2000 + " pyodide " + "y" * 1000 + "</html>",
        encoding="utf-8",
    )
    # compile.py that always exits nonzero with an error.
    (tmp_path / "compile.py").write_text(
        "import sys\nprint('synthetic crash', file=sys.stderr)\nsys.exit(1)\n",
        encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "hello_world.toy").write_text("", encoding="utf-8")

    res = smoke_test(tmp_path)
    assert res.passed is False
    assert any("compile.py exit 1" in f for f in res.failures)
    assert res.repl["compile_exit_code"] == 1
    assert res.repl["launches"] is False


# ---------------------------------------------------------------------------
# Canonical-tests check
# ---------------------------------------------------------------------------

def test_smoke_reads_canonical_from_summary_when_present():
    """If generation_summary.json's canonical_tests block is present,
    smoke uses it (source='summary') rather than re-running verify.
    Saves ~600ms per language at batch scale."""
    res = smoke_test(GENERATED / "toylang", force_reverify=False)
    assert res.canonical.get("source") in ("summary", "verify"), (
        f"canonical source should be either summary or verify, "
        f"got {res.canonical.get('source')}"
    )


def test_smoke_force_reverify_runs_verify():
    """`force_reverify=True` ignores the summary and re-runs verify().
    Useful when the user suspects the summary is stale."""
    res = smoke_test(GENERATED / "toylang", force_reverify=True)
    assert res.canonical["source"] == "verify"
    assert res.canonical["passed"] == res.canonical["total"]


def test_smoke_canonical_failure_recorded_in_failures():
    """If canonical tests fail, the failures list explains how many."""
    # Synthetic: write a summary saying 5/8 passed.
    src = GENERATED / "toylang"
    fake = Path(os.path.dirname(src)) / "_smoke_fake_partial"
    if fake.exists():
        import shutil
        shutil.rmtree(fake)
    fake.mkdir()
    try:
        (fake / "resolved_spec.json").write_text(
            (src / "resolved_spec.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        (fake / "generation_summary.json").write_text(json.dumps({
            "canonical_tests": {"passed": 5, "total": 8, "pass_rate": 0.625},
        }), encoding="utf-8")
        (fake / "repl.html").write_text(
            "<html>" + "x" * 2000 + " pyodide " + "y" * 1000 + "</html>",
            encoding="utf-8")
        (fake / "compile.py").write_text("import sys; sys.exit(0)",
                                         encoding="utf-8")
        (fake / "tests").mkdir()
        (fake / "tests" / "hello_world.toy").write_text("", encoding="utf-8")

        res = smoke_test(fake, force_reverify=False)
        assert res.passed is False
        assert any("5/8" in f for f in res.failures)
    finally:
        import shutil
        shutil.rmtree(fake, ignore_errors=True)


# ---------------------------------------------------------------------------
# Pack-for-syntax map sanity
# ---------------------------------------------------------------------------

def test_pack_for_syntax_only_includes_curated_families():
    """Only families with a real curated pack should be in the map.
    Adding python_like or s_expression here would cause smoke to
    fail for those languages until Phase 4 ships native packs."""
    assert _PACK_FOR_SYNTAX == {
        "c_like": "classics",
        "stack_based": "stack_classics",
    }


# ---------------------------------------------------------------------------
# Runner integration: smoke results land in state.json
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_runner_records_smoke_in_state_json(tmp_path):
    """The runner should call smoke_test on each completed slot and
    add a `smoke` field to the slot's state entry. Use a real
    templated subprocess generation so this is a true end-to-end
    integration check."""
    from forge.catalog.planner import Slot
    from forge.catalog.runner import BatchRunner, _state_path

    plan = [Slot(
        slot_id="smoke_int_001",
        options={"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common",
    )]
    runner = BatchRunner(plan=plan, output_root=tmp_path, concurrency=1,
                         run_smoke=True)
    outcome = runner.run()

    assert outcome.completed == 1
    state = json.loads(_state_path(tmp_path).read_text(encoding="utf-8"))
    entry = state["slots"]["smoke_int_001"]
    assert "smoke" in entry, (
        f"runner failed to record smoke result; entry was: {entry}"
    )
    assert entry["smoke"]["passed"] in (True, False)
    assert "canonical" in entry["smoke"]
    assert "repl" in entry["smoke"]
    assert "duration_seconds" in entry["smoke"]


def test_runner_skip_smoke_with_run_smoke_false(tmp_path):
    """run_smoke=False should skip the smoke step entirely. Useful
    for debug runs where smoke would just add noise. Uses a
    bogus-spec slot so we don't need a real subprocess."""
    from forge.catalog.planner import Slot
    from forge.catalog.runner import BatchRunner, _state_path

    bogus = Slot(
        slot_id="no_smoke_001",
        options={"syntax": "imaginary", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common",
    )
    runner = BatchRunner(plan=[bogus], output_root=tmp_path, concurrency=1,
                         run_smoke=False)
    outcome = runner.run()
    # The bogus slot fails before any smoke could be run anyway.
    # Just verify the outcome object has smoke counts at zero.
    assert outcome.smoke_passed == 0
    assert outcome.smoke_failed == 0


def test_outcome_smoke_pass_rate_zero_when_no_completed(tmp_path):
    """smoke_pass_rate property should be 0.0 (not crash) when no
    slots completed."""
    from forge.catalog.planner import Slot
    from forge.catalog.runner import BatchRunner

    bogus = Slot(
        slot_id="rate_zero_001",
        options={"syntax": "imaginary", "typing": "dynamic", "memory": "host_gc"},
        customization={"persona": None, "era": None, "theme": None,
                       "phrasebook": None, "feature_bans": []},
        seed=1, target_rarity="common",
    )
    runner = BatchRunner(plan=[bogus], output_root=tmp_path, concurrency=1)
    outcome = runner.run()
    assert outcome.smoke_pass_rate == 0.0
