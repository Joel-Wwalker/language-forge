"""Tests for the user-customization layer."""
from __future__ import annotations

import pytest

from forge.orchestrator.spec_builder import build_spec, validate_spec


BASE_OPTS = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}


def test_no_customization_validates():
    spec = build_spec(BASE_OPTS, "lang")
    validate_spec(spec)
    assert "customization" not in spec


def test_file_extension_override():
    spec = build_spec(BASE_OPTS, "lang", customization={"file_extension": ".my"})
    assert spec["file_extension"] == ".my"


def test_file_extension_dot_added():
    spec = build_spec(BASE_OPTS, "lang", customization={"file_extension": "myx"})
    assert spec["file_extension"] == ".myx"


def test_keyword_override_changes_var_keyword():
    spec = build_spec(BASE_OPTS, "lang",
                      customization={"keyword_overrides": {"var": "let"}})
    assert spec["variable_declaration"]["keyword"] == "let"
    assert "let" in spec["keywords"]
    assert "var" not in spec["keywords"]


def test_keyword_override_func():
    spec = build_spec(BASE_OPTS, "lang",
                      customization={"keyword_overrides": {"func": "fn"}})
    assert spec["function_definition"]["keyword"] == "fn"
    assert "fn" in spec["keywords"]


def test_operator_override_replaces_category():
    spec = build_spec(BASE_OPTS, "lang",
                      customization={"operator_overrides": {"assignment": ["<-"]}})
    assert spec["operators"]["assignment"] == ["<-"]


def test_extra_design_notes_appended():
    spec = build_spec(BASE_OPTS, "lang",
                      customization={"extra_design_notes": ["lispy", "minimal"]})
    assert "lispy" in spec["design_notes"]
    assert "minimal" in spec["design_notes"]


def test_passthrough_fields_persist():
    spec = build_spec(BASE_OPTS, "lang", customization={
        "extra_prompt_notes": {"codegen": "use 2-space indents"},
        "additional_tests": [{"name": "my_test", "source": "x;", "expected": "1\n"}],
        "extra_design_notes": ["custom"],
    })
    assert spec["customization"]["extra_prompt_notes"]["codegen"] == "use 2-space indents"
    assert spec["customization"]["additional_tests"][0]["name"] == "my_test"
    assert spec["customization"]["extra_design_notes"] == ["custom"]


def test_additional_test_missing_field_raises():
    with pytest.raises(ValueError):
        build_spec(BASE_OPTS, "lang", customization={
            "additional_tests": [{"name": "x", "source": "y"}]  # missing expected
        })


def test_combined_customization_validates():
    spec = build_spec(BASE_OPTS, "lang", customization={
        "file_extension": ".combo",
        "keyword_overrides": {"var": "let", "func": "fn", "true": "yes", "false": "no"},
        "operator_overrides": {"assignment": [":="], "logical": ["and", "or", "not"]},
        "extra_design_notes": ["combined customization"],
        "extra_prompt_notes": {"codegen": "be terse"},
        "additional_tests": [
            {"name": "feature_a", "source": "print(1);", "expected": "1\n"},
        ],
    })
    validate_spec(spec)
    assert spec["file_extension"] == ".combo"
    assert spec["variable_declaration"]["keyword"] == "let"
    assert spec["function_definition"]["keyword"] == "fn"
    assert spec["boolean_keywords"]["true"] == "yes"
    assert spec["boolean_keywords"]["false"] == "no"
    assert spec["operators"]["assignment"] == [":="]
    assert "feature_a" in {t["name"] for t in spec["customization"]["additional_tests"]}


# ---- generator integration ----
def test_user_customization_for_returns_empty_without_notes():
    from forge.orchestrator.generator import _user_customization_for
    spec = build_spec(BASE_OPTS, "lang")
    assert _user_customization_for("codegen", spec) == ""


def test_user_customization_for_appends_notes():
    from forge.orchestrator.generator import _user_customization_for
    spec = build_spec(BASE_OPTS, "lang", customization={
        "extra_prompt_notes": {"codegen": "use 4-space indent"},
    })
    out = _user_customization_for("codegen", spec)
    assert "use 4-space indent" in out
    assert "HIGH PRIORITY" in out


# ---- verifier integration ----
def test_verifier_requires_additional_tests(tmp_path):
    """Verifier must report additional_tests as missing if not present in tests/."""
    from forge.orchestrator.verifier import verify, CANONICAL_TESTS
    # Make a minimal lang dir with the spec but no actual tests
    lang_dir = tmp_path / "demo"
    lang_dir.mkdir()
    (lang_dir / "tests").mkdir()
    spec = build_spec(BASE_OPTS, "demo", customization={
        "additional_tests": [
            {"name": "feature_a", "source": "print(1);", "expected": "1\n"},
        ],
    })
    import json
    (lang_dir / "resolved_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (lang_dir / "compile.py").write_text("import sys; sys.exit(1)\n", encoding="utf-8")

    report = verify(lang_dir)
    # Missing canonicals should include feature_a
    assert "feature_a" in report.missing_canonical
    # All canonicals are also missing (we created an empty tests dir)
    for c in CANONICAL_TESTS:
        assert c in report.missing_canonical
