"""Tests for the design axes added from language-generation-design-decisions.md.

Covers: naming_convention, null_model, and the deterministic coherence
validator that flags self-contradicting combinations before they reach
the LLM.
"""
from __future__ import annotations

import pytest

from forge.orchestrator.spec_builder import build_spec, validate_spec
from forge.orchestrator.coherence import (
    check, errors, warnings, CoherenceError, Issue,
)


BASE = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}


# ---------------------------------------------------------------------------
# naming_convention
# ---------------------------------------------------------------------------

def test_naming_convention_default_is_snake_case():
    spec = build_spec(BASE, "demo")
    assert spec["naming_convention"] == "snake_case"
    assert spec["options"]["naming_convention"] == "snake_case"


def test_naming_convention_camelcase():
    spec = build_spec({**BASE, "naming_convention": "camelCase"}, "demo")
    assert spec["naming_convention"] == "camelCase"


def test_naming_convention_pascalcase():
    spec = build_spec({**BASE, "naming_convention": "PascalCase"}, "demo")
    assert spec["naming_convention"] == "PascalCase"


def test_naming_convention_validates_in_schema():
    """The schema enum rejects unknown casings."""
    spec = build_spec(BASE, "demo")
    spec["naming_convention"] = "kebab-case"
    from jsonschema import ValidationError
    with pytest.raises(ValidationError):
        validate_spec(spec)


# ---------------------------------------------------------------------------
# null_model
# ---------------------------------------------------------------------------

def test_null_model_default_is_nullable():
    spec = build_spec(BASE, "demo")
    assert spec["null_model"] == "nullable"


def test_null_model_option_adds_helpers():
    spec = build_spec({**BASE, "null_model": "option"}, "demo")
    names = {f["name"] for f in spec["stdlib"]["functions"]}
    assert {"Some", "is_some", "unwrap"}.issubset(names)


def test_null_model_none_marks_keyword_unused():
    """null_model=none with a failure path (Result/exceptions) is allowed."""
    spec = build_spec({**BASE, "null_model": "none",
                      "error_handling": "result_type"}, "demo")
    assert spec["null_model"] == "none"
    assert spec.get("null_keyword_status") == "reserved_but_unused"


def test_null_model_nullable_no_helpers_added():
    """Default null_model shouldn't pollute the stdlib with Some/unwrap."""
    spec = build_spec(BASE, "demo")
    names = {f["name"] for f in spec["stdlib"]["functions"]}
    assert "Some" not in names
    assert "unwrap" not in names


# ---------------------------------------------------------------------------
# Coherence validator: per-rule
# ---------------------------------------------------------------------------

def test_coherence_clean_combo_returns_no_issues():
    issues = check({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
                    "default_mutability": "mutable", "boolean_evaluation": "short_circuit",
                    "null_model": "nullable", "error_handling": "panic_only",
                    "loop_forms": ["while"]})
    # Note: `boolean_evaluation` defaults to short_circuit so no rule fires.
    assert errors(issues) == []


def test_coherence_warns_for_immutable_eager():
    issues = check({"default_mutability": "immutable", "boolean_evaluation": "eager",
                    "loop_forms": ["while"]})
    codes = {i.code for i in issues}
    assert "immutable_eager_pointless" in codes
    # That's a warning, not an error
    assert all(i.severity == "warning" for i in issues if i.code == "immutable_eager_pointless")


def test_coherence_warns_for_static_python_combo():
    issues = check({"syntax": "python_like", "typing": "static",
                    "default_mutability": "mutable", "loop_forms": ["while"]})
    codes = {i.code for i in issues}
    assert "static_python_uses_gradual" in codes


def test_coherence_warns_for_null_model_none_panic_only():
    issues = check({"null_model": "none", "error_handling": "panic_only",
                    "loop_forms": ["while"]})
    codes = {i.code for i in issues}
    assert "null_model_no_failure_path" in codes


def test_coherence_no_warning_when_null_none_paired_with_result():
    issues = check({"null_model": "none", "error_handling": "result_type",
                    "loop_forms": ["while"]})
    codes = {i.code for i in issues}
    assert "null_model_no_failure_path" not in codes


def test_coherence_errors_for_no_exceptions_ban_with_exception_handling():
    issues = check({"error_handling": "exceptions",
                    "feature_bans": ["no_exceptions"], "loop_forms": ["while"]})
    err_codes = {i.code for i in errors(issues)}
    assert "no_exceptions_but_exceptions_chosen" in err_codes


def test_coherence_errors_for_no_mutation_with_mutable_default():
    issues = check({"default_mutability": "mutable",
                    "feature_bans": ["no_mutation"], "loop_forms": ["while"]})
    err_codes = {i.code for i in errors(issues)}
    assert "no_mutation_but_mutable_default" in err_codes


def test_coherence_warns_for_empty_loop_forms_without_ban():
    issues = check({"loop_forms": []})
    codes = {i.code for i in issues}
    assert "loop_forms_empty_without_ban" in codes


def test_coherence_no_warning_for_empty_loop_forms_with_no_loops_ban():
    issues = check({"loop_forms": [], "feature_bans": ["no_loops"]})
    codes = {i.code for i in issues}
    assert "loop_forms_empty_without_ban" not in codes


# ---------------------------------------------------------------------------
# build_spec integration
# ---------------------------------------------------------------------------

def test_build_spec_raises_coherence_error():
    """Hard incoherences raise CoherenceError before the resolver runs."""
    with pytest.raises(CoherenceError) as exc:
        build_spec({**BASE, "error_handling": "exceptions"}, "demo",
                   feature_bans=["no_exceptions"])
    # The exception lists the issues
    assert len(exc.value.issues) >= 1
    assert any(i.code == "no_exceptions_but_exceptions_chosen"
               for i in exc.value.issues)


def test_build_spec_records_warnings_in_design_notes():
    """Soft warnings end up in design_notes, not raised."""
    spec = build_spec({**BASE, "default_mutability": "immutable",
                       "boolean_evaluation": "eager"}, "demo")
    notes = spec["design_notes"]
    assert any("[coherence]" in n for n in notes)
    assert any("eager" in n.lower() for n in notes)


def test_build_spec_no_notes_for_clean_combo():
    """Defaults should produce zero coherence warnings."""
    spec = build_spec(BASE, "demo")
    coherence_notes = [n for n in spec["design_notes"] if "[coherence]" in n]
    assert coherence_notes == []


# ---------------------------------------------------------------------------
# Backward compatibility: original 8 MVP combos still build cleanly.
# ---------------------------------------------------------------------------

def test_all_original_combos_still_build():
    import itertools
    for syn, ty, mem in itertools.product(
        ["c_like", "python_like"], ["static", "dynamic"], ["host_gc", "refcount"]
    ):
        spec = build_spec({"syntax": syn, "typing": ty, "memory": mem}, "demo")
        validate_spec(spec)
        # New axes have defaults
        assert spec["naming_convention"] == "snake_case"
        assert spec["null_model"] == "nullable"
