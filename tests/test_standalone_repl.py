"""Tests for the single-HTML-file Pyodide REPL output."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.orchestrator.generator import render_standalone_repl
from forge.orchestrator.spec_builder import build_spec


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


def test_renders_html_for_toylang(tmp_path):
    """Render against a copy of toylang. Result must be a self-contained HTML
    page that embeds the compiler files + canonical examples."""
    # Copy toylang into the tmp dir so we can render without polluting workspace
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(TOYLANG_DIR, work, ignore=shutil.ignore_patterns(".forge_log", "__pycache__", "_playground", "*.out.py"))

    spec = json.loads((work / "resolved_spec.json").read_text(encoding="utf-8"))
    html = render_standalone_repl(spec, work)

    assert "<!doctype html>" in html.lower()
    assert "Pyodide" in html
    assert "CodeMirror" in html
    assert "toylang" in html
    # File should also be written to disk
    assert (work / "repl.html").exists()
    assert (work / "repl.html").read_text(encoding="utf-8") == html


def test_repl_embeds_compiler_files(tmp_path):
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(TOYLANG_DIR, work, ignore=shutil.ignore_patterns(".forge_log", "__pycache__", "_playground", "*.out.py"))
    spec = json.loads((work / "resolved_spec.json").read_text(encoding="utf-8"))
    html = render_standalone_repl(spec, work)

    # Pull the embedded compiler-files JSON blob from the page
    import re
    m = re.search(r'<script id="compiler-files" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    assert m, "could not find compiler-files JSON blob"
    files = json.loads(m.group(1))

    # Every required compiler file is present and non-empty
    for required in ("__init__.py", "lexer.py", "parser.py", "codegen.py", "runtime.py"):
        assert required in files, f"missing {required} in embedded files"
        assert files[required].strip(), f"{required} is empty"


def test_repl_embeds_canonical_examples(tmp_path):
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(TOYLANG_DIR, work, ignore=shutil.ignore_patterns(".forge_log", "__pycache__", "_playground", "*.out.py"))
    spec = json.loads((work / "resolved_spec.json").read_text(encoding="utf-8"))
    html = render_standalone_repl(spec, work)

    import re
    m = re.search(r'<script id="examples-data" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    assert m, "examples blob missing"
    examples = json.loads(m.group(1))
    # At least the canonical 8 should be embedded (toylang has them all)
    for canonical in ("hello_world", "arithmetic", "loops", "closures"):
        assert canonical in examples
        assert examples[canonical].strip()


def test_repl_picks_correct_codemirror_mode(tmp_path):
    """python_like spec → python mode in the REPL."""
    spec = build_spec({"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"}, "demo")
    work = tmp_path / "demo"
    work.mkdir()
    # Minimal compiler stubs so render_standalone_repl has something to embed
    for f in ("__init__.py", "parser.py", "codegen.py", "runtime.py"):
        (work / f).write_text("# stub\n", encoding="utf-8")
    (work / "resolved_spec.json").write_text(json.dumps(spec), encoding="utf-8")

    html = render_standalone_repl(spec, work)
    # The render passes syntax=spec.options.syntax to the template; the template
    # uses it to pick CodeMirror's mode.
    assert '"python_like"' in html


def test_repl_contains_run_button_and_editor(tmp_path):
    import shutil
    work = tmp_path / "toylang"
    shutil.copytree(TOYLANG_DIR, work, ignore=shutil.ignore_patterns(".forge_log", "__pycache__", "_playground", "*.out.py"))
    spec = json.loads((work / "resolved_spec.json").read_text(encoding="utf-8"))
    html = render_standalone_repl(spec, work)

    assert 'id="run-btn"' in html
    assert 'id="editor"' in html
    assert 'id="output"' in html
    # Pyodide CDN reference
    assert "cdn.jsdelivr.net/pyodide" in html


def test_toylang_repl_was_backfilled():
    """The actual toylang directory has a working repl.html."""
    repl = TOYLANG_DIR / "repl.html"
    assert repl.exists(), "toylang/repl.html was not backfilled"
    content = repl.read_text(encoding="utf-8")
    assert len(content) > 10000, "repl.html suspiciously small"
    assert "toylang" in content
    assert "Pyodide" in content
