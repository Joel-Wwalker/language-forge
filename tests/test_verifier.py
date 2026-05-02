"""Tests for the verification harness against the hand-written toylang."""
from __future__ import annotations

from pathlib import Path

from forge.orchestrator.verifier import verify, CANONICAL_TESTS


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


def test_toylang_passes_all_canonical_tests():
    """The hand-written compiler must pass all 8 canonical tests; this is the
    bedrock the LLM-generated compilers must meet."""
    report = verify(TOYLANG_DIR)
    assert report.all_passed, "\n" + report.summary()
    assert {t.name for t in report.tests if t.status == "pass"} == set(CANONICAL_TESTS)


def test_verifier_reports_missing_canonicals(tmp_path):
    """An empty lang dir should report all canonicals missing."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "compile.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    report = verify(tmp_path)
    assert not report.all_passed
    assert set(report.missing_canonical) == set(CANONICAL_TESTS)


def test_attribution_catches_typechecker_paths():
    """An IndexError raised inside typechecker.py should attribute to
    'typechecker', not 'codegen'. This was the bug behind hardcombo's
    repair targeting the wrong component."""
    from forge.orchestrator.verifier import _attribute_failure
    fake = (
        'Traceback (most recent call last):\n'
        '  File "compile.py", line 36, in main\n'
        '    tree = check(tree)\n'
        '  File ".../generated/hardcombo/typechecker.py", line 66, in check_expr\n'
        '    expr_type = self.check_expr(tree.children[2])\n'
        '                                ~~~~~~~~~~~~~^^^\n'
        'IndexError: list index out of range\n'
    )
    assert _attribute_failure(fake, "compile") == "typechecker"


def test_attribution_catches_lexer_paths():
    """An UnexpectedCharacters from lexer.py attributes to 'lexer', not 'parser'."""
    from forge.orchestrator.verifier import _attribute_failure
    fake = (
        'Traceback (most recent call last):\n'
        '  File ".../lexer.py", line 50, in tokenize\n'
        "lark.exceptions.UnexpectedCharacters: No terminal matches '/' at line 1\n"
    )
    # parser keywords (lark, unexpected) are present, but lexer.py is in the
    # traceback. File path wins.
    assert _attribute_failure(fake, "compile") == "lexer"


def test_attribution_falls_back_to_keyword_match():
    """Tracebacks without our file paths still attribute via keywords."""
    from forge.orchestrator.verifier import _attribute_failure
    fake = "lark.exceptions.UnexpectedToken: ...\n"
    assert _attribute_failure(fake, "compile") == "parser"


def test_verifier_attributes_compile_failure(tmp_path):
    """If compile.py fails, the verifier should mark stage='compile' and pick a
    plausible component (parser / codegen)."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # Use a real spec so the verifier knows the file extension.
    (tmp_path / "resolved_spec.json").write_text(
        '{"lang_name":"x","options":{"syntax":"c_like","typing":"dynamic","memory":"host_gc"},'
        '"file_extension":".x","comment_syntax":{"line":"//"},'
        '"keywords":["a","b","c","d","e"],'
        '"operators":{"arithmetic":[],"comparison":[],"logical":[],"assignment":[]},'
        '"literals":{"integer":"","float":"","string":"","boolean":""},'
        '"statement_terminator":";","block_style":"braces",'
        '"function_definition":{"keyword":"f","syntax_example":""},'
        '"variable_declaration":{"keyword":"v","syntax_example":""},'
        '"print_form":"print(x);","boolean_keywords":{"true":"true","false":"false"},'
        '"null_keyword":"null"}',
        encoding="utf-8",
    )
    # compile.py that always errors.
    (tmp_path / "compile.py").write_text(
        "import sys\nprint('boom: parse error', file=sys.stderr)\nsys.exit(1)\n",
        encoding="utf-8",
    )
    # Provide one canonical source + expected so it actually attempts compile.
    (tests_dir / "hello_world.x").write_text("// hi\n", encoding="utf-8")
    (tests_dir / "hello_world.expected_output.txt").write_text("Hello, World!\n", encoding="utf-8")

    report = verify(tmp_path)
    failing = [t for t in report.tests if t.name == "hello_world"][0]
    assert failing.status == "fail"
    assert failing.stage == "compile"
    assert failing.failing_component in {"parser", "codegen", "lexer", "typechecker"}
