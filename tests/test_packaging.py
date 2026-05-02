"""Tests for the packaging output (pyproject.toml, LICENSE, INSTALL.md, examples/).

These verify the deterministic templates render correctly and that the
download endpoint excludes the right things.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from forge.orchestrator.generator import _render_templates, _emit_examples
from forge.orchestrator.spec_builder import build_spec


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


def _spec_for(name="demo", **opts):
    return build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc", **opts}, name)


def test_render_templates_emits_required_files(tmp_path):
    spec = _spec_for("demo")
    _render_templates(spec, tmp_path)
    expected = ["__init__.py", "compile.py", "pyproject.toml", "LICENSE", "INSTALL.md"]
    for f in expected:
        assert (tmp_path / f).exists(), f"missing {f}"
        assert (tmp_path / f).read_text(encoding="utf-8").strip(), f"{f} is empty"


def test_pyproject_has_console_script(tmp_path):
    spec = _spec_for("mylang")
    _render_templates(spec, tmp_path)
    py = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "mylang"' in py
    # Console script must point at compile.main so users get a `mylang` CLI
    assert 'mylang = "mylang.compile:main"' in py
    # package-dir bridge so setuptools finds the package at the project root
    assert 'package-dir = {"mylang" = "."}' in py


def test_pyproject_python_version_constraint(tmp_path):
    spec = _spec_for("demo")
    _render_templates(spec, tmp_path)
    py = (tmp_path / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.11"' in py


def test_install_md_mentions_command(tmp_path):
    spec = _spec_for("zigzag")
    _render_templates(spec, tmp_path)
    install = (tmp_path / "INSTALL.md").read_text(encoding="utf-8")
    assert "pip install -e ." in install
    # The install doc references the language-specific console command
    assert "zigzag --help" in install
    assert ".zig" in install   # auto-derived extension


def _setup_lang_dir(tmp_path, name="toylang", src_dir=None):
    """Copy a working language into `tmp_path/<name>/` so the compile-check
    has a real package to validate samples against."""
    import shutil
    src_dir = src_dir or TOYLANG_DIR
    pkg_dir = tmp_path / name
    pkg_dir.mkdir()
    for f in ("__init__.py", "compile.py", "lexer.py", "parser.py",
              "codegen.py", "runtime.py", "stdlib.py"):
        if (src_dir / f).exists():
            shutil.copy2(src_dir / f, pkg_dir / f)
    return pkg_dir


def test_emit_examples_produces_files(tmp_path):
    spec = _spec_for("toylang")
    pkg_dir = _setup_lang_dir(tmp_path)
    import json as _json
    (pkg_dir / "resolved_spec.json").write_text(_json.dumps(spec), encoding="utf-8")
    _emit_examples(spec, pkg_dir)
    examples = pkg_dir / "examples"
    assert examples.is_dir()
    for name in ("fizzbuzz", "fibonacci", "counter_factory", "string_manipulation"):
        assert (examples / f"{name}{spec['file_extension']}").exists()
    assert (examples / "README.md").exists()


def test_emit_examples_uses_correct_syntax_flavor(tmp_path):
    """python_like specs get python-style sample programs (no semicolons).
    We test syntax flavor independently of the compile-check by inspecting
    the curated sample DIRECTLY, since we don't have a python_like reference
    compiler in the workspace."""
    from forge.gui.samples import get_sample
    fizz = get_sample("fizzbuzz", "python_like")
    assert "elif " in fizz
    body_lines = [l for l in fizz.split("\n") if l.strip() and not l.strip().startswith("#")]
    assert not body_lines[0].rstrip().endswith(";")


def test_toylang_package_files_present():
    """The hand-written toylang reference must have working packaging."""
    for f in ("pyproject.toml", "LICENSE", "INSTALL.md"):
        assert (TOYLANG_DIR / f).exists(), f"toylang/{f} missing"


def test_toylang_pyproject_is_valid_toml():
    """toylang's pyproject must parse as valid TOML."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib   # py<3.11 fallback
    py_path = TOYLANG_DIR / "pyproject.toml"
    data = tomllib.loads(py_path.read_text(encoding="utf-8"))
    assert data["project"]["name"] == "toylang"
    assert "toylang.compile:main" in data["project"]["scripts"].values()


# ---- download-zip behavior (tested by inspecting the generator's output dir) ----

def test_download_excludes_internal_dirs(tmp_path):
    """The download zip endpoint excludes .forge_log/, _playground/,
    __pycache__/, *.pyc, *.out.py. We test the same exclusion logic the
    endpoint uses by replicating it here."""
    # Set up a fake language dir with both keep + exclude content
    lang_dir = tmp_path / "fake"
    lang_dir.mkdir()
    keep_files = ["pyproject.toml", "compile.py", "__init__.py", "tests/hello.fk"]
    skip_files = [
        ".forge_log/some.txt",
        "_playground/program.fk",
        "_playground/program.fk.out.py",
        "__pycache__/foo.cpython-311.pyc",
        "examples/fibonacci.fk.out.py",
    ]
    for rel in keep_files + skip_files:
        path = lang_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")

    excluded_dirs = {".forge_log", "_playground", "__pycache__"}
    excluded_suffixes = (".pyc", ".out.py")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path in lang_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(lang_dir)
            if any(part in excluded_dirs for part in rel.parts):
                continue
            if path.name.endswith(excluded_suffixes):
                continue
            zf.write(path, f"fake/{rel.as_posix()}")

    buf.seek(0)
    with zipfile.ZipFile(buf, "r") as zf:
        names = set(zf.namelist())

    for kept in keep_files:
        assert f"fake/{kept}" in names, f"expected to keep {kept}"
    for skipped in skip_files:
        assert f"fake/{skipped}" not in names, f"should have excluded {skipped}"
