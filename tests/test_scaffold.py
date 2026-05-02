"""Tests for `forge init`."""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.scaffold import init_project


WORKSPACE = Path(__file__).resolve().parents[1]


def test_init_creates_starter_files(tmp_path):
    out = init_project("mytool", lang="toylang", parent_dir=tmp_path,
                       workspace_root=WORKSPACE)
    assert out.exists()
    for f in ("main.toy", "README.md", "pyproject.toml", "run.sh"):
        assert (out / f).exists(), f"{f} not scaffolded"


def test_init_main_file_uses_correct_extension(tmp_path):
    out = init_project("appname", lang="toylang", parent_dir=tmp_path,
                       workspace_root=WORKSPACE)
    assert (out / "main.toy").exists()
    main = (out / "main.toy").read_text(encoding="utf-8")
    assert "func greet" in main
    assert "list(" in main          # uses the new stdlib
    assert "appname" in main        # project name interpolated


def test_init_starter_program_compiles_and_runs(tmp_path):
    """The scaffolded main.toy must actually compile and run successfully
    against the toylang reference compiler."""
    import subprocess, sys, os
    out = init_project("smoke_app", lang="toylang", parent_dir=tmp_path,
                       workspace_root=WORKSPACE)
    main = out / "main.toy"

    toylang_dir = WORKSPACE / "generated" / "toylang"
    env = {**os.environ, "PYTHONPATH": str(WORKSPACE / "generated")}

    # Compile
    proc = subprocess.run(
        [sys.executable, str(toylang_dir / "compile.py"), str(main)],
        capture_output=True, text=True, timeout=20, cwd=str(toylang_dir), env=env,
    )
    assert proc.returncode == 0, f"compile failed: {proc.stderr}"

    out_py = main.with_suffix(main.suffix + ".out.py")
    assert out_py.exists()

    # Run
    run = subprocess.run(
        [sys.executable, str(out_py)],
        capture_output=True, text=True, timeout=20, env=env,
    )
    assert run.returncode == 0, f"run failed: {run.stderr}"
    # The starter prints three greetings.
    lines = [l for l in run.stdout.splitlines() if l]
    assert len(lines) == 3
    assert all("Hello" in l for l in lines)
    assert "smoke_app" in run.stdout    # project name embedded in output


def test_init_rejects_invalid_name(tmp_path):
    with pytest.raises(ValueError):
        init_project("not a valid name", parent_dir=tmp_path, workspace_root=WORKSPACE)


def test_init_refuses_to_overwrite(tmp_path):
    init_project("once", parent_dir=tmp_path, workspace_root=WORKSPACE)
    with pytest.raises(FileExistsError):
        init_project("once", parent_dir=tmp_path, workspace_root=WORKSPACE)


def test_init_unknown_lang_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        init_project("x", lang="nonexistent_language",
                     parent_dir=tmp_path, workspace_root=WORKSPACE)


def test_init_copies_examples_dir(tmp_path):
    """If the language has an examples/ directory, the scaffold copies it."""
    out = init_project("with_examples", lang="toylang",
                       parent_dir=tmp_path, workspace_root=WORKSPACE)
    examples = out / "examples"
    assert examples.is_dir()
    # toylang has at least fizzbuzz + fibonacci shipped
    assert any(p.name == "fizzbuzz.toy" for p in examples.iterdir())


def test_init_pyproject_has_correct_name(tmp_path):
    out = init_project("specialname", parent_dir=tmp_path, workspace_root=WORKSPACE)
    py = (out / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "specialname"' in py
