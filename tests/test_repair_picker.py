"""Tests for the repair-loop component-picking heuristics.

These don't run the LLM; they just exercise `_pick_component` over crafted
verification reports to confirm the cascade-aware ordering rules hold.
"""
from __future__ import annotations

from forge.orchestrator.repair import _pick_component
from forge.orchestrator.verifier import VerificationReport
from forge.orchestrator.verifier import TestResult as _TestResult


# Alias avoids pytest auto-collecting "TestResult" as a test class.
TestResult = _TestResult
__test__ = False
TestResult.__test__ = False


def _report(failures: list[dict], missing: list[str] = None) -> VerificationReport:
    """Synthesize a report. `failures` is a list of dicts overriding TestResult fields."""
    tests = []
    for f in failures:
        kw = {"name": f["name"], "status": "fail", "stage": f.get("stage", "compile"),
              "failing_component": f.get("failing_component"),
              "stderr": f.get("stderr", "")}
        tests.append(TestResult(**kw))
    return VerificationReport(
        lang_dir="/fake",
        file_extension=".x",
        all_passed=False,
        tests=tests,
        missing_canonical=missing or [],
    )


SPEC_DYNAMIC = {"options": {"typing": "dynamic"}}
SPEC_STATIC = {"options": {"typing": "static"}}


def test_missing_tests_picked_first():
    """Missing canonicals trump everything: regenerate tests before anything else."""
    rep = _report(
        [{"name": "hello_world", "failing_component": "codegen"}],
        missing=["arithmetic", "loops"],
    )
    assert _pick_component(rep, SPEC_DYNAMIC) == "tests"


def test_parser_chosen_for_parse_error():
    """A parse-stage failure attributes to parser even if codegen also failed."""
    rep = _report([
        {"name": "hello_world", "stage": "compile", "failing_component": "codegen",
         "stderr": "lark.exceptions.UnexpectedInput: Unexpected token"},
        {"name": "arithmetic", "stage": "compile", "failing_component": "codegen",
         "stderr": "TypeError: unhashable"},
    ])
    assert _pick_component(rep, SPEC_DYNAMIC) == "parser"


def test_typechecker_attribution_dropped_for_dynamic():
    """typechecker-attributed failure is ignored when the language is dynamic."""
    rep = _report([
        {"name": "x", "stage": "compile", "failing_component": "typechecker"},
        {"name": "y", "stage": "compile", "failing_component": "typechecker"},
        {"name": "z", "stage": "compile", "failing_component": "codegen"},
    ])
    pick = _pick_component(rep, SPEC_DYNAMIC)
    # typechecker ignored; codegen wins
    assert pick == "codegen"


def test_typechecker_kept_for_static():
    """For static-typed specs, typechecker IS a real component to repair."""
    rep = _report([
        {"name": "x", "stage": "compile", "failing_component": "typechecker"},
        {"name": "y", "stage": "compile", "failing_component": "codegen"},
    ])
    # Tie at one each; "most_common" preserves first-seen order in Counter
    pick = _pick_component(rep, SPEC_STATIC)
    assert pick in ("typechecker", "codegen")


def test_no_failures_returns_none():
    rep = VerificationReport(lang_dir="/x", file_extension=".x", all_passed=True, tests=[], missing_canonical=[])
    assert _pick_component(rep, SPEC_DYNAMIC) is None


def test_pick_skips_unattributed_failures():
    """Failures with no `failing_component` shouldn't crash the picker."""
    rep = _report([{"name": "x", "stage": "run"}])
    # No attribution, no parse-error stderr, no missing canonicals: returns None
    assert _pick_component(rep, SPEC_DYNAMIC) is None


def test_majority_failing_component_wins():
    """Most-common attribution should be picked when no special-case fires."""
    rep = _report([
        {"name": "a", "stage": "run", "failing_component": "runtime"},
        {"name": "b", "stage": "run", "failing_component": "runtime"},
        {"name": "c", "stage": "run", "failing_component": "codegen"},
    ])
    assert _pick_component(rep, SPEC_DYNAMIC) == "runtime"
