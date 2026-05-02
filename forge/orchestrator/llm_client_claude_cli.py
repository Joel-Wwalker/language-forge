"""Alternative LLM client that uses the `claude` CLI (Claude Code).

Why: the `claude` binary authenticates against the user's Claude.ai/Max
subscription, NOT against an API key. So users with a Max plan can run Forge
without paying per-token API fees, the price is slower per-call latency and
weaker JSON guarantees.

API parity with `LLMClient` in llm_client.py:
  - call_code(prompt) -> str
  - call_json(prompt, schema) -> dict

Differences:
  - call_json uses prompt-engineering + extraction instead of forced tool use,
    so it's slightly less reliable. We re-validate against the JSON schema and
    retry on failure (same retry pattern as the API client).
  - Each call spawns a subprocess; this is OK for our usage (~10 calls per
    language) but not appropriate for tight loops.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from jsonschema import Draft7Validator

from .llm_client import (  # reuse helpers + retry logic
    DEFAULT_MODEL,
    DEFAULT_MAX_TOKENS,
    extract_first_fenced_block,
    _log_call,
    _DEFAULT_SYSTEM,
)


# Best-effort find of the `claude` binary. On Windows it's typically a `.cmd`
# shim under %APPDATA%\npm\claude.cmd.
def _find_claude_cli() -> str:
    explicit = os.environ.get("FORGE_CLAUDE_CLI")
    if explicit and Path(explicit).exists():
        return explicit
    for name in ("claude", "claude.cmd", "claude.exe"):
        found = shutil.which(name)
        if found:
            return found
    raise RuntimeError(
        "Could not find the `claude` CLI. Install Claude Code "
        "(npm i -g @anthropic-ai/claude-code) or set FORGE_CLAUDE_CLI to its path."
    )


_JSON_OBJ_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)


def _extract_json_object(text: str) -> Optional[dict]:
    """Pull the first valid JSON object out of an LLM response.

    Tries fenced blocks first, then loose object-shaped substrings. Returns
    None if nothing parses.
    """
    fenced = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    for chunk in fenced:
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            continue
    # Greedy: try the largest brace-balanced substring.
    best = None
    for m in _JSON_OBJ_RE.finditer(text):
        try:
            data = json.loads(m.group(0))
            if best is None or len(m.group(0)) > len(json.dumps(best)):
                best = data
        except json.JSONDecodeError:
            continue
    return best


class ClaudeCLIClient:
    """Drop-in replacement for LLMClient that shells out to `claude -p`."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        log_dir: Optional[str | os.PathLike] = None,
        cli_path: Optional[str] = None,
        timeout_seconds: int = 240,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.log_dir = Path(log_dir) if log_dir else None
        self.cli_path = cli_path or _find_claude_cli()
        self.timeout = timeout_seconds

    # ------------------------------------------------------------------
    # Internal subprocess invocation
    # ------------------------------------------------------------------

    def _invoke(self, prompt: str, *, system: Optional[str] = None) -> str:
        # `claude -p <prompt>` runs a one-shot, non-interactive completion.
        # We pass the prompt via stdin to avoid shell-escaping issues with
        # large prompts.
        full_prompt = (system + "\n\n" if system else "") + prompt
        cmd = [self.cli_path, "-p", "--model", self.model]
        try:
            proc = subprocess.run(
                cmd,
                input=full_prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace",
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude CLI timed out after {self.timeout}s: {e}")
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}\n--- stderr ---\n{proc.stderr}"
            )
        return proc.stdout

    # ------------------------------------------------------------------
    # Public API (parity with LLMClient)
    # ------------------------------------------------------------------

    def call_code(self, prompt: str, *, tag: str = "code", system: Optional[str] = None,
                  max_retries: int = 2) -> str:
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                text = self._invoke(prompt, system=system or _DEFAULT_SYSTEM)
                _log_call(self.log_dir, tag, prompt, text)
                return extract_first_fenced_block(text)
            except RuntimeError as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"call_code failed after {max_retries + 1} attempts: {last_err}")

    def call_chat(self, system: str, history: list, *,
                  tag: str = "chat", max_retries: int = 2) -> str:
        """Multi-turn chat. Concatenates history into a single prompt the
        CLI can swallow (the `claude -p` mode is one-shot per call). Each
        turn's role is annotated for the model."""
        import json as _json
        flat = []
        for msg in history:
            role = msg.get("role", "user").upper()
            flat.append(f"\n[{role}]\n{msg.get('content', '')}\n")
        prompt = "".join(flat).strip()
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                text = self._invoke(prompt, system=system)
                _log_call(self.log_dir, tag, system + "\n---\n" + _json.dumps(history), text)
                return text
            except RuntimeError as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"call_chat failed after {max_retries + 1} attempts: {last_err}")

    def call_json(self, prompt: str, schema: dict, *, tag: str = "json",
                  system: Optional[str] = None, max_retries: int = 2) -> dict:
        validator = Draft7Validator(schema)
        sys_msg = (
            (system or _DEFAULT_SYSTEM)
            + "\n\nIMPORTANT: respond with a SINGLE valid JSON object inside a "
              "```json fenced code block. No prose before or after. The object "
              "must strictly match the schema described below."
        )
        retry_prompt = prompt
        last_err: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                text = self._invoke(retry_prompt, system=sys_msg)
                _log_call(self.log_dir, tag, retry_prompt, text)
                data = _extract_json_object(text)
                if data is None:
                    raise ValueError("no JSON object found in response")
                errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
                if errors:
                    err_msg = "\n".join(
                        f"- {'/'.join(map(str, e.path))}: {e.message}" for e in errors
                    )
                    raise ValueError(f"schema validation failed:\n{err_msg}")
                return data
            except (RuntimeError, ValueError) as e:
                last_err = e
                if isinstance(e, ValueError) and attempt < max_retries:
                    retry_prompt = (
                        prompt
                        + "\n\nYour previous response failed validation:\n"
                        + str(e)
                        + "\nFix the issues and respond with corrected JSON only."
                    )
                time.sleep(2 ** attempt)
        raise RuntimeError(f"call_json failed after {max_retries + 1} attempts: {last_err}")
