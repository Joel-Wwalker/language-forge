"""Tests for the playground's smart compile-error hints.

`_explain_compile_error` reads a Lark traceback plus the language's spec
and produces a one-line tip the GUI shows above the raw stderr. This is
the user-facing fix for the recurring "compile failed" reports where the
underlying issue was a comment-style mismatch.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.gui.app import _explain_compile_error


WORKSPACE = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _fixture_lang(name: str) -> Path:
    """Resolve a tracked stub language fixture under `tests/fixtures/`.

    `_explain_compile_error` only reads `resolved_spec.json` from the
    language dir (`comment_syntax`, `options.syntax`, `literals.string`).
    A minimal stub spec is enough to exercise every hint branch without
    requiring an LLM-generated language to be present on disk."""
    return FIXTURES / name


def _stderr_unexpected_char(ch: str, line: int = 1, col: int = 1) -> str:
    return (
        "Traceback (most recent call last):\n"
        "  File \"compile.py\", line 36, in main\n"
        "    tree = parse(src)\n"
        f"lark.exceptions.UnexpectedCharacters: No terminal matches '{ch}' "
        f"in the current parser context, at line {line} col {col}\n"
    )


def _stderr_unexpected_token(kind: str, value: str, line: int = 1) -> str:
    return (
        "Traceback (most recent call last):\n"
        f"lark.exceptions.UnexpectedToken: Unexpected token Token('{kind}', '{value}') "
        f"at line {line}, column 1.\n"
        "Expected one of: LPAR SEMICOLON\n"
    )


def test_hint_for_slash_in_block_only_language():
    """love has comment_style=block. // is rejected. Hint should suggest /* */"""
    lang = _fixture_lang("love")
    hint = _explain_compile_error(_stderr_unexpected_char("/"), lang)
    assert hint is not None
    assert "block comments" in hint or "/*" in hint
    assert "//" in hint        # mentions what to replace


def test_hint_for_slash_in_python_like_language():
    """hardcombo is python_like. # is the line comment. Hint should suggest #."""
    lang = _fixture_lang("hardcombo")
    hint = _explain_compile_error(_stderr_unexpected_char("/"), lang)
    assert hint is not None
    assert "#" in hint


def test_hint_for_hash_in_c_like_language():
    """toylang uses // for line comments. # is rejected."""
    hint = _explain_compile_error(_stderr_unexpected_char("#"), WORKSPACE / "generated" / "toylang")
    assert hint is not None
    assert "//" in hint


def test_hint_for_assignment_token_rejected():
    """Some languages have parsers that don't accept assignment as a statement."""
    lang = _fixture_lang("love")
    hint = _explain_compile_error(_stderr_unexpected_token("EQUAL", "=", line=16),
                                  lang)
    assert hint is not None
    assert "assignment" in hint.lower()
    assert "16" in hint


def test_hint_for_slash_tokenized_as_factor_op():
    """`//` mis-tokenized as two FACTOR_OPs (lexer has no line-comment rule).
    The hint must still point at the comment-style mismatch and offer the
    Fix comments button."""
    lang = _fixture_lang("love")
    stderr = (
        "lark.exceptions.UnexpectedToken: Unexpected token Token('FACTOR_OP', '/') "
        "at line 1, column 1.\n"
    )
    hint = _explain_compile_error(stderr, lang)
    assert hint is not None
    assert "//" in hint
    assert "/*" in hint or "block" in hint
    assert "Fix comments" in hint


def test_hint_for_factor_op_slash_in_python_target():
    """Same FACTOR_OP `/` error on a python_like language should point at `#`."""
    lang = _fixture_lang("hardcombo")
    stderr = (
        "lark.exceptions.UnexpectedToken: Unexpected token Token('FACTOR_OP', '/') "
        "at line 1, column 1.\n"
    )
    hint = _explain_compile_error(stderr, lang)
    assert hint is not None
    assert "#" in hint
    assert "Fix comments" in hint


def test_hint_returns_none_for_empty_stderr():
    assert _explain_compile_error("", WORKSPACE / "generated" / "toylang") is None


def test_hint_returns_none_for_unknown_lang():
    """Returns None gracefully if the language directory doesn't exist."""
    h = _explain_compile_error(_stderr_unexpected_char("/"), WORKSPACE / "generated" / "nonexistent")
    assert h is None


def test_hint_passes_through_when_no_pattern_matches():
    """A traceback that doesn't have a recognized lark error returns None."""
    h = _explain_compile_error("RuntimeError: something completely different\n",
                               WORKSPACE / "generated" / "toylang")
    assert h is None
