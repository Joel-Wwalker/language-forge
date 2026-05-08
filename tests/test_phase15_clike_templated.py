"""Phase 1.5 Stages B + C — c_like is now templated from toylang.

This is the structural-fix headline test. A c_like generation through
`generate_all` should now:
  - Make zero LLM calls (resolver is cached or LLM-bypassed; the
    templated components don't invoke the model).
  - Complete in seconds, not minutes.
  - Pass 8/8 canonical tests (correctness inherited from the toylang
    reference).

Stage B: c_like is registered in REFERENCE_COMPILERS.
Stage C: README, LANGUAGE.md, and tests are templated/copied from
toylang rather than LLM-generated.
"""
from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.generator import (
    generate_all, REFERENCE_COMPILERS, reference_compiler_for,
)


WORKSPACE = Path(__file__).resolve().parents[1]


class _CountingFake:
    """Fake LLM client that records every call. Templated c_like
    generations should produce an empty call log."""
    log_dir = None
    model = "fake-stage-bc"
    telemetry = None

    def __init__(self):
        self.calls: list[str] = []

    def _emit(self, tag: str) -> None:
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, tag, time.monotonic() - 0.01,
                        100, 50, 1, True, None)
        self.calls.append(tag)

    def call_code(self, prompt, *, tag="code", **kw):
        self._emit(tag)
        return "# fake stub\n"

    def call_json(self, *a, **kw):
        self._emit(kw.get("tag", "json"))
        return {"tests": []}

    def call_chat(self, *a, **kw):
        return ""


# ---------------------------------------------------------------------------
# Stage B: registration is correct
# ---------------------------------------------------------------------------

def test_c_like_is_registered_in_reference_compilers():
    """Stage B: REFERENCE_COMPILERS must include c_like → toylang."""
    assert "c_like" in REFERENCE_COMPILERS
    assert REFERENCE_COMPILERS["c_like"].name == "toylang"
    assert REFERENCE_COMPILERS["c_like"].exists()


def test_reference_compiler_for_returns_toylang_on_c_like_spec():
    """Stage B: the per-spec lookup correctly resolves c_like to
    toylang."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "test_lookup",
    )
    ref = reference_compiler_for(spec)
    assert ref is not None
    assert ref.name == "toylang"


# ---------------------------------------------------------------------------
# Stages B + C: c_like generation through generate_all
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_templated_c_like_makes_zero_llm_calls(tmp_path):
    """Headline result. A c_like dynamic generation through the new
    templated path should make ZERO LLM calls.

    Compare to the LLM-driven path which makes 9 (resolver + 5
    components + tests-bulk + readme + language_reference)."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "zero_llm_clike",
    )
    client = _CountingFake()
    generate_all(spec, output_root=tmp_path, client=client,
                 verify_after_generation=False)
    assert client.calls == [], (
        f"templated c_like should make ZERO LLM calls; got {client.calls}"
    )


@pytest.mark.slow
def test_templated_c_like_completes_in_under_30_seconds(tmp_path):
    """Phase 1.5 acceptance: templated path should complete in ≤30s
    (vs. ~6 minutes for the LLM-driven path)."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "fast_clike",
    )
    t0 = time.monotonic()
    generate_all(spec, output_root=tmp_path, client=_CountingFake(),
                 verify_after_generation=False)
    elapsed = time.monotonic() - t0
    assert elapsed < 30.0, (
        f"templated c_like took {elapsed:.1f}s; expected <30s"
    )


@pytest.mark.slow
def test_templated_c_like_passes_canonical_tests(tmp_path):
    """Stage B/C correctness: the templated c_like must pass all 8
    canonical tests. If this fails, the template substitution layer
    or the routing has broken correctness."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "canonical_clike",
    )
    out_dir = generate_all(spec, output_root=tmp_path, client=_CountingFake())
    summary = json.loads(
        (out_dir / "generation_summary.json").read_text(encoding="utf-8"))
    canonical = summary["canonical_tests"]
    assert canonical["total"] == 8
    assert canonical["passed"] == 8, (
        f"templated c_like failed canonical tests: {canonical}"
    )


@pytest.mark.slow
def test_templated_c_like_produces_all_required_files(tmp_path):
    """The output language directory should have every file a c_like
    user expects: parser.py, lexer.py, codegen.py, runtime.py,
    stdlib.py, README.md, LANGUAGE.md, INSTALL.md, LICENSE,
    pyproject.toml, compile.py, repl.html, resolved_spec.json,
    plus tests/."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "complete_clike",
    )
    out_dir = generate_all(spec, output_root=tmp_path, client=_CountingFake(),
                           verify_after_generation=False)
    expected = {
        "parser.py", "lexer.py", "codegen.py", "runtime.py", "stdlib.py",
        "README.md", "LANGUAGE.md", "INSTALL.md", "LICENSE",
        "pyproject.toml", "compile.py", "repl.html", "resolved_spec.json",
        "__init__.py",
    }
    have = {p.name for p in out_dir.iterdir() if p.is_file()}
    missing = expected - have
    assert not missing, f"templated c_like missing files: {missing}"
    assert (out_dir / "tests").is_dir()
    test_files = {p.name for p in (out_dir / "tests").iterdir()
                  if p.is_file()}
    # 8 canonical tests × 2 files each (.<ext> + .expected_output.txt)
    assert len(test_files) >= 16, (
        f"expected ≥16 test files (8 source + 8 expected), got {len(test_files)}"
    )


@pytest.mark.slow
def test_templated_c_like_with_keyword_overrides_passes_canonical(tmp_path):
    """End-to-end Stage A + B integration: spec with custom keyword
    overrides goes through generate_all and produces a working
    language with the custom spellings."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "custom_keywords_clike",
    )
    cust = dict(spec.get("customization") or {})
    cust["keyword_overrides"] = {
        "var": "let", "func": "fn",
        "if": "if", "else": "else", "while": "while", "return": "return",
        "true": "true", "false": "false", "null": "null",
    }
    spec["customization"] = cust
    out_dir = generate_all(spec, output_root=tmp_path, client=_CountingFake())

    # Confirm grammar uses new keywords.
    parser_text = (out_dir / "parser.py").read_text(encoding="utf-8")
    assert '"let"' in parser_text and '"fn"' in parser_text

    # Confirm canonical tests still pass.
    summary = json.loads(
        (out_dir / "generation_summary.json").read_text(encoding="utf-8"))
    assert summary["canonical_tests"]["passed"] == 8


@pytest.mark.slow
def test_templated_c_like_readme_uses_c_like_syntax(tmp_path):
    """Stage C: the generated README's `## At a glance` section
    should show c_like syntax (not Lisp parens / Forth postfix).
    Confirms `_render_templated_readme` handles c_like correctly."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "readme_check",
    )
    out_dir = generate_all(spec, output_root=tmp_path, client=_CountingFake(),
                           verify_after_generation=False)
    readme = (out_dir / "README.md").read_text(encoding="utf-8")
    # c_like signatures: braces + semicolons.
    assert "{" in readme and "}" in readme, (
        "README should show c_like braces"
    )
    assert ";" in readme, "README should show c_like semicolons"
    # Should NOT show Lisp-style example.
    assert "(define" not in readme, (
        "README should not show Lisp syntax for c_like"
    )


@pytest.mark.slow
def test_python_like_still_uses_llm_path(tmp_path):
    """Stage B explicitly defers python_like (no reference exists).
    Pin that python_like still routes through the LLM path so a
    future python_like reference doesn't accidentally land in a
    templated state without explicit registration.

    This test uses the LLM path so it'd make many call_code calls.
    We only check that the LLM IS being invoked, not the output
    quality."""
    spec = build_spec(
        {"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"},
        "still_llm_pylike",
    )
    client = _CountingFake()
    # We expect this to fail at some component step because the fake
    # client returns stubs that don't satisfy real schemas. That's
    # fine — we just want to confirm the LLM path was taken.
    try:
        generate_all(spec, output_root=tmp_path, client=client,
                     only=["readme"], verify_after_generation=False)
    except Exception:
        pass
    # python_like must hit the LLM (no reference compiler).
    assert any("gen-readme" in c for c in client.calls), (
        f"python_like should still call the LLM for readme; "
        f"calls were: {client.calls}"
    )
