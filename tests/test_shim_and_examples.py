"""Tests for the runtime shim and the example-coverage filter.

These guard the fix for the bug where new examples (wordcount, args_demo,
list_operations) failed in the in-browser REPL of LLM-generated languages
because their runtime didn't have the helpers the examples needed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from forge.orchestrator.generator import (
    apply_runtime_shim,
    _emit_examples,
    _runtime_available_helpers,
    _codegen_imports,
    _SAMPLE_REQUIREMENTS,
)
from forge.orchestrator.spec_builder import build_spec


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


# ---------------------------------------------------------------------------
# Runtime shim
# ---------------------------------------------------------------------------

def test_apply_runtime_shim_adds_missing_helpers(tmp_path):
    """A bare runtime gets every missing helper appended."""
    rt = tmp_path / "runtime.py"
    rt.write_text(
        "def toy_print(*args): print(*args)\n"
        "def toy_len(s): return len(s)\n"
        "def toy_str(v): return str(v)\n"
        "def toy_truthy(v): return bool(v)\n",
        encoding="utf-8",
    )
    changed = apply_runtime_shim(tmp_path)
    assert changed is True
    new_rt = rt.read_text(encoding="utf-8")
    # Original helpers preserved
    assert "def toy_print" in new_rt
    assert "def toy_truthy" in new_rt
    # New helpers appended
    for fn in ("toy_list", "toy_get", "toy_dict", "toy_argv", "toy_split"):
        assert f"def {fn}" in new_rt
    # Marker comment present
    assert "FORGE_STDLIB_SHIM_BEGIN" in new_rt
    assert "FORGE_STDLIB_SHIM_END" in new_rt


def test_apply_runtime_shim_is_idempotent(tmp_path):
    rt = tmp_path / "runtime.py"
    rt.write_text("def toy_print(*a): print(*a)\n", encoding="utf-8")
    apply_runtime_shim(tmp_path)
    first = rt.read_text(encoding="utf-8")
    apply_runtime_shim(tmp_path)
    second = rt.read_text(encoding="utf-8")
    assert first == second   # second call is a no-op


def test_apply_runtime_shim_skips_complete_runtime(tmp_path):
    """A runtime that already has every helper isn't modified."""
    full = ""
    for name in ("toy_print", "toy_input", "toy_list", "toy_get", "toy_set",
                 "toy_push", "toy_pop", "toy_dict", "toy_has", "toy_keys",
                 "toy_range", "toy_split", "toy_join", "toy_upper", "toy_lower",
                 "toy_replace", "toy_int", "toy_float",
                 "toy_read_file", "toy_write_file", "toy_argv", "toy_exit"):
        full += f"def {name}(*a, **k): pass\n"
    (tmp_path / "runtime.py").write_text(full, encoding="utf-8")
    changed = apply_runtime_shim(tmp_path)
    assert changed is False


def test_apply_runtime_shim_no_runtime_file(tmp_path):
    """Returns False (no error) when runtime.py doesn't exist."""
    assert apply_runtime_shim(tmp_path) is False


# ---------------------------------------------------------------------------
# Coverage detection
# ---------------------------------------------------------------------------

def test_runtime_helpers_detected_by_def_lines(tmp_path):
    (tmp_path / "runtime.py").write_text(
        "def toy_print(): pass\n"
        "def toy_list(*items): return list(items)\n"
        "def toy_argv(): return []\n",
        encoding="utf-8",
    )
    avail = _runtime_available_helpers(tmp_path)
    assert {"print", "list", "argv"}.issubset(avail)
    # str, len, print are in the always-on baseline
    assert {"print", "len", "str"}.issubset(avail)
    # things we didn't define aren't claimed
    assert "dict" not in avail


def test_codegen_imports_extracted_from_aliases(tmp_path):
    (tmp_path / "codegen.py").write_text(
        'from x.runtime import toy_print as print, toy_list as list, toy_get as get\n',
        encoding="utf-8",
    )
    imports = _codegen_imports(tmp_path)
    assert {"print", "list", "get"}.issubset(imports)


# ---------------------------------------------------------------------------
# Example filter: never ship a sample whose helpers aren't both in the
# runtime AND imported by the codegen.
# ---------------------------------------------------------------------------

def test_emit_examples_skips_samples_with_missing_runtime(tmp_path):
    """A bare runtime + codegen with only the basic 4 imports yields only the
    samples that depend solely on print/len/str."""
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "demo")
    # Runtime missing list/get/dict/argv etc.
    (tmp_path / "runtime.py").write_text(
        "def toy_print(*a): pass\n"
        "def toy_len(s): return len(s)\n"
        "def toy_str(v): return str(v)\n"
        "def toy_truthy(v): return bool(v)\n",
        encoding="utf-8",
    )
    (tmp_path / "codegen.py").write_text(
        "from demo.runtime import (\n"
        "    toy_print as print,\n"
        "    toy_len as len,\n"
        "    toy_str as str,\n"
        ")\n",
        encoding="utf-8",
    )
    _emit_examples(spec, tmp_path)
    shipped = sorted(p.stem for p in (tmp_path / "examples").glob(f"*{spec['file_extension']}"))
    # The new examples need helpers we don't have; they should be filtered out.
    for sample_needing_more in ("wordcount", "list_operations", "args_demo"):
        assert sample_needing_more not in shipped, f"{sample_needing_more} should have been filtered"


def test_emit_examples_ships_all_when_runtime_is_complete(tmp_path):
    """A full toylang copy as `tmp_path/toylang/` should ship every curated sample."""
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "toylang")
    pkg_dir = tmp_path / "toylang"
    pkg_dir.mkdir()
    for name in ("__init__.py", "compile.py", "lexer.py", "parser.py",
                 "codegen.py", "runtime.py", "stdlib.py"):
        shutil.copy2(TOYLANG_DIR / name, pkg_dir / name)
    import json as _json
    (pkg_dir / "resolved_spec.json").write_text(_json.dumps(spec), encoding="utf-8")
    _emit_examples(spec, pkg_dir)
    shipped = sorted(p.stem for p in (pkg_dir / "examples").glob(f"*{spec['file_extension']}"))
    for required in ("fizzbuzz", "fibonacci", "wordcount", "list_operations", "args_demo"):
        assert required in shipped, f"missing {required}; got {shipped}"


def test_translate_comments_block_only_target():
    """A c_like sample shipped to a block-only language gets `/* */` comments."""
    from forge.orchestrator.generator import _translate_comments
    src = '// hello\nvar x = 1;\n// trailing\n'
    out = _translate_comments(src, "c_like",
                              {"line": None, "block_open": "/*", "block_close": "*/"})
    assert "//" not in out
    assert "/* hello */" in out
    assert "/* trailing */" in out
    assert "var x = 1;" in out      # non-comment code untouched


def test_translate_comments_python_target():
    """A c_like sample shipped to a python_like language gets `#` comments."""
    from forge.orchestrator.generator import _translate_comments
    src = '// header\nvar x = 1;\n'
    out = _translate_comments(src, "c_like", {"line": "#"})
    assert "# header" in out
    assert "//" not in out


def test_translate_comments_keeps_matching_form():
    """When the comment form matches, content is unchanged."""
    from forge.orchestrator.generator import _translate_comments
    src = '// hello\nvar x = 1;\n'
    out = _translate_comments(src, "c_like",
                              {"line": "//", "block_open": "/*", "block_close": "*/"})
    assert out == src


def test_compile_check_rejects_unparseable_source(tmp_path):
    """The compile check should fail cleanly on syntax the language can't parse."""
    from forge.orchestrator.generator import _compile_check
    # Toylang is a real, complete language; use it as the test fixture.
    bad_source = "this is not valid toylang at all"
    assert _compile_check(TOYLANG_DIR, bad_source) is False


def test_compile_check_accepts_valid_source():
    from forge.orchestrator.generator import _compile_check
    good = 'print("hi");\nvar x = 5;\n'
    assert _compile_check(TOYLANG_DIR, good) is True


def test_sample_requirements_table_covers_known_samples():
    """Every curated sample we ship must have a `_SAMPLE_REQUIREMENTS` entry."""
    from forge.gui.samples import SAMPLES
    for key in SAMPLES:
        assert key in _SAMPLE_REQUIREMENTS, f"sample {key!r} has no requirements declared"


# ---------------------------------------------------------------------------
# End-to-end: run wordcount through every existing language's compile flow.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lang", ["toylang", "democ", "smoke", "love", "god"])
def test_wordcount_runs_on_each_language(lang):
    """Smoke test: every backfilled language can compile and run wordcount."""
    lang_dir = WORKSPACE / "generated" / lang
    if not lang_dir.exists():
        pytest.skip(f"{lang} not present in this workspace")

    spec = json.loads((lang_dir / "resolved_spec.json").read_text(encoding="utf-8"))
    ext = spec["file_extension"]
    src = lang_dir / "examples" / f"wordcount{ext}"
    if not src.exists():
        pytest.skip(f"wordcount{ext} not shipped to {lang} (insufficient stdlib coverage)")

    # Skip languages whose lexer rejects `//` line comments. The samples
    # carry `//`-style comments; converting them per-language is a future
    # improvement.
    cs = spec.get("comment_syntax", {})
    if cs.get("line") not in ("//", "#"):
        pytest.skip(f"{lang} comment_style is incompatible with the sample's `//` comments")

    import os
    env = {**os.environ, "PYTHONPATH": str(WORKSPACE / "generated")}

    compile_proc = subprocess.run(
        [sys.executable, str(lang_dir / "compile.py"), str(src)],
        capture_output=True, text=True, timeout=20,
        cwd=str(lang_dir), env=env,
    )
    assert compile_proc.returncode == 0, f"{lang} compile failed: {compile_proc.stderr}"

    out_py = src.with_suffix(src.suffix + ".out.py")
    run = subprocess.run(
        [sys.executable, str(out_py)],
        capture_output=True, text=True, timeout=20,
        cwd=str(lang_dir), env=env,
    )
    assert run.returncode == 0, f"{lang} run failed: {run.stderr}"
    # All variants should produce these visible markers.
    assert "9" in run.stdout              # word count
    assert "the" in run.stdout            # frequency lookup
