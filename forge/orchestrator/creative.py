"""Stage D (Phase 1.5) + variance-improvement: the multi-section
creative-content LLM call.

The structural fix in Phase 1.5 templates parser/codegen/runtime/stdlib
from a hand-written reference and renders README/LANGUAGE.md from the
spec deterministically. That eliminates 9 LLM calls per c_like
generation. But it also flattens personality — the templated README's
"At a glance" section is the same shape for every c_like sibling.

# Phase 1.5 Stage D (CREATIVE_PROMPT_VERSION=1)

Added ONE small LLM call per spec, tagged `gen-creative`, that produced
a 2-3 sentence prose intro for the README.

# Variance improvement (CREATIVE_PROMPT_VERSION=2)

After the Phase 3 follow-up validation surfaced that one paragraph of
voice across an otherwise-templated README left languages feeling
"mundane and copies," the call was expanded to produce six voiced
fields instead of one:

  readme_intro       - same headline paragraph as before (still required)
  design_philosophy  - why the language has the features it has
  what_its_good_at   - 2-4 specific strengths
  what_its_bad_at    - 1-3 honest limitations (the most distinctive)
  example_commentary - persona's annotation on the hello-world example
  common_mistake     - one warning for new users

Same LLM call (still ~$0.005 per language), same caching, same
fallback discipline. Just a richer schema.

`readme_intro` stays required; the other five are optional. If the
LLM produces 5/6 cleanly, we keep what we got. If it produces 0/6 or
errors out, we return {} and generation proceeds with no creative
content (preserving the existing fallback behavior).

# CACHE COMPATIBILITY

Bumping CREATIVE_PROMPT_VERSION from 1 to 2 invalidates the old
single-section cache entries. Old entries would now be served against
a renderer that expects six fields, so we let them expire. Same
hygiene as the resolver cache bump in Phase 1.5 P1.

# Public API

    creative_content(spec, *, client, use_cache=True, cache_dir=None)
        -> dict with at minimum {"readme_intro": str} on success,
           {} on any failure or full LLM error.
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
# would alter outputs for the same input spec.
#   v1 -> v2: variance-improvement; prompt grew from 1 field to 6.
#   v2 -> v3: structural-variance-channel Seam 6; added per-family
#             surface-characteristics section so example_commentary
#             references the family's actual syntax (ml_like uses
#             pattern matching + `;;`, not c_like braces + `;`).
#   v3 -> v4: logic-family experiment Stage F; added logic_like to the
#             per-family surface-characteristics section so
#             example_commentary correctly references facts / rules /
#             queries + the `:-` / `is/2` / `=/2` distinction, instead
#             of attempting to describe assignment or loops (which
#             logic_like doesn't have).
CREATIVE_PROMPT_VERSION = 4

_DEFAULT_CACHE_DIR = (
    Path(__file__).resolve().parents[2] / ".forge_cache" / "creative"
)

# Same lang_name-insensitive strip list as the resolver. The creative
# call's output depends on options + customization, not on the
# language's name.
_CACHE_KEY_IGNORE_FIELDS = ("lang_name", "file_extension", "lineage")


# Word count targets per field. Used for the loose validation pass —
# if a field is wildly outside its target (more than ±50%), we trim
# or drop it. The LLM following these exactly is nice-to-have; the
# floor is "it didn't produce something pathologically wrong."
_FIELD_TARGETS: dict[str, tuple[int, int]] = {
    "readme_intro":       (80, 180),
    "design_philosophy":  (60, 120),
    "what_its_good_at":   (40,  80),
    "what_its_bad_at":    (40,  80),
    "example_commentary": (50, 100),
    "common_mistake":     (40,  80),
}

# All field names produced by the variance-improvement prompt. Order
# matters for stable JSON serialization but not semantically.
_CREATIVE_FIELDS = tuple(_FIELD_TARGETS.keys())

# JSON schema fed to call_json. `readme_intro` is required so we
# never silently produce a creative block missing the headline.
# The other five are optional — partial output is better than no
# output. Extra fields the LLM might invent are stripped by the
# explicit additionalProperties=False rule.
_CREATIVE_SCHEMA = {
    "type": "object",
    "required": ["readme_intro"],
    "properties": {
        name: {"type": "string"} for name in _CREATIVE_FIELDS
    },
    "additionalProperties": False,
}


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


def _validate_field_word_count(field: str, content: str) -> Optional[str]:
    """Return the field content if it's roughly within its word-count
    target, or a trimmed version, or None to drop it entirely.

    Loose tolerance: ±50% of the target range. If a field comes back
    massively over (e.g. an LLM ignored '40-80 words' and wrote 500),
    we trim to roughly 2× the upper bound. If massively under (less
    than half the lower bound), we drop it — too short usually means
    the LLM gave up on that field and a 5-word sentence reads worse
    than a missing section.
    """
    if not isinstance(content, str):
        return None
    content = content.strip()
    if not content:
        return None
    target_lo, target_hi = _FIELD_TARGETS.get(field, (0, 1000))
    words = content.split()
    n = len(words)
    # Way too short → drop.
    if n < max(5, target_lo // 2):
        return None
    # Way too long → trim to 2x the upper bound. We pick the cut at
    # the last sentence boundary before the cap so the output ends
    # cleanly.
    hard_cap = target_hi * 2
    if n > hard_cap:
        trimmed = " ".join(words[:hard_cap])
        # Try to end on a period if there's one in the last 30 words.
        last_period = trimmed.rfind(".")
        if last_period > 0 and len(trimmed) - last_period < 200:
            trimmed = trimmed[: last_period + 1]
        return trimmed
    return content


def creative_content(spec: dict, *, client: LLMClient,
                     use_cache: bool = True,
                     cache_dir: Optional[Path] = None) -> dict:
    """Return creative content for a spec — up to six voiced fields.

    Returns a dict containing at least `readme_intro` (the required
    field) plus any of the other five fields the LLM produced cleanly.
    Returns `{}` on any failure — the templated renderers must
    tolerate missing creative content gracefully.

    Returned keys (when present):
      - readme_intro:       headline paragraph (80-180 words)
      - design_philosophy:  why this language has its feature set (60-120)
      - what_its_good_at:   2-4 specific strengths (40-80)
      - what_its_bad_at:    1-3 honest limitations (40-80)
      - example_commentary: persona's commentary on hello-world (50-100)
      - common_mistake:     warning for new users (40-80)
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

    raw: dict = {}
    try:
        raw = client.call_json(
            prompt, _CREATIVE_SCHEMA, tag="gen-creative"
        ) or {}
    except Exception:
        # Creative content is best-effort. A failure here MUST NOT
        # break generation — fall back to empty content.
        return {}

    if not isinstance(raw, dict):
        return {}

    # Validate + trim each field individually. If readme_intro fails
    # validation, we have to drop the whole creative block (it's the
    # required headline). The other five drop individually.
    result: dict = {}
    for field in _CREATIVE_FIELDS:
        if field not in raw:
            continue
        validated = _validate_field_word_count(field, raw[field])
        if validated is not None:
            result[field] = validated

    if "readme_intro" not in result:
        # Headline missing → don't ship partial output without it.
        # The renderer's fallback path handles a fully-empty creative
        # block cleanly; trying to render the other five without an
        # intro reads worse than rendering none.
        return {}

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
