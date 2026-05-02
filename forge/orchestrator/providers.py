"""LLM provider factory.

Two providers today:
  - "api": Anthropic API via SDK (requires ANTHROPIC_API_KEY)
  - "claude_cli": `claude` CLI (uses Claude Max / Code subscription)

Default is "api" if ANTHROPIC_API_KEY is set, else "claude_cli" if the binary
is on PATH.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal, Optional, Protocol


Provider = Literal["api", "claude_cli"]


class _LLMLike(Protocol):
    log_dir: Optional[Path]
    def call_code(self, prompt: str, *, tag: str = "code", system: Optional[str] = None,
                  max_retries: int = 2) -> str: ...
    def call_json(self, prompt: str, schema: dict, *, tag: str = "json",
                  system: Optional[str] = None, max_retries: int = 2) -> dict: ...


def detect_default_provider() -> Provider:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    for name in ("claude", "claude.cmd", "claude.exe"):
        if shutil.which(name):
            return "claude_cli"
    return "api"  # will raise a clean error when used


def make_client(
    provider: Optional[Provider] = None,
    *,
    log_dir: Optional[str | os.PathLike] = None,
) -> _LLMLike:
    provider = provider or detect_default_provider()
    if provider == "claude_cli":
        from .llm_client_claude_cli import ClaudeCLIClient
        return ClaudeCLIClient(log_dir=log_dir)
    if provider == "api":
        from .llm_client import LLMClient
        return LLMClient(log_dir=log_dir)
    raise ValueError(f"Unknown provider: {provider!r}")
