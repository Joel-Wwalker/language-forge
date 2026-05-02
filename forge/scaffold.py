"""Scaffold a starter project for an existing generated language.

Usage:
    forge init <project_name> [--lang <lang>] [--dir <parent>]

Creates a new directory containing:
    main.<ext>           a runnable starter program using the stdlib
    README.md            project intro and run instructions
    pyproject.toml       so the project itself is pip-installable later
    run.sh               compile + execute in one shot
    examples/            copies of the language's curated samples

The chosen language's compiler is NOT bundled. Users install it separately
(`pip install -e .` from the language directory). The starter README walks
them through it.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader


HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"


def _load_lang_spec(lang_dir: Path) -> dict:
    spec_path = lang_dir / "resolved_spec.json"
    if spec_path.exists():
        return json.loads(spec_path.read_text(encoding="utf-8"))
    # Fallback: schema example for toylang
    fallback = HERE.parent / "schemas" / "example_toylang_spec.json"
    if lang_dir.name == "toylang" and fallback.exists():
        return json.loads(fallback.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"no resolved_spec.json in {lang_dir}")


def init_project(
    project_name: str,
    lang: str = "toylang",
    parent_dir: Optional[Path] = None,
    workspace_root: Optional[Path] = None,
) -> Path:
    """Create a starter project. Returns the project directory."""
    if not project_name.isidentifier():
        raise ValueError("project name must be a Python identifier (letters, digits, underscore; no leading digit)")

    workspace_root = workspace_root or Path.cwd()
    parent_dir = (parent_dir or workspace_root).resolve()
    project_dir = parent_dir / project_name
    if project_dir.exists():
        raise FileExistsError(f"{project_dir} already exists")

    # Locate the language's resolved spec.
    lang_dir = (workspace_root / "generated" / lang).resolve()
    if not lang_dir.exists():
        raise FileNotFoundError(
            f"language '{lang}' not found at {lang_dir}. "
            "Run `python -m forge create --name {lang}` first, or pick an existing one."
        )
    spec = _load_lang_spec(lang_dir)

    project_dir.mkdir(parents=True)

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    ctx = {
        "project_name": project_name,
        "lang_name": spec["lang_name"],
        "file_extension": spec["file_extension"],
        "syntax": spec["options"]["syntax"],
    }

    # Render the starter files.
    rendered = {
        f"main{ctx['file_extension']}": env.get_template("starter_program.j2").render(**ctx),
        "README.md":      env.get_template("starter_README.md.j2").render(**ctx),
        "pyproject.toml": env.get_template("starter_pyproject.toml.j2").render(**ctx),
        "run.sh":         env.get_template("starter_run.sh.j2").render(**ctx),
    }
    for filename, content in rendered.items():
        (project_dir / filename).write_text(content, encoding="utf-8")
    # run.sh needs the executable bit (no-op on Windows but does no harm)
    try:
        (project_dir / "run.sh").chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR |
                                       stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    except OSError:
        pass

    # Copy curated examples from the language's `examples/` if present.
    src_examples = lang_dir / "examples"
    if src_examples.exists():
        dst_examples = project_dir / "examples"
        dst_examples.mkdir()
        for src in src_examples.iterdir():
            if src.is_file():
                shutil.copy2(src, dst_examples / src.name)

    return project_dir
