"""Tests for the stack_based / concatenative family.

Roadmap families.md Tier 1 item 2.2: Forth-flavored postfix on an
implicit data stack. We ship a hand-written reference compiler at
`generated/forthlang/`; new stack_based languages template from it
the same way s_expression languages template from lisplang.

Pinned contracts:
  - build_spec produces a coherent spec for stack_based
  - Schema accepts stack_based + concatenative block_style
  - forthlang reference passes all 8 canonical tests
  - REFERENCE_COMPILERS routes stack_based to forthlang
  - Templated languages generate in <10 seconds
  - StackBackend transpiles c_like classics to Forth-style postfix
  - Coherence flags warns about phrasebook + stack_based
  - GUI + CLI + surprise picker know about stack_based
"""
from __future__ import annotations

import io
import json
import shutil
import time
import contextlib
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
FORTHLANG_DIR = WORKSPACE_ROOT / "generated" / "forthlang"


# ---------- spec_builder ----------

def test_build_spec_stack_based_dynamic():
    from forge.orchestrator.spec_builder import build_spec, validate_spec
    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "forthy",
    )
    assert spec["lang_name"] == "forthy"
    assert spec["block_style"] == "concatenative"
    assert spec["statement_terminator"] == " "
    assert spec["comment_syntax"]["line"] == "\\"
    assert spec["function_definition"]["keyword"] == ":"
    assert spec["variable_declaration"]["keyword"] == "variable"
    assert spec["null_keyword"] == "nil"
    validate_spec(spec)


def test_build_spec_stack_based_static_uses_stack_effect_annotations():
    from forge.orchestrator.spec_builder import build_spec, validate_spec
    spec = build_spec(
        {"syntax": "stack_based", "typing": "static", "memory": "host_gc"},
        "typedforth",
    )
    assert "(" in spec["function_definition"]["type_annotations"]
    assert spec["type_system"]["annotation_form"].startswith("stack-effect")
    assert spec["type_system"]["inference"] is True
    validate_spec(spec)


def test_build_spec_stack_based_immutable_uses_constant():
    from forge.orchestrator.spec_builder import build_spec
    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc",
         "default_mutability": "immutable"},
        "rigidforth",
    )
    assert spec["variable_declaration"]["keyword"] == "constant"
    assert "constant" in spec["keywords"]


# ---------- schema ----------

def test_schema_accepts_stack_based():
    schema = json.loads(
        (WORKSPACE_ROOT / "schemas" / "language_spec.schema.json").read_text(encoding="utf-8")
    )
    syntax_enum = schema["properties"]["options"]["properties"]["syntax"]["enum"]
    assert "stack_based" in syntax_enum
    block_enum = schema["properties"]["block_style"]["enum"]
    assert "concatenative" in block_enum


# ---------- forthlang reference compiler ----------

def test_forthlang_reference_exists():
    assert FORTHLANG_DIR.exists()
    for f in ("__init__.py", "parser.py", "codegen.py", "runtime.py",
              "stdlib.py", "lexer.py", "compile.py", "pyproject.toml",
              "resolved_spec.json", "README.md"):
        assert (FORTHLANG_DIR / f).exists(), f"forthlang/{f} missing"


def test_forthlang_canonical_tests_pass_via_verifier():
    from forge.orchestrator.verifier import verify
    report = verify(FORTHLANG_DIR)
    failures = [t.name for t in report.tests if t.status == "fail"]
    assert report.all_passed, f"forthlang canonical failures: {failures}"


@pytest.mark.parametrize("test_name", [
    "hello_world", "arithmetic", "variables", "conditionals",
    "loops", "functions", "closures", "strings", "stdlib",
])
def test_forthlang_each_canonical_runs(test_name):
    """Each canonical test parses, transpiles, runs, matches expected."""
    import sys
    if str(WORKSPACE_ROOT / "generated") not in sys.path:
        sys.path.insert(0, str(WORKSPACE_ROOT / "generated"))
    # Force fresh module load - runtime _stack is a global mutable list
    for m in [k for k in list(sys.modules) if k.startswith("forthlang")]:
        del sys.modules[m]
    from forthlang.parser import parse
    from forthlang.codegen import generate

    src = (FORTHLANG_DIR / "tests" / f"{test_name}.fth").read_text(encoding="utf-8")
    expected = (FORTHLANG_DIR / "tests" / f"{test_name}.expected_output.txt").read_text(encoding="utf-8")
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == expected, (
        f"output mismatch for {test_name}.fth\n"
        f"expected: {expected!r}\nactual:   {buf.getvalue()!r}"
    )


def test_forthlang_factorial_recurses_correctly():
    """Direct test of the canonical Forth example from the families
    doc: `: factorial dup 1 <= if drop 1 else dup 1 - factorial * then ;`"""
    import sys
    if str(WORKSPACE_ROOT / "generated") not in sys.path:
        sys.path.insert(0, str(WORKSPACE_ROOT / "generated"))
    for m in [k for k in list(sys.modules) if k.startswith("forthlang")]:
        del sys.modules[m]
    from forthlang.parser import parse
    from forthlang.codegen import generate
    src = (
        ": factorial ( n -- n! )\n"
        "    dup 1 <= if drop 1 else dup 1 - factorial * then ;\n"
        "5 factorial .\n"
    )
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == "120\n"


# ---------- generator template path ----------

class _FakeClient:
    log_dir = None
    def call_code(self, *a, **kw): return "# stub"
    def call_json(self, *a, **kw): return {"tests": []}
    def call_chat(self, *a, **kw): return "# stub"


def test_template_path_routes_stack_based_to_forthlang():
    from forge.orchestrator.generator import reference_compiler_for
    spec = {"options": {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
            "lang_name": "test"}
    ref = reference_compiler_for(spec)
    assert ref is not None
    assert ref.name == "forthlang"


def test_stack_based_generation_is_fast_and_correct(tmp_path):
    """End-to-end: generating a fresh stack_based language must be fast
    AND produce a working compiler that passes all canonical tests."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all
    from forge.orchestrator.verifier import verify

    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "speedforth",
    )
    t0 = time.monotonic()
    out_dir = generate_all(spec, output_root=tmp_path, client=_FakeClient())
    elapsed = time.monotonic() - t0
    assert elapsed < 10.0, f"stack_based generation took {elapsed:.1f}s; expected < 10s"

    report = verify(out_dir)
    failures = [t.name for t in report.tests if t.status == "fail"]
    assert report.all_passed, f"freshly templated forth language failed: {failures}"


def test_template_substitutes_module_name(tmp_path):
    """Verify `forthlang.runtime` import gets rewritten to the new
    language's package name."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "myforth",
    )
    out_dir = generate_all(spec, output_root=tmp_path, client=_FakeClient())
    codegen = (out_dir / "codegen.py").read_text(encoding="utf-8")
    assert "from myforth.runtime import" in codegen
    assert "from forthlang.runtime import" not in codegen


# ---------- mechanical translator ----------

def test_can_handle_stack_based_returns_stack_backend():
    from forge.orchestrator.mechanical_translator import can_handle, StackBackend
    from forge.orchestrator.spec_builder import build_spec
    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "forthy",
    )
    backend = can_handle(spec)
    assert isinstance(backend, StackBackend)


def test_transpile_arithmetic_to_postfix():
    from forge.orchestrator.mechanical_translator import transpile
    from forge.orchestrator.spec_builder import build_spec
    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "forthy",
    )
    out = transpile("var x = 1 + 2 * 3;\n", spec)
    # Expected: `1 2 3 * +` somewhere in the output (postfix arithmetic)
    assert "1 2 3 * +" in out, f"missing postfix arithmetic; got:\n{out}"


def test_transpile_function_to_colon_def():
    from forge.orchestrator.mechanical_translator import transpile
    from forge.orchestrator.spec_builder import build_spec
    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "forthy",
    )
    out = transpile("func double(n) { return n * 2; }\n", spec)
    # Colon definition with stack-effect comment
    assert ": double" in out
    # Body has `n 2 *` (postfix multiply) and `;` terminator
    assert "n 2 *" in out
    assert ";" in out


def test_transpile_no_curly_braces():
    """Stack-based output must NEVER contain c_like punctuation."""
    from forge.orchestrator.mechanical_translator import transpile
    from forge.orchestrator.spec_builder import build_spec
    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "forthy",
    )
    src = (
        "var n = 5;\n"
        "func square(x) { return x * x; }\n"
        "print(square(n));\n"
    )
    out = transpile(src, spec)
    assert "{" not in out and "}" not in out, f"got curly braces in:\n{out}"


# ---------- coherence ----------

def test_coherence_phrasebook_with_stack_based_warns():
    from forge.orchestrator.coherence import check
    issues = check({
        "syntax": "stack_based", "typing": "dynamic", "memory": "host_gc",
        "phrasebook": "child_speak",
    })
    codes = {i.code for i in issues}
    assert "stack_based_with_phrasebook" in codes


def test_coherence_no_loops_with_stack_based_warns():
    from forge.orchestrator.coherence import check
    issues = check({
        "syntax": "stack_based", "typing": "dynamic", "memory": "host_gc",
        "feature_bans": ["no_loops"],
    })
    codes = {i.code for i in issues}
    assert "stack_based_no_loops_unusual" in codes


def test_coherence_baseline_stack_based_no_errors():
    from forge.orchestrator.coherence import check, errors
    issues = check({"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"})
    assert errors(issues) == []


# ---------- GUI / CLI plumbing ----------

def test_surprise_normalizer_maps_forth_synonyms():
    from forge.gui.app import _normalize_surprise_picks
    for variant in ("forth", "stack-based", "concatenative", "factor", "postscript"):
        out = _normalize_surprise_picks({
            "options": {"syntax": variant, "typing": "dynamic", "memory": "host_gc"},
        })
        assert out["options"]["syntax"] == "stack_based", (
            f"{variant!r} should normalize to stack_based"
        )


def test_repair_skips_templated_components_for_stack_based():
    """Repair must not overwrite the hand-written forthlang reference."""
    from forge.orchestrator.repair import _is_templated_language, _pick_component
    from forge.orchestrator.verifier import VerificationReport, TestResult

    spec = {"options": {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"}}
    assert _is_templated_language(spec) is True

    fail = TestResult(
        name="loops", status="fail", stage="run",
        failing_component="codegen",
        expected="55\n", actual="", stderr="x", returncode=1,
    )
    report = VerificationReport(
        lang_dir=FORTHLANG_DIR, file_extension=".fth",
        all_passed=False, missing_canonical=[], tests=[fail],
    )
    pick = _pick_component(report, spec)
    assert pick not in {"parser", "codegen", "runtime", "stdlib", "lexer"}


# ---------- kata wrap ----------

def test_kata_wrap_stack_based_translates_c_like_calls():
    """`_wrap_with_test_prints` must convert c_like-form `factorial(5)`
    test calls into Forth-form `5 factorial .`."""
    from forge.orchestrator.katas import _wrap_with_test_prints
    spec = json.loads((FORTHLANG_DIR / "resolved_spec.json").read_text(encoding="utf-8"))
    user_code = ": factorial dup 1 <= if drop 1 else dup 1 - factorial * then ;"
    tests = [{"call": "factorial(5)", "expected": "120"}]
    program = _wrap_with_test_prints(user_code, tests, spec)
    # Must translate the c_like call AND end with `.` to print.
    assert "factorial" in program
    assert " ." in program   # ends with print
    # And no c_like-style print(call):
    assert "print(factorial" not in program


def test_kata_wrap_stack_based_handles_already_postfix_calls():
    from forge.orchestrator.katas import _wrap_with_test_prints
    spec = json.loads((FORTHLANG_DIR / "resolved_spec.json").read_text(encoding="utf-8"))
    user_code = ": double 2 * ;"
    tests = [{"call": "5 double", "expected": "10"}]
    program = _wrap_with_test_prints(user_code, tests, spec)
    assert "5 double ." in program
