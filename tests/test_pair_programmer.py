"""Tests for the AI pair programmer.

Covers system-prompt construction, code-block extraction, parser
validation of code blocks, and the chat orchestrator's retry-on-bad-
parse behavior. Uses a fake client; no real LLM calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.orchestrator.pair_programmer import (
    build_system_prompt, build_kata_addendum, extract_code_blocks,
    validate_code_block, annotate_response, chat,
)


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


def _toylang_spec():
    return json.loads((TOYLANG_DIR / "resolved_spec.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def test_system_prompt_includes_lang_essentials():
    spec = _toylang_spec()
    prompt = build_system_prompt(spec)
    assert "toylang" in prompt
    assert "c_like" in prompt
    assert "func" in prompt or "var" in prompt   # keywords
    # Must hint at fenced code blocks tagged with the language name
    assert "```toylang" in prompt or "```" in prompt


def test_system_prompt_mentions_phrasebook_when_set():
    spec = _toylang_spec()
    spec.setdefault("customization", {})["natural_language"] = {
        "var_decl": "set <name> to <value>.",
        "if_stmt": "if <cond> then <body> otherwise <else>.",
    }
    prompt = build_system_prompt(spec)
    assert "set <name> to <value>" in prompt
    assert "phrasebook" in prompt.lower()


def test_kata_addendum_hint_mode_says_no_full_solution():
    kata = {"id": "x", "title": "X", "difficulty": "easy",
            "problem": "do thing", "function_name": "fn"}
    text = build_kata_addendum(kata, "func fn() {}", "hint")
    assert "HINT" in text
    assert "do not write the full solution" in text.lower() or "nudge" in text.lower()


def test_kata_addendum_solution_mode_says_complete():
    kata = {"id": "x", "title": "X", "difficulty": "easy",
            "problem": "do thing", "function_name": "fn"}
    text = build_kata_addendum(kata, "", "solution")
    assert "SOLUTION" in text
    assert "complete" in text.lower() or "full" in text.lower()


# ---------------------------------------------------------------------------
# Code-block extraction
# ---------------------------------------------------------------------------

def test_extract_code_blocks_handles_multiple_fences():
    text = "Some prose.\n```toylang\nvar x = 1;\n```\nMore prose.\n```py\nx = 1\n```"
    blocks = extract_code_blocks(text)
    assert len(blocks) == 2
    assert blocks[0][0] == "toylang"
    assert "var x = 1;" in blocks[0][1]
    assert blocks[1][0] == "py"


def test_extract_code_blocks_handles_unlabeled_fences():
    text = "```\njust code\n```"
    blocks = extract_code_blocks(text)
    assert blocks == [("", "just code\n")]


def test_extract_code_blocks_returns_empty_when_none():
    assert extract_code_blocks("plain text, no fences") == []


# ---------------------------------------------------------------------------
# Parser validation
# ---------------------------------------------------------------------------

def test_validate_code_block_passes_for_valid_toylang():
    res = validate_code_block(TOYLANG_DIR, 'print("hi");\n')
    assert res["ok"] is True


def test_validate_code_block_fails_for_garbage():
    res = validate_code_block(TOYLANG_DIR, "this @ is not @ valid")
    assert res["ok"] is False
    assert "error" in res
    assert res["error"]    # non-empty


def test_annotate_response_marks_each_block():
    text = (
        "Here's some code:\n"
        "```toylang\nprint(\"hi\");\n```\n"
        "And bad:\n"
        "```toylang\n@@@\n```"
    )
    _, blocks = annotate_response(text, TOYLANG_DIR)
    assert len(blocks) == 2
    assert blocks[0]["ok"] is True
    assert blocks[1]["ok"] is False


# ---------------------------------------------------------------------------
# Chat orchestrator with a fake client
# ---------------------------------------------------------------------------

class FakeClient:
    """Minimal stand-in for LLMClient. Returns canned responses."""
    def __init__(self, responses):
        self.log_dir = None
        self.responses = list(responses)
        self.calls = []

    def call_chat(self, system, history, *, tag="chat", max_retries=2):
        self.calls.append({"system": system, "history": list(history), "tag": tag})
        if not self.responses:
            return ""
        return self.responses.pop(0)


def test_chat_returns_text_and_validates_blocks():
    """Happy path: assistant produces a valid block; chat returns it as-is."""
    spec = _toylang_spec()
    client = FakeClient([
        'Here you go:\n```toylang\nvar x = 5;\n```'
    ])
    out = chat(spec, TOYLANG_DIR, "make a var x", [], client, max_retries=0)
    assert "var x = 5" in out["text"]
    assert len(out["blocks"]) == 1
    assert out["blocks"][0]["ok"] is True
    assert out["retried"] is False


def test_chat_retries_when_block_fails_to_parse():
    spec = _toylang_spec()
    client = FakeClient([
        # Bad first reply
        'try this:\n```toylang\nthis ::: not valid\n```',
        # Good second reply after feedback
        'corrected:\n```toylang\nprint("ok");\n```',
    ])
    out = chat(spec, TOYLANG_DIR, "do a thing", [], client, max_retries=1)
    assert out["retried"] is True
    assert len(client.calls) == 2
    # Second call's history must contain feedback about the previous failure
    feedback_msg = client.calls[1]["history"][-1]
    assert feedback_msg["role"] == "user"
    assert "didn't parse" in feedback_msg["content"] or "previous response" in feedback_msg["content"]
    # Final blocks should be ok
    assert all(b["ok"] for b in out["blocks"])


def test_chat_with_kata_attaches_addendum():
    spec = _toylang_spec()
    kata = {"id": "k1", "title": "Reverse a list", "difficulty": "easy",
            "problem": "reverse it", "function_name": "rev"}
    client = FakeClient(["Hint: think about indexing from the end."])
    chat(spec, TOYLANG_DIR, "I'm stuck", [], client, kata=kata,
         current_code="func rev(lst) { }", mode="hint", max_retries=0)
    sys = client.calls[0]["system"]
    assert "Reverse a list" in sys
    assert "rev" in sys
    assert "HINT" in sys


def test_chat_history_round_trips_to_client():
    """The user's history is forwarded; the new message is appended."""
    spec = _toylang_spec()
    client = FakeClient(["ok"])
    history = [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "earlier reply"},
    ]
    chat(spec, TOYLANG_DIR, "now", history, client, max_retries=0)
    sent = client.calls[0]["history"]
    assert len(sent) == 3
    assert sent[0] == history[0]
    assert sent[1] == history[1]
    assert sent[-1] == {"role": "user", "content": "now"}
