"""Structural variance: themed canonical-test bodies + themed examples.

# Why this exists

The variance-improvement work (gen-creative expansion to 6 fields)
closed the prose gap but the variance-validation read came back with a
"prose says different, structure says same" verdict (Call B). Two
c_like languages with different personas/themes were still shipping
the same eight canonical tests with the same content — only the
keyword names differed.

This module adds a third LLM call to the per-language pipeline that
produces:

  canonical_test_bodies  - themed replacement for each of the 8 canonical
                           tests. Same name, same expected output, but the
                           body reads in the persona's voice. Pirate
                           arithmetic divides plunder; Stroustrup-1980s
                           closures is a CAD callback; etc.
  examples               - 0-5 longer themed example programs written to
                           examples/<name>.<ext>. Not smoke-tested; just
                           parse-checked. Show off "this language doing
                           what it's designed to do."

# Discipline

Same fallback shape as creative.py: any failure (LLM error, schema
mismatch, every body fails validation) returns `{}`. Generators
gracefully degrade to the existing reference templates.

# Cache

Content-hash key, strips lang_name + file_extension + lineage (same
list as creative.py). Folds IDIOMS_PROMPT_VERSION. Bump the version
constant when the prompt changes in a way that would alter outputs
for the same input spec.

# Validation

This module does NOT validate canonical_test_bodies against the
language's compiler — that requires lang_dir, which only exists
after parser/codegen/runtime have been generated. The generator
hook (generator.py) runs per-body validation in the tests step and
drops any body that doesn't produce expected output.

Examples get a parse-check in the generator hook (they don't need
to produce expected output, only parse cleanly).

# Public API

    idiomatic_content(spec, *, client, use_cache=True, cache_dir=None)
        -> dict with optional 'canonical_test_bodies' and 'examples'
           keys on success, {} on any failure.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from .llm_client import LLMClient


_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "idioms.md"

# Bump this when the idioms prompt template changes in a way that
# would alter outputs for the same input spec.
IDIOMS_PROMPT_VERSION = 1

_DEFAULT_CACHE_DIR = (
    Path(__file__).resolve().parents[2] / ".forge_cache" / "idioms"
)

# Same strip list as the creative + resolver caches. The idiom call's
# output should depend on options + customization, not on the
# language's surface name or file extension.
_CACHE_KEY_IGNORE_FIELDS = ("lang_name", "file_extension", "lineage")

# The eight canonical test names — pulled from generator.py's
# _CANONICAL_TESTS. Kept here as a duplicated source of truth so the
# JSON schema can enforce them. If generator.py changes the canon,
# both lists need to change.
CANONICAL_TEST_NAMES = (
    "hello_world",
    "arithmetic",
    "variables",
    "conditionals",
    "loops",
    "functions",
    "closures",
    "strings",
)

# JSON schema fed to call_json. canonical_test_bodies is required (the
# call exists to populate them); examples is optional.
_IDIOMS_SCHEMA = {
    "type": "object",
    "required": ["canonical_test_bodies"],
    "properties": {
        "canonical_test_bodies": {
            "type": "object",
            "properties": {
                name: {"type": "string"} for name in CANONICAL_TEST_NAMES
            },
            "additionalProperties": False,
        },
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "description", "body"],
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "body": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def _cache_key(spec: dict) -> str:
    stripped = {k: v for k, v in spec.items()
                if k not in _CACHE_KEY_IGNORE_FIELDS}
    blob = (
        json.dumps(stripped, sort_keys=True, default=str)
        + "|prompt=" + str(IDIOMS_PROMPT_VERSION)
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _cache_path(key: str, cache_dir: Path) -> Path:
    return cache_dir / f"{key}.json"


def _validate_example_name(name: str) -> bool:
    """Example filenames must be snake_case identifiers. The generator
    hook writes them to examples/<name>.<ext>; we reject anything that
    couldn't be a Python identifier (no path traversal, no special
    characters) so the LLM can't produce examples/../escape.txt."""
    if not isinstance(name, str) or not name:
        return False
    if len(name) > 60:
        return False
    return name.isidentifier() and name.islower()


def _sanitize_examples(raw_examples) -> list[dict]:
    """Keep only well-formed example entries. Drop the rest silently."""
    if not isinstance(raw_examples, list):
        return []
    out: list[dict] = []
    seen_names: set[str] = set()
    for entry in raw_examples:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        desc = entry.get("description")
        body = entry.get("body")
        if not _validate_example_name(name):
            continue
        if name in seen_names:
            continue
        if not isinstance(desc, str) or not desc.strip():
            continue
        if not isinstance(body, str) or len(body.strip()) < 5:
            continue
        seen_names.add(name)
        out.append({
            "name": name,
            "description": desc.strip(),
            "body": body.strip() + ("\n" if not body.endswith("\n") else ""),
        })
        # Cap at 6 examples — the LLM occasionally returns a dozen
        # and the README's ## Examples section starts feeling like
        # filler past 5 or 6.
        if len(out) >= 6:
            break
    return out


def _sanitize_test_bodies(raw_bodies) -> dict[str, str]:
    """Keep only well-formed canonical test bodies. Drop the rest."""
    if not isinstance(raw_bodies, dict):
        return {}
    out: dict[str, str] = {}
    for name in CANONICAL_TEST_NAMES:
        body = raw_bodies.get(name)
        if not isinstance(body, str):
            continue
        body = body.strip()
        if len(body) < 5:
            # Pathologically short — almost certainly garbage. Drop.
            continue
        if len(body) > 4000:
            # Pathologically long — drop. Real test bodies are 4-15
            # lines; >4000 chars means the LLM went off the rails.
            continue
        out[name] = body + ("\n" if not body.endswith("\n") else "")
    return out


def idiomatic_content(spec: dict, *, client: LLMClient,
                       use_cache: bool = True,
                       cache_dir: Optional[Path] = None) -> dict:
    """Return idiomatic content for a spec.

    Returns a dict containing at least one of:
      - canonical_test_bodies: dict[name -> program string]
      - examples: list[dict with name/description/body]

    Returns `{}` on any failure — generators must tolerate missing
    idiomatic content gracefully (fall back to reference templates).

    Note: this function does NOT validate test bodies against the
    language's compiler. That happens in the generator hook, which
    has access to lang_dir. Here we only do shape + sanity checks.
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
            prompt, _IDIOMS_SCHEMA, tag="gen-idioms"
        ) or {}
    except Exception:
        # Idiomatic content is best-effort. A failure here MUST NOT
        # break generation — fall back to empty content.
        return {}

    if not isinstance(raw, dict):
        return {}

    result: dict = {}
    bodies = _sanitize_test_bodies(raw.get("canonical_test_bodies"))
    if bodies:
        result["canonical_test_bodies"] = bodies
    examples = _sanitize_examples(raw.get("examples"))
    if examples:
        result["examples"] = examples

    if not result:
        # Both fields empty after sanitization — nothing usable.
        return {}

    if use_cache:
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
    show what fraction of idioms work was avoided."""
    rec = getattr(client, "telemetry", None)
    if rec is None:
        return
    try:
        from .telemetry import LLMCallRecord
        rec.record_llm_call(LLMCallRecord(
            tag="gen-idioms-cache-hit",
            model=getattr(client, "model", "unknown"),
            input_tokens=0, output_tokens=0,
            duration_seconds=0.0, attempts=1, success=True,
            error=None,
        ))
    except Exception:
        pass


def clear_idioms_cache(cache_dir: Optional[Path] = None) -> int:
    """Remove all cached idioms entries. Returns count of files
    deleted. Used by tests + CLI cleanup."""
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
