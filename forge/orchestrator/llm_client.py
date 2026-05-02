"""Thin wrapper around the Anthropic SDK.

Two helpers:

  call_json(prompt, schema, ...) -> dict
      Force-structured output via tool use. Validates against JSON schema.

  call_code(prompt, ...) -> str
      Plain text completion. Extracts the FIRST fenced code block from the
      response and returns the contents.

Both have built-in retry on API errors and (for call_json) on schema validation
errors. Every call is logged as a (prompt, response) pair to a directory
provided by the caller for debuggability.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import anthropic
from jsonschema import Draft7Validator


DEFAULT_MODEL = "claude-sonnet-4-5"
DEFAULT_MAX_TOKENS = 8000


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _log_call(log_dir: Optional[Path], tag: str, prompt: str, response: str) -> None:
    if not log_dir:
        return
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    safe_tag = re.sub(r"[^A-Za-z0-9_-]", "_", tag)[:40]
    base = log_dir / f"{ts}_{safe_tag}"
    base.with_suffix(".prompt.txt").write_text(prompt, encoding="utf-8")
    base.with_suffix(".response.txt").write_text(response, encoding="utf-8")


# ---------------------------------------------------------------------------
# Code-block extraction
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"```(?:[\w+\-.]+)?\n(.*?)```", re.DOTALL)


def extract_first_fenced_block(text: str) -> str:
    """Pull the first fenced code block out of an LLM response.

    Falls back to the entire string if no fence is found (some models forget
    fences for short snippets).
    """
    m = _FENCE_RE.search(text)
    return m.group(1).rstrip() + "\n" if m else text.rstrip() + "\n"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: Optional[str] = None,
        log_dir: Optional[str | os.PathLike] = None,
    ):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Export it or pass api_key=... to LLMClient."
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.log_dir = Path(log_dir) if log_dir else None

    # --------------------------------------------------------------------
    # call_code: plain text completion → first fenced code block
    # --------------------------------------------------------------------

    def call_code(self, prompt: str, *, tag: str = "code", system: Optional[str] = None,
                  max_retries: int = 2) -> str:
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system or _DEFAULT_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
                _log_call(self.log_dir, tag, prompt, text)
                return extract_first_fenced_block(text)
            except (anthropic.APIError, anthropic.APIConnectionError, anthropic.RateLimitError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"call_code failed after {max_retries + 1} attempts: {last_err}")

    # --------------------------------------------------------------------
    # call_json: tool-use forced structured output
    # --------------------------------------------------------------------

    def call_json(self, prompt: str, schema: dict, *, tag: str = "json",
                  system: Optional[str] = None, max_retries: int = 2) -> dict:
        validator = Draft7Validator(schema)
        tool = {
            "name": "emit_spec",
            "description": "Emit the requested structured spec object.",
            "input_schema": schema,
        }

        last_err: Optional[Exception] = None
        retry_prompt = prompt
        for attempt in range(max_retries + 1):
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=system or _DEFAULT_SYSTEM,
                    tools=[tool],
                    tool_choice={"type": "tool", "name": "emit_spec"},
                    messages=[{"role": "user", "content": retry_prompt}],
                )
                tool_use = next(
                    (b for b in resp.content if getattr(b, "type", None) == "tool_use"),
                    None,
                )
                if tool_use is None:
                    raise ValueError("LLM did not call emit_spec tool")
                data = tool_use.input
                _log_call(self.log_dir, tag, retry_prompt, json.dumps(data, indent=2))
                errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
                if errors:
                    err_msg = "\n".join(f"- {'/'.join(map(str, e.path))}: {e.message}" for e in errors)
                    raise ValueError(f"schema validation failed:\n{err_msg}")
                return data
            except (anthropic.APIError, anthropic.APIConnectionError, anthropic.RateLimitError, ValueError) as e:
                last_err = e
                # On schema validation failure, retry once with the error appended.
                if isinstance(e, ValueError) and attempt < max_retries:
                    retry_prompt = (
                        prompt
                        + "\n\nYour previous response failed validation:\n"
                        + str(e)
                        + "\nFix the issues and try again."
                    )
                time.sleep(2 ** attempt)
        raise RuntimeError(f"call_json failed after {max_retries + 1} attempts: {last_err}")


_DEFAULT_SYSTEM = (
    "You are a meticulous compiler engineer. When asked for code, return ONLY a "
    "single fenced code block: no explanation. When asked for structured data, "
    "use the provided tool and produce JSON that strictly matches the schema."
)


# Chat method bolted on to LLMClient: open-ended multi-turn for the pair
# programmer. Caller passes a full message history; we return assistant text.
def _chat_method(self, system: str, history: list, *,
                 tag: str = "chat", max_retries: int = 2) -> str:
    last_err = None
    for attempt in range(max_retries + 1):
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=history,
            )
            text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
            _log_call(self.log_dir, tag, system + "\n---\n" + json.dumps(history), text)
            return text
        except Exception as e:
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"call_chat failed after {max_retries + 1} attempts: {last_err}")


LLMClient.call_chat = _chat_method
