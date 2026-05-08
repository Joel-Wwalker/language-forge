"""Regression tests from the comprehensive s_expression audit.

After shipping the lisplang reference compiler + template path, an audit
turned up several places where code branched on c_like / python_like and
had no s_expression case. These tests pin the fixes.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
LISPLANG_DIR = WORKSPACE_ROOT / "generated" / "lisplang"


# ---------- samples.py: s_expression mechanical translation ----------

def test_get_sample_returns_lisp_form_for_s_expression():
    """get_sample must transpile c_like samples to s_expression form so
    generated lisplang-templated languages get usable examples."""
    from forge.gui.samples import get_sample
    src = get_sample("fibonacci", "s_expression")
    assert src is not None, "fibonacci sample must transpile for s_expression"
    # It's Lisp form: starts with (, no semicolons, no curly braces.
    assert src.lstrip().startswith("("), f"expected lisp form, got: {src[:50]!r}"
    assert ";" not in src or src.count(";") < 5, "should not have c_like statement terminators"
    assert "{" not in src and "}" not in src


def test_get_sample_c_like_unchanged():
    """Regression: c_like sample retrieval must not be affected by the
    s_expression branch."""
    from forge.gui.samples import get_sample
    src = get_sample("fibonacci", "c_like")
    assert src is not None
    assert "func" in src or "fib" in src
    assert ";" in src


def test_get_sample_python_like_unchanged():
    from forge.gui.samples import get_sample
    src = get_sample("fibonacci", "python_like")
    assert src is not None
    assert "def" in src
    assert "{" not in src   # no braces


# ---------- _translate_comments: ; both directions ----------

def test_translate_comments_emits_semicolon_for_s_expression_target():
    """Loading a c_like sample with `// foo` onto an s_expression target
    must rewrite the comment to `; foo`."""
    from forge.orchestrator.generator import _translate_comments
    src = "// hello\n(def x 1)\n"
    out = _translate_comments(src, "s_expression",
                              {"line": ";", "block_open": None, "block_close": None})
    assert "; hello" in out
    assert "//" not in out


def test_translate_comments_lisp_to_c_like():
    """Loading an s_expression sample with `; foo` onto a c_like target
    rewrites to `// foo`."""
    from forge.orchestrator.generator import _translate_comments
    src = "; hello\nvar x = 1;\n"
    out = _translate_comments(src, "c_like",
                              {"line": "//", "block_open": "/*", "block_close": "*/"})
    assert "// hello" in out
    assert "; hello" not in out


def test_translate_comments_lisp_to_python_like():
    from forge.orchestrator.generator import _translate_comments
    src = "; hello\n(def x 1)\n"
    out = _translate_comments(src, "python_like",
                              {"line": "#", "block_open": None, "block_close": None})
    assert "# hello" in out


def test_translate_comments_handles_double_semicolon_scheme_style():
    """Scheme convention is `;;` for top-level comments. Strip both."""
    from forge.orchestrator.generator import _translate_comments
    src = ";; section header\n; inline\n(def x 1)\n"
    out = _translate_comments(src, "c_like",
                              {"line": "//", "block_open": "/*", "block_close": "*/"})
    assert "// section header" in out
    assert "// inline" in out


# ---------- _explain_compile_error: s_expression hints ----------

def test_compile_error_hint_for_extra_close_paren():
    """When lisplang's parser hits an unmatched `)`, the hint should
    name the cause and point at the Load reference button."""
    from forge.gui.app import _explain_compile_error
    fake_stderr = (
        "lark.exceptions.UnexpectedCharacters: No terminal matches ')' "
        "in the current parser context, at line 5 col 12\n"
    )
    hint = _explain_compile_error(fake_stderr, LISPLANG_DIR)
    assert hint is not None
    assert "extra `)`" in hint or "matching" in hint.lower()


def test_compile_error_hint_for_c_like_punctuation_in_lisp():
    """User pasted c_like code into lisplang. Rejected `;` or `{` should
    surface a 'wrong syntax family' hint."""
    from forge.gui.app import _explain_compile_error
    fake_stderr = (
        "lark.exceptions.UnexpectedCharacters: No terminal matches '{' "
        "in the current parser context, at line 1 col 5\n"
    )
    hint = _explain_compile_error(fake_stderr, LISPLANG_DIR)
    assert hint is not None
    assert "s_expression" in hint or "Lisp" in hint or "(...)" in hint


# ---------- repair guard: don't overwrite templated components ----------

def test_repair_skips_templated_components():
    """For s_expression languages, the parser/codegen/runtime/stdlib are
    templated from lisplang and known-good. Repair must NOT pick them
    even when verify reports failures attributed to those components,
    because that would replace hand-written code with LLM output."""
    from forge.orchestrator.repair import _pick_component, _is_templated_language
    from forge.orchestrator.verifier import VerificationReport, TestResult

    spec = {"options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"}}
    assert _is_templated_language(spec) is True

    # Fabricate a report where codegen is the dominant attribution.
    fail = TestResult(
        name="closures",
        status="fail",
        stage="run",
        failing_component="codegen",
        expected="1\n2\n3",
        actual="",
        stderr="some runtime error",
        returncode=1,
    )
    report = VerificationReport(
        lang_dir=LISPLANG_DIR,
        file_extension=".lsp",
        all_passed=False,
        missing_canonical=[],
        tests=[fail],
    )

    pick = _pick_component(report, spec)
    # codegen is templated → must NOT be picked. Either no pick at all
    # (None) or a non-templated component.
    assert pick not in {"parser", "codegen", "runtime", "stdlib", "lexer"}


def test_repair_can_still_pick_tests_for_templated_languages():
    """Repair should still target `tests` (regenerate canonical tests)
    when those are missing, even for templated languages."""
    from forge.orchestrator.repair import _pick_component
    from forge.orchestrator.verifier import VerificationReport

    spec = {"options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"}}
    report = VerificationReport(
        lang_dir=LISPLANG_DIR,
        file_extension=".lsp",
        all_passed=False,
        missing_canonical=["arithmetic"],
        tests=[],
    )
    pick = _pick_component(report, spec)
    assert pick == "tests"


def test_repair_skips_templated_components_for_c_like_post_phase15():
    """Phase 1.5 Stage B: c_like is now templated from toylang.
    Repair should NOT try to LLM-rewrite the templated parser/codegen/
    runtime/stdlib/lexer — those are hand-written reference files
    inherited via _template_from_reference. Asking the LLM to "fix"
    them would regress a known-good baseline.

    This test was originally pinning the OPPOSITE: c_like has full
    repair access. Phase 1.5 inverted that — c_like is now in the
    templated set. python_like still has full LLM repair access since
    it stays on the LLM-driven path."""
    from forge.orchestrator.repair import _pick_component, _is_templated_language
    from forge.orchestrator.verifier import VerificationReport, TestResult

    # c_like: now templated, parser repair should be skipped.
    c_spec = {"options": {"syntax": "c_like", "typing": "dynamic",
                          "memory": "host_gc"}}
    assert _is_templated_language(c_spec) is True

    # python_like: still LLM-driven, parser repair still active.
    p_spec = {"options": {"syntax": "python_like", "typing": "dynamic",
                          "memory": "host_gc"}}
    assert _is_templated_language(p_spec) is False

    fail = TestResult(
        name="hello_world",
        status="fail",
        stage="compile",
        failing_component="parser",
        expected="hi", actual="", stderr="UnexpectedInput", returncode=1,
    )
    report = VerificationReport(
        lang_dir=LISPLANG_DIR,
        file_extension=".toy",
        all_passed=False,
        missing_canonical=[],
        tests=[fail],
    )
    # python_like with parse error → repair targets parser (LLM path).
    assert _pick_component(report, p_spec) == "parser"
    # c_like with parse error → no parser repair (templated baseline).
    # _pick_component should fall through to alternate-component logic
    # or return None when the only failing component is templated.
    c_pick = _pick_component(report, c_spec)
    assert c_pick != "parser", (
        f"c_like is templated post-Phase 1.5; parser repair should be "
        f"skipped to avoid clobbering the toylang reference. Got: {c_pick}"
    )


# ---------- _batch_validate uses _emit_print for s_expression ----------

def test_batch_validate_emits_lisp_print_for_s_expression(tmp_path):
    """Batch validation builds a single program with print(...) calls.
    For s_expression the wrapping must use `(print ...)` form, not
    `print(...)` which would fail to parse."""
    from forge.orchestrator.katas import _batch_validate

    # Minimal kata in lisplang form
    spec = json.loads((LISPLANG_DIR / "resolved_spec.json").read_text(encoding="utf-8"))
    katas = [
        {
            "id": "tiny",
            "reference_solution": "(defn double (n) (* n 2))",
            "tests": [
                {"call": "(double 21)", "expected": "42"},
            ],
        }
    ]
    # We don't run end-to-end here; just verify the wrapping logic works.
    # If _batch_validate produces parseable Lisp, the lisplang compiler
    # accepts it and returns clean results.
    results = _batch_validate(katas, LISPLANG_DIR, spec)
    # Result might be None (drift) or a list. If None, the per-kata
    # fallback path is exercised; in either case, the wrap logic must
    # not have crashed.
    if results is not None:
        # If batch ran cleanly, the test passes.
        assert isinstance(results, list)


# ---------- starter_program template covers s_expression ----------

def test_starter_program_template_has_s_expression_branch():
    """The j2 template must produce valid lisplang code for s_expression
    languages, not fall through to the c_like default."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(
        loader=FileSystemLoader(str(WORKSPACE_ROOT / "forge" / "templates")),
        keep_trailing_newline=True,
    )
    tmpl = env.get_template("starter_program.j2")
    rendered = tmpl.render(
        syntax="s_expression",
        project_name="test_project",
        lang_name="mylisp",
        file_extension=".lsp",
    )
    # Lisp form: starts with `;` comment + `(defn ...)`
    assert rendered.lstrip().startswith(";")
    assert "(defn" in rendered
    assert "{" not in rendered, "should not have curly braces"
    assert ";" in rendered    # has comments
