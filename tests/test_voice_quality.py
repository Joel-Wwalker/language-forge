"""Tests that guard the project's writing voice.

Forbid em-dashes, en-dashes, and a small set of AI-tell adjectives in
user-facing text. These patterns are conspicuous and the user wants them
gone.
"""
from __future__ import annotations

from pathlib import Path

import pytest


WORKSPACE = Path(__file__).resolve().parents[1]


# Files we treat as user-facing voice. The orchestrator's code comments are
# allowed to use whatever style, but anything a user sees must stay clean.
USER_FACING = [
    WORKSPACE / "README.md",
    WORKSPACE / "forge" / "templates" / "INSTALL.md.j2",
    WORKSPACE / "forge" / "templates" / "LICENSE.j2",
    WORKSPACE / "forge" / "templates" / "pyproject.toml.j2",
    WORKSPACE / "forge" / "templates" / "package_init.py.j2",
    WORKSPACE / "forge" / "templates" / "standalone_repl.html.j2",
    WORKSPACE / "forge" / "templates" / "compiler_entry.py.j2",
    WORKSPACE / "forge" / "gui" / "static" / "index.html",
]

PROMPT_FILES = sorted((WORKSPACE / "forge" / "prompts").glob("*.md"))


@pytest.mark.parametrize("path", USER_FACING, ids=lambda p: p.name)
def test_no_em_or_en_dashes_in_user_facing(path):
    """Em-dashes and en-dashes are AI tells. Use periods, commas, or colons."""
    if not path.exists():
        pytest.skip(f"{path} not present")
    text = path.read_text(encoding="utf-8")
    assert "—" not in text, f"em-dash (—) found in {path.name}"
    assert "–" not in text, f"en-dash (–) found in {path.name}"


@pytest.mark.parametrize("path", PROMPT_FILES, ids=lambda p: p.name)
def test_no_em_or_en_dashes_in_prompts(path):
    """Prompts shape the LLM's output; em-dashes here leak into generated text."""
    text = path.read_text(encoding="utf-8")
    assert "—" not in text, f"em-dash in {path.name}"
    assert "–" not in text, f"en-dash in {path.name}"


# AI-style adjectives the user explicitly doesn't want. Some are unavoidable
# in technical reference docs; this is a guardrail not an absolute ban.
AI_ADJECTIVES = [
    "elegantly", "robustly", "seamlessly", "effortlessly",
    "delve", "tapestry", "realm", "underscore",
]


@pytest.mark.parametrize("path", USER_FACING, ids=lambda p: p.name)
def test_no_ai_adjectives_in_user_facing(path):
    if not path.exists():
        pytest.skip(f"{path} not present")
    text = path.read_text(encoding="utf-8").lower()
    found = [w for w in AI_ADJECTIVES if w in text]
    assert not found, f"AI tells in {path.name}: {found}"


import re


def _count_claude_prose(text: str) -> int:
    """Count proper-noun "Claude" mentions in prose, ignoring technical
    identifiers like `claude_cli` (provider name), `claude.cmd` (binary), and
    `--provider claude_cli` (CLI flag value)."""
    # Strip out the technical identifier forms we know are unavoidable.
    sanitized = re.sub(r"`?claude(?:_cli|\.cmd|\.exe)?`?", "", text)
    sanitized = sanitized.replace("Claude.ai", "")  # plan name, also fine
    return sum(1 for m in re.finditer(r"\bClaude\b", sanitized))


def test_main_readme_has_no_claude_promotion():
    """README should reference Claude as the model provider sparingly. The
    `claude_cli` provider name is allowed; effusive 'Claude does X' prose is not."""
    text = (WORKSPACE / "README.md").read_text(encoding="utf-8")
    n = _count_claude_prose(text)
    assert n <= 1, f"README has {n} prose Claude mentions; trim them"


def test_gui_index_has_no_claude_in_visible_text():
    """The GUI's visible text should not name-drop Claude. Code and
    identifiers (--provider claude_cli, the `claude` CLI) are allowed."""
    text = (WORKSPACE / "forge" / "gui" / "static" / "index.html").read_text(encoding="utf-8")
    # Strip HTML comments first (developer-only).
    visible = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    assert _count_claude_prose(visible) == 0


def test_generated_toylang_readme_is_clean_if_present():
    """If toylang/README.md exists, it shouldn't have em-dashes either."""
    p = WORKSPACE / "generated" / "toylang" / "README.md"
    if not p.exists():
        pytest.skip("toylang README not present")
    text = p.read_text(encoding="utf-8")
    assert "—" not in text
    assert "–" not in text
