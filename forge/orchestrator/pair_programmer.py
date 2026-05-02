"""AI pair programmer: a chat-style helper that knows the user's language.

Builds a fresh system prompt from the language spec each session. Every
code block in the assistant's reply gets parsed by the actual compiler
before it leaves the server: parse failures either trigger a silent
retry or a "may not parse cleanly" warning so users aren't misled.

This module exposes:
  - `build_system_prompt(spec)` for the chat session's fixed framing
  - `chat(spec, lang_dir, history, user_message, client, ...)` which
    sends the message, gets a reply, validates code blocks, and returns
    a structured result the GUI can render.

Kata integration: when `kata` and `mode` ("hint" | "solution") are
supplied, the system prompt is augmented with the problem statement and
the user's current solution, and the assistant is told to give nudges
rather than a full answer in hint mode.
"""
from __future__ import annotations

import re
import subprocess
import sys
import os
import tempfile
import json
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def build_system_prompt(spec: dict) -> str:
    """Compact (target ~3k tokens) system prompt from the language spec.

    Cached per-language by the GUI so chat doesn't re-pay this cost every
    message.
    """
    parts = []
    parts.append(f"You are an expert pair programmer for `{spec['lang_name']}`, "
                 "a programming language. Help the user write and debug code in "
                 "this language. Use ONLY this language's syntax in code blocks.")

    parts.append("\n## Language at a glance\n")
    opts = spec.get("options", {})
    parts.append(f"- Syntax family: {opts.get('syntax', '?')}")
    parts.append(f"- Typing: {opts.get('typing', '?')}")
    parts.append(f"- Memory: {opts.get('memory', '?')}")
    parts.append(f"- File extension: `{spec['file_extension']}`")

    cs = spec.get("comment_syntax") or {}
    if cs.get("line"):
        parts.append(f"- Line comments: `{cs['line']}`")
    if cs.get("block_open") and cs.get("block_close"):
        parts.append(f"- Block comments: `{cs['block_open']} ... {cs['block_close']}`")
    parts.append(f"- Statement terminator: `{spec.get('statement_terminator', ';')}`")
    parts.append(f"- Block style: {spec.get('block_style', 'braces')}")

    parts.append("\n## Keywords\n")
    parts.append(", ".join(f"`{k}`" for k in spec.get("keywords", [])))

    parts.append("\n## Operators\n")
    ops = spec.get("operators") or {}
    for cat in ("arithmetic", "comparison", "logical", "assignment"):
        parts.append(f"- {cat}: {' '.join(ops.get(cat, []))}")

    fd = spec.get("function_definition", {})
    if fd.get("syntax_example"):
        parts.append("\n## Function definition\n")
        parts.append(f"```{spec['lang_name']}\n{fd['syntax_example']}\n```")

    vd = spec.get("variable_declaration", {})
    if vd.get("syntax_example"):
        parts.append("\n## Variable declaration\n")
        parts.append(f"```{spec['lang_name']}\n{vd['syntax_example']}\n```")

    # Phrasebook trumps everything: if natural-language templates are set,
    # those are the only valid statement forms.
    cust = spec.get("customization") or {}
    nl = cust.get("natural_language")
    if nl:
        parts.append("\n## Natural-language phrasebook (use these EXACTLY)\n")
        for tpl_name, tpl in nl.items():
            parts.append(f"- {tpl_name}: `{tpl}`")
        parts.append("\nProgrammatic constructs OUTSIDE this list use the language's "
                     "default syntax. Operator words and boolean/null words listed "
                     "above ARE the valid spellings.")

    stdlib = (spec.get("stdlib") or {}).get("functions") or []
    if stdlib:
        parts.append("\n## Stdlib (call without import)\n")
        for fn in stdlib[:24]:    # cap to keep tokens in budget
            sig = fn.get("signature", fn["name"] + "(...)")
            parts.append(f"- `{sig}`. {fn.get('description', '')}")

    notes = spec.get("design_notes") or []
    if notes:
        parts.append("\n## Design notes\n")
        for n in notes[:6]:
            parts.append(f"- {n}")

    parts.append(
        "\n## How to respond\n"
        f"- When you write code, fence it as ```{spec['lang_name']}\\n... ```. "
        "The GUI runs every fenced block through this language's parser before "
        "showing it to the user, so do not invent syntax.\n"
        "- Be concise. One small example is worth more than three paragraphs.\n"
        "- Use the language's exact operator spellings, comment style, and statement "
        "terminator. Do not slip into Python or generic pseudocode."
    )
    return "\n".join(parts)


def build_kata_addendum(kata: dict, current_code: str, mode: str) -> str:
    """When the user is solving a kata, prepend their current state."""
    parts = ["\n## Active kata\n",
             f"**{kata.get('title', kata['id'])}** ({kata.get('difficulty', '?')})\n",
             kata.get("problem", ""),
             "",
             f"They must define a function called `{kata['function_name']}`."]
    if current_code.strip():
        parts.append("\n## Their current code\n")
        parts.append("```\n" + current_code + "\n```")
    if mode == "hint":
        parts.append("\n## Mode: HINT\n")
        parts.append("Give a short nudge (one paragraph max). Point them at the next idea, "
                     "do NOT write the full solution. If they show a bug, narrate it without "
                     "fixing it. Real learning happens in hint mode.")
    else:
        parts.append("\n## Mode: SOLUTION\n")
        parts.append("Provide a complete, runnable solution with brief commentary.")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Code-block extraction + parser validation
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```([\w+\-.]*)\n(.*?)```", re.DOTALL)


def extract_code_blocks(text: str) -> list[tuple[str, str]]:
    """Return [(label, body), ...] for every fenced block in `text`."""
    return [(m.group(1), m.group(2)) for m in _FENCE_RE.finditer(text)]


def validate_code_block(lang_dir: Path, source: str, timeout: float = 6.0) -> dict:
    """Compile-only sanity check. Returns {ok, error}."""
    lang_dir = lang_dir.resolve()
    compile_py = lang_dir / "compile.py"
    if not compile_py.exists():
        return {"ok": False, "error": "compile.py not found"}
    with tempfile.NamedTemporaryFile("w", suffix=".__chat__", delete=False, encoding="utf-8") as f:
        f.write(source)
        path = Path(f.name)
    try:
        env = {**os.environ, "PYTHONPATH": str(lang_dir.parent)}
        proc = subprocess.run(
            [sys.executable, str(compile_py), str(path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(lang_dir), env=env,
        )
        if proc.returncode == 0:
            return {"ok": True}
        # Extract a short error line for UI display.
        last_line = (proc.stderr.strip().splitlines() or [""])[-1]
        return {"ok": False, "error": last_line[:200]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timed out"}
    finally:
        try: path.unlink()
        except OSError: pass
        try: path.with_suffix(path.suffix + ".out.py").unlink()
        except OSError: pass


def annotate_response(text: str, lang_dir: Path) -> tuple[str, list[dict]]:
    """For each code block, attach a parser-validation result.

    Returns (text, blocks) where text is the original assistant text and
    blocks is a list of {label, body, ok, error?} the GUI uses to render
    "may not parse cleanly" badges and Run-this buttons.
    """
    blocks = []
    for label, body in extract_code_blocks(text):
        v = validate_code_block(lang_dir, body)
        blocks.append({"label": label, "body": body, **v})
    return text, blocks


# ---------------------------------------------------------------------------
# Chat orchestration
# ---------------------------------------------------------------------------

def chat(
    spec: dict,
    lang_dir: Path,
    user_message: str,
    history: list[dict],
    client,
    *,
    kata: Optional[dict] = None,
    current_code: Optional[str] = None,
    mode: str = "hint",
    max_retries: int = 1,
) -> dict:
    """Run one round of chat. Validates code blocks, retries once if any
    fail to parse. Returns:

      {
        "text": "<full assistant text>",
        "blocks": [{"label", "body", "ok", "error"}, ...],
        "retried": bool,
      }
    """
    system_prompt = build_system_prompt(spec)
    if kata is not None:
        system_prompt += build_kata_addendum(kata, current_code or "", mode)

    convo: list[dict] = list(history) + [{"role": "user", "content": user_message}]

    text = client.call_chat(system_prompt, convo, tag="pair")
    blocks = []
    for label, body in extract_code_blocks(text):
        blocks.append({"label": label, "body": body, **validate_code_block(lang_dir, body)})

    retried = False
    failed = [b for b in blocks if not b["ok"]]
    if failed and max_retries > 0:
        retried = True
        feedback = (
            "Your previous response had code that didn't parse:\n"
            + "\n".join(f"- {b['error']}" for b in failed)
            + "\nTry again. Keep code blocks valid for this language's parser."
        )
        convo.append({"role": "assistant", "content": text})
        convo.append({"role": "user", "content": feedback})
        text = client.call_chat(system_prompt, convo, tag="pair-retry")
        blocks = []
        for label, body in extract_code_blocks(text):
            blocks.append({"label": label, "body": body, **validate_code_block(lang_dir, body)})

    return {"text": text, "blocks": blocks, "retried": retried}
