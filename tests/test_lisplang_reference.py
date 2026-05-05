"""Tests for the hand-written lisplang reference compiler + the
template-from-reference fast path in generator.py.

Background: the user reported that s_expression generation took 15
minutes and didn't work. Root cause: the LLM had to write parser,
codegen, runtime, stdlib from scratch, repeatedly, with subtle bugs
(e.g. closures emitting `(lambda : ()[-1])` from `...` placeholders
in the codegen prompt).

Fix: ship `generated/lisplang/` as a hand-written reference compiler
(mirroring how toylang serves c_like). When the user picks
`syntax = s_expression`, the orchestrator templates from lisplang
instead of asking the LLM. Generation drops from ~15min to ~1.3s and
all 8 canonical tests pass deterministically.

These tests pin that contract.
"""
from __future__ import annotations

import io
import shutil
import contextlib
import time
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
LISPLANG_DIR = WORKSPACE_ROOT / "generated" / "lisplang"


# ---------- lisplang reference: parser + codegen + runtime ----------

def test_lisplang_reference_exists():
    assert LISPLANG_DIR.exists(), "lisplang reference compiler is missing"
    for f in ("__init__.py", "parser.py", "codegen.py", "runtime.py",
              "stdlib.py", "lexer.py", "compile.py", "pyproject.toml"):
        assert (LISPLANG_DIR / f).exists(), f"lisplang/{f} missing"
    assert (LISPLANG_DIR / "tests").is_dir()


def test_lisplang_canonical_tests_all_pass_via_verifier():
    """The canonical 8 tests must pass on the hand-written reference.
    If this regresses, the entire s_expression family is broken."""
    from forge.orchestrator.verifier import verify
    report = verify(LISPLANG_DIR)
    failures = [t.name for t in report.tests if t.status == "fail"]
    assert report.all_passed, f"lisplang canonical failures: {failures}"


@pytest.mark.parametrize("test_name", [
    "hello_world", "arithmetic", "variables", "conditionals",
    "loops", "functions", "closures", "strings", "stdlib",
])
def test_lisplang_canonical_test_runs(test_name):
    """Each canonical test compiles + runs + matches expected output."""
    import sys
    if str(WORKSPACE_ROOT / "generated") not in sys.path:
        sys.path.insert(0, str(WORKSPACE_ROOT / "generated"))
    from lisplang.parser import parse
    from lisplang.codegen import generate
    src = (LISPLANG_DIR / "tests" / f"{test_name}.lsp").read_text(encoding="utf-8")
    expected = (LISPLANG_DIR / "tests" / f"{test_name}.expected_output.txt").read_text(encoding="utf-8")
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == expected, (
        f"output mismatch for {test_name}.lsp\n"
        f"expected: {expected!r}\n"
        f"actual:   {buf.getvalue()!r}\n"
        f"--- generated python ---\n{py}"
    )


def test_lisplang_closures_emit_nonlocal():
    """The bug that triggered this whole investigation: closures used to
    emit `(lambda : ()[-1])`. The hand-written codegen must produce a
    proper nested def with `nonlocal` for captured assignments."""
    import sys
    if str(WORKSPACE_ROOT / "generated") not in sys.path:
        sys.path.insert(0, str(WORKSPACE_ROOT / "generated"))
    from lisplang.parser import parse
    from lisplang.codegen import generate
    src = (LISPLANG_DIR / "tests" / "closures.lsp").read_text(encoding="utf-8")
    py = generate(parse(src))
    # Hard guards against the original bug:
    assert "()[-1]" not in py, "closures regressed to empty-tuple bug"
    assert "lambda : " not in py, "closures should hoist to nested def, not lambda"
    # Soft guard: nonlocal directive should appear for `count`.
    assert "nonlocal count" in py


# ---------- generator template path ----------

class _FakeClient:
    """No-op LLM client: just enough to satisfy the components that aren't
    fulfilled by the template (readme, language_reference, custom tests)."""
    def __init__(self):
        self.log_dir = None
        self.calls = 0

    def call_code(self, prompt, *, tag="code"):
        self.calls += 1
        return f"# stub for {tag}\n"

    def call_json(self, *args, **kwargs):
        self.calls += 1
        return {"tests": []}

    def call_chat(self, *args, **kwargs):
        self.calls += 1
        return "# stub"


def test_template_path_skips_llm_for_core_components(tmp_path):
    """When syntax=s_expression, parser/codegen/runtime/stdlib/lexer/tests
    should be templated from lisplang and the LLM should NOT be invoked
    for them."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "fastlisp",
    )
    client = _FakeClient()
    out_dir = generate_all(spec, output_root=tmp_path, client=client)

    # Templated files should exist
    for f in ("parser.py", "codegen.py", "runtime.py", "stdlib.py", "lexer.py"):
        assert (out_dir / f).exists(), f"templated {f} missing"
    # Tests directory should exist with 8 canonical tests + their expecteds
    tests_dir = out_dir / "tests"
    assert tests_dir.exists()
    canonical = ["hello_world", "arithmetic", "variables", "conditionals",
                 "loops", "functions", "closures", "strings"]
    for name in canonical:
        assert (tests_dir / f"{name}{spec['file_extension']}").exists()
        assert (tests_dir / f"{name}.expected_output.txt").exists()

    # The fake client should only have been called for non-template
    # components (readme, language_reference, maybe extras). Without the
    # template path it would have been called ~10+ times. Bound it loosely
    # in case future components get added to the LLM path.
    assert client.calls <= 4, (
        f"expected at most 4 LLM calls (template path active), got {client.calls}"
    )


def test_template_substitutes_module_name(tmp_path):
    """The reference uses `lisplang.runtime`; the templated language must
    use its own name in the import paths."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "myownlisp",
    )
    out_dir = generate_all(spec, output_root=tmp_path, client=_FakeClient())
    codegen = (out_dir / "codegen.py").read_text(encoding="utf-8")
    assert "from myownlisp.runtime import" in codegen
    assert "from lisplang.runtime import" not in codegen


def test_template_path_passes_canonical_verification(tmp_path):
    """End-to-end: a fresh s_expression language must pass all 8
    canonical tests without any repair loop."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all
    from forge.orchestrator.verifier import verify

    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "fizzlisp",
    )
    out_dir = generate_all(spec, output_root=tmp_path, client=_FakeClient())
    report = verify(out_dir)
    failures = [t.name for t in report.tests if t.status == "fail"]
    assert report.all_passed, f"freshly templated language failed: {failures}"


def test_template_path_is_fast(tmp_path):
    """Performance pin. Generating an s_expression language must take
    well under 10 seconds (was ~15 minutes before the template path).
    Wide margin so this isn't flaky on slow CI."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "speedy",
    )
    t0 = time.monotonic()
    generate_all(spec, output_root=tmp_path, client=_FakeClient())
    elapsed = time.monotonic() - t0
    assert elapsed < 10.0, (
        f"s_expression generation took {elapsed:.1f}s; expected < 10s. "
        "Template path may be broken (LLM is being called for core components)."
    )


def test_c_like_does_not_use_template_path(tmp_path):
    """Sanity check: only s_expression triggers the template path. c_like
    languages must still go through the LLM (we don't have a reference
    for them in this PR)."""
    from forge.orchestrator.generator import reference_compiler_for
    c_spec = {"options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
              "lang_name": "ctest"}
    p_spec = {"options": {"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"},
              "lang_name": "ptest"}
    s_spec = {"options": {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
              "lang_name": "stest"}
    assert reference_compiler_for(c_spec) is None
    assert reference_compiler_for(p_spec) is None
    assert reference_compiler_for(s_spec) is not None
    assert reference_compiler_for(s_spec).name == "lisplang"
