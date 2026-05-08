"""Phase 1.5 Stage A — parameterized `_template_from_reference`.

Pins the contract: cloning toylang into a sibling with non-default
keyword spellings and comment syntax produces a working language
whose canonical 8 tests still pass.

This is the foundational test for the structural fix described in
PIPELINE_DIAGNOSIS.md §5. Without these substitutions, templating
produces identical clones with different module names; with them,
templated languages can be visibly distinct from the reference and
from each other while inheriting the reference's correctness for
free.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from forge.orchestrator.generator import (
    _template_from_reference,
    _keyword_overrides_from_spec,
    _comment_syntax_from_spec,
    _substitute_grammar_keywords,
    _substitute_grammar_comments,
    _substitute_source_keywords,
    _substitute_source_comments,
    _substitute_runtime_str_literals,
    _apply_template_substitutions,
)
from forge.orchestrator.spec_builder import build_spec


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


# ---------------------------------------------------------------------------
# Helper: build a c_like spec with deliberate keyword + comment overrides
# ---------------------------------------------------------------------------

def _democ_style_spec(lang_name: str = "democ_test") -> dict:
    """Build a spec that overrides keywords (var→let, func→fn) and
    comment syntax (// → #). This is the deliberate test case the
    Phase 1.5 instructions specify in Stage A's acceptance criterion."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        lang_name,
    )
    # Inject overrides directly. In production these come from themes /
    # phrasebooks via spec_builder; here we set them explicitly to
    # exercise the substitution layer in isolation.
    cust = dict(spec.get("customization") or {})
    cust["keyword_overrides"] = {
        "var": "let",
        "func": "fn",
        "if": "if",        # unchanged; should pass through cleanly
        "else": "else",
        "while": "while",
        "return": "return",
        "true": "true",
        "false": "false",
        "null": "null",
    }
    spec["customization"] = cust
    spec["comment_syntax"] = {
        "line": "#",
        "block_open": "/*",   # unchanged
        "block_close": "*/",
    }
    return spec


# ---------------------------------------------------------------------------
# Unit tests for the helper functions
# ---------------------------------------------------------------------------

def test_keyword_overrides_pulls_from_customization():
    spec = _democ_style_spec()
    overrides = _keyword_overrides_from_spec(spec)
    assert overrides["var"] == "let"
    assert overrides["func"] == "fn"
    assert overrides["if"] == "if"   # identity passthrough


def test_keyword_overrides_falls_back_to_identity_when_empty():
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "x")
    spec["customization"] = {}
    overrides = _keyword_overrides_from_spec(spec)
    assert overrides == {
        "var": "var", "func": "func", "if": "if", "else": "else",
        "while": "while", "return": "return",
        "true": "true", "false": "false", "null": "null",
    }


def test_grammar_keyword_substitution_only_touches_quoted_tokens():
    """The substitution must replace `"var"` (the Lark token) without
    touching unquoted occurrences (e.g. variable names like `varying`
    or comments mentioning `var`)."""
    g = '''var_decl: "var" NAME "=" expr ";"\n# A comment mentioning var\nvarying: "varying"'''
    out = _substitute_grammar_keywords(g, {"var": "let"})
    assert '"let"' in out                           # token swapped
    assert '"varying"' in out                       # unrelated token untouched
    assert "var_decl:" in out                       # rule name untouched
    assert "# A comment mentioning var" in out      # comment text untouched
    assert "varying:" in out                        # rule name with substring untouched


def test_grammar_comment_substitution_swaps_line_terminal():
    g = 'LINE_COMMENT: "//" /[^\\n]*/'
    out = _substitute_grammar_comments(g, {"line": "#", "block_open": "/*", "block_close": "*/"})
    assert 'LINE_COMMENT: "#"' in out
    assert '"//"' not in out


def test_source_keyword_substitution_word_boundary():
    """Source-level substitution: `var x = 5;` → `let x = 5;` but
    `varying = 1;` stays as-is."""
    src = "var x = 5;\nvarying = 1;\nfunc f() {}"
    out = _substitute_source_keywords(src, {"var": "let", "func": "fn",
                                            "if": "if", "else": "else",
                                            "while": "while", "return": "return",
                                            "true": "true", "false": "false",
                                            "null": "null"})
    assert "let x = 5;" in out
    assert "varying = 1;" in out         # not "letying"
    assert "fn f() {}" in out


def test_source_comment_substitution_replaces_marker():
    src = "// header\nvar x = 1; // trailing\n/* block */"
    out = _substitute_source_comments(
        src,
        old={"line": "//", "block_open": "/*", "block_close": "*/"},
        new={"line": "#", "block_open": "/*", "block_close": "*/"},
    )
    assert "# header" in out
    assert "# trailing" in out
    assert "/* block */" in out      # block markers unchanged


def test_runtime_str_literal_substitution_for_true_false_null():
    rt = '''def toy_str(v):
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    return str(v)'''
    out = _substitute_runtime_str_literals(
        rt, {"true": "aye", "false": "nay", "null": "ghost",
             "var": "var", "func": "func", "if": "if", "else": "else",
             "while": "while", "return": "return"})
    assert 'return "aye"' in out
    assert 'return "nay"' in out
    assert 'return "ghost"' in out
    assert 'return "true"' not in out


# ---------------------------------------------------------------------------
# Integration: clone toylang into a democ-style sibling and run canonical tests
# ---------------------------------------------------------------------------

def _write_spec_for_verify(lang_dir: Path, spec: dict) -> None:
    """The verifier reads `<lang_dir>/resolved_spec.json` to learn the
    file extension. `_template_from_reference` doesn't write it (that's
    `generate_all`'s job, called separately). Tests that exercise
    `_template_from_reference` directly need to write the spec
    themselves so the verifier can pick the right extension."""
    (lang_dir / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8"
    )


def _run_canonical_tests(lang_dir: Path) -> tuple[int, int, list[str]]:
    """Compile + run each test; return (passed, total, failed_names)."""
    from forge.orchestrator.verifier import verify
    report = verify(lang_dir)
    passed = sum(1 for t in report.tests if t.status == "pass")
    failed = [t.name for t in report.tests if t.status != "pass"]
    return passed, len(report.tests), failed


@pytest.mark.slow
def test_clone_toylang_into_democ_style_passes_8_of_8(tmp_path):
    """The Stage A acceptance criterion. Clone toylang into a sibling
    language with deliberate keyword + comment overrides, run all 8
    canonical tests, expect 8/8 pass.

    If this test fails, the substitution layer has broken correctness
    somewhere — fix before proceeding to Stage B."""
    spec = _democ_style_spec(lang_name="democ_clone")
    lang_dir = tmp_path / "democ_clone"
    lang_dir.mkdir()

    _write_spec_for_verify(lang_dir, spec)
    fulfilled = _template_from_reference(spec, lang_dir, TOYLANG_DIR)
    # Confirm all 5 code components + tests were templated.
    assert {"parser", "lexer", "codegen", "runtime", "stdlib", "tests"} <= fulfilled

    # Sanity: the templated parser.py should contain the new keyword
    # spellings inside its grammar.
    parser_text = (lang_dir / "parser.py").read_text(encoding="utf-8")
    assert '"let"' in parser_text, (
        "parser.py grammar should contain `\"let\"` after var→let "
        "substitution; the substitution layer didn't apply"
    )
    assert '"fn"' in parser_text
    assert 'LINE_COMMENT: "#"' in parser_text, (
        "comment-syntax substitution didn't update LINE_COMMENT terminal"
    )

    # Sanity: the templated test source should use the new spellings.
    # File extension is the spec's, not the reference's `.toy`.
    var_test_path = lang_dir / "tests" / f"variables{spec['file_extension']}"
    var_test = var_test_path.read_text(encoding="utf-8")
    assert "let " in var_test, (
        f"{var_test_path.name} should use `let` after substitution; "
        f"templated parser would reject the original `var x = ...`"
    )
    # Confirm `var` doesn't appear as a standalone keyword.
    import re as _re
    assert not _re.search(r'\bvar\b', var_test), (
        f"`var` keyword still appears in {var_test_path.name} after substitution"
    )

    # And finally: run the canonical 8. They MUST pass.
    passed, total, failed = _run_canonical_tests(lang_dir)
    assert total == 8, f"expected 8 canonical tests, found {total}"
    assert passed == total, (
        f"democ-style clone failed {len(failed)} canonical test(s): "
        f"{failed}. The substitution layer broke correctness."
    )


@pytest.mark.slow
def test_clone_toylang_with_no_overrides_still_works(tmp_path):
    """Identity case: cloning toylang with no keyword/comment
    customization should produce a byte-identical (modulo module-name
    swap) sibling that passes 8/8. Pins that the new substitution
    pass is a no-op when there's nothing to substitute."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "identity_clone",
    )
    lang_dir = tmp_path / "identity_clone"
    lang_dir.mkdir()
    _write_spec_for_verify(lang_dir, spec)
    _template_from_reference(spec, lang_dir, TOYLANG_DIR)

    passed, total, failed = _run_canonical_tests(lang_dir)
    assert passed == total == 8, (
        f"identity clone failed {len(failed)} test(s): {failed}. The "
        f"no-substitution path regressed."
    )


@pytest.mark.slow
def test_clone_toylang_with_renamed_booleans_passes(tmp_path):
    """A more aggressive override: rename true/false/null. The
    runtime's toy_str must emit the new spellings, AND the canonical
    expected_output.txt files must be substituted to match."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "boolswap_clone",
    )
    cust = dict(spec.get("customization") or {})
    cust["keyword_overrides"] = {
        "var": "var", "func": "func", "if": "if", "else": "else",
        "while": "while", "return": "return",
        "true": "aye", "false": "nay", "null": "void",
    }
    spec["customization"] = cust

    lang_dir = tmp_path / "boolswap_clone"
    lang_dir.mkdir()
    _write_spec_for_verify(lang_dir, spec)
    _template_from_reference(spec, lang_dir, TOYLANG_DIR)

    # Sanity: runtime.py's toy_str should now emit "aye" / "nay" / "void"
    rt_text = (lang_dir / "runtime.py").read_text(encoding="utf-8")
    assert 'return "aye"' in rt_text
    assert 'return "nay"' in rt_text
    assert 'return "void"' in rt_text

    # Expected outputs that contained `true` / `false` should be
    # substituted to match. conditionals.expected_output.txt has
    # `both true`; should become `both aye`.
    cond_eo = (lang_dir / "tests" / "conditionals.expected_output.txt").read_text(encoding="utf-8")
    assert "both aye" in cond_eo, (
        f"expected_output.txt substitution failed; got:\n{cond_eo}"
    )

    passed, total, failed = _run_canonical_tests(lang_dir)
    assert passed == total == 8, (
        f"bool-renamed clone failed {len(failed)} test(s): {failed}"
    )
