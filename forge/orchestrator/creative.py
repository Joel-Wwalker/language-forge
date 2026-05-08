"""Stage D (Phase 1.5): the small creative-content LLM call.

The structural fix in Phase 1.5 templates parser/codegen/runtime/stdlib
from a hand-written reference and renders README/LANGUAGE.md from the
spec deterministically. That eliminates 9 LLM calls per c_like
generation. But it also flattens personality — the templated README's
"At a glance" section is the same shape for every c_like sibling.

This module adds back ONE small LLM call per spec, tagged
`gen-creative`, that produces a 2-3 sentence prose intro for the
README. The output is persona / era / theme flavored. Stays on the
generation hot path because it's small (~200 tokens in, ~200 tokens
out) and cached aggressively.

Caching follows the resolver's lang_name-insensitive pattern (Phase
1.5 P1) so a 50-slot batch where many slots share options pays the
LLM cost once, not 50 times.

Public API:
    creative_content(spec, *, client, use_cache=True, cache_dir=None)
        -> dict with at minimum {"readme_intro": str}
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from .llm_client import LLMClient


_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "creative.md"

# Bump this when the creative prompt template changes in a way that
# would alter outputs for the same input spec. Same discipline as
# RESOLVER_PROMPT_VERSION — without the bump, cache hits silently
# return outputs generated under the old prompt.
CREATIVE_PROMPT_VERSION = 1

_DEFAULT_CACHE_DIR = (
    Path(__file__).resolve().parents[2] / ".forge_cache" / "creative"
)

# Same lang_name-insensitive strip list as the resolver. The creative
# call's output depends on options + customization, not on the
# language's name.
_CACHE_KEY_IGNORE_FIELDS = ("lang_name", "file_extension", "lineage")


def _cache_key(spec: dict) -> str:
    stripped = {k: v for k, v in spec.items()
                if k not in _CACHE_KEY_IGNORE_FIELDS}
    blob = (
        json.dumps(stripped, sort_keys=True, default=str)
        + "|prompt=" + str(CREATIVE_PROMPT_VERSION)
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _cache_path(key: str, cache_dir: Path) -> Path:
    return cache_dir / f"{key}.json"


def creative_content(spec: dict, *, client: LLMClient,
                     use_cache: bool = True,
                     cache_dir: Optional[Path] = None) -> dict:
    """Return creative content for a spec — currently just a
    `readme_intro` field. Cached on disk by content hash so a batch
    of slots sharing options pays the LLM cost once.

    Returns a dict like:
        {"readme_intro": "Two or three sentences of persona-flavored prose."}

    Future fields (extend as needed): `tagline`, `motto`,
    `design_notes_prose`. The dict shape is open; callers should
    `.get()` rather than assume keys.

    On any failure (LLM error, schema problem), falls back to an
    empty dict — the templated renderers must tolerate missing
    creative content gracefully.
    """
    cache_dir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    key = _cache_key(spec)
    cache_file = _cache_path(key, cache_dir)

    if use_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            _record_cache_hit(client)
            return cached
        except Exception:
            try:
                cache_file.unlink(missing_ok=True)
            except Exception:
                pass

    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt.replace("{{SPEC}}", json.dumps(spec, indent=2))

    try:
        # call_code returns the FIRST fenced code block by default;
        # but our prompt explicitly asks for plain text (no fences),
        # so the body is just the text content. The fenced-block
        # extractor returns the whole text when no fence is present.
        text = client.call_code(prompt, tag="gen-creative")
        # Strip whitespace + any accidental fence markers.
        intro = text.strip()
        if intro.startswith("```"):
            # Defensive: if the model wrapped in fences anyway, peel them.
            lines = intro.splitlines()
            intro = "\n".join(
                line for line in lines if not line.startswith("```")
            ).strip()
    except Exception:
        # Creative content is best-effort. A failure here MUST NOT
        # break generation — fall back to empty content.
        return {}

    result = {"readme_intro": intro} if intro else {}

    if use_cache and result:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
            os.replace(tmp, cache_file)
        except Exception:
            pass

    return result


def _record_cache_hit(client) -> None:
    """Record a zero-cost cache-hit telemetry event so summaries
    show what fraction of creative work was avoided."""
    rec = getattr(client, "telemetry", None)
    if rec is None:
        return
    try:
        from .telemetry import LLMCallRecord
        rec.record_llm_call(LLMCallRecord(
            tag="gen-creative-cache-hit",
            model=getattr(client, "model", "unknown"),
            input_tokens=0, output_tokens=0,
            duration_seconds=0.0, attempts=1, success=True,
            error=None,
        ))
    except Exception:
        pass


def clear_creative_cache(cache_dir: Optional[Path] = None) -> int:
    """Remove all cached creative entries. Returns count of files
    deleted. CLI knob + test cleanup."""
    cache_dir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    if not cache_dir.exists():
        return 0
    n = 0
    for p in cache_dir.glob("*.json"):
        try:
            p.unlink()
            n += 1
        except Exception:
            pass
    return n
