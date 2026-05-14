"""Stage 2: Design Resolver.

LLM call. Takes the base spec produced by the spec builder and:
  - Fills in any auto/null fields the spec_builder couldn't decide.
  - Adds `design_notes` explaining each non-trivial choice (especially for
    incoherent combos like static + python_like).
  - Returns a structured spec validated against the schema.

The LLM is constrained via tool-use (`call_json`) to produce a JSON object
matching the language_spec.schema.json. On schema validation failure the
client retries once with the schema error appended (handled in llm_client).

Phase 0.3 (production roadmap): resolver results are cached on disk by
content hash. Re-running a generation with identical options reads from
cache and skips the LLM call entirely. This makes resumed/retry batch
runs cheap and makes interactive iteration fast on second invocations.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from .llm_client import LLMClient
from .personas import persona_block
from .spec_builder import load_schema, validate_spec


_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "resolver.md"

# ---------------------------------------------------------------------------
# Cache version keys
# ---------------------------------------------------------------------------
#
# BUMP these constants whenever the resolver prompt template, the JSON
# schema it must produce, or the resolver's logic itself changes in a
# way that would alter the resolved spec for the same input. Without
# this bump, cache hits will silently return outputs generated under the
# old prompt — which during Phase 1 batch debugging will look like
# "everything's fine" while actually corrupting hundreds of catalog
# entries with stale resolutions.
#
# Why two constants instead of one? They change on different cadences:
#   - PROMPT_VERSION bumps when prompts/resolver.md or any persona block
#     wording changes.
#   - SCHEMA_VERSION bumps when language_spec.schema.json adds/removes
#     fields or tightens enums.
# Either bump invalidates the cache. Both feed the cache key.
#
# When you bump: leave the old cache dir on disk; old entries will simply
# stop being matched. Run `clear_resolver_cache()` to free the space.
#
# Bumped to 2 in Phase 1.5 P1 when _cache_key started stripping
# lang_name / file_extension / lineage. Without the bump, old cache
# entries (whose key included those fields) would never be matched
# again anyway, but they'd also never be re-used cross-name even
# after the new logic activated. Bumping forces a fresh population
# of the cache under the new key shape so the savings show up
# immediately on the first batch run.
RESOLVER_PROMPT_VERSION = 2
# Schema version history:
#   v1: original
#   v1 -> v2: structural-variance-channel Stage F tightened parent
#     descriptions for print_form / statement_terminator / block_style /
#     comment_syntax / loop_forms / error_handling.
#   v2 -> v3: seam8-fix; descriptions added to comment_syntax sub-
#     properties (line, block_open, block_close, nestable) and to
#     options.loop_forms (the input-axis sibling of top-level
#     loop_forms). The Stage F batch revealed the resolver was still
#     rewriting comment_syntax.block_open from '(*' to '"""' for
#     ml_like specs, and adding 'while' to options.loop_forms, because
#     it weights sub-property descriptions over parent ones. v3 adds
#     the missing sub-property descriptions with family-aware values.
RESOLVER_SCHEMA_VERSION = 3


# Workspace-relative cache dir. Each cached spec is one JSON file keyed
# by sha256 of the deterministic-dump of (base_spec + prompt_version +
# schema_version).
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / ".forge_cache" / "specs"


# Fields stripped from base_spec before hashing for the cache key. These
# are bookkeeping / pass-through fields that don't affect the resolved
# spec's content — the resolver prompt explicitly says "Do NOT change
# lang_name or file_extension" — so caching by them would force
# 50 cache misses on a 50-slot batch where the slots share options.
# Phase 1.5 P1 (resolver cache key fix). See PIPELINE_DIAGNOSIS.md §3.2
# / API_COST_AUDIT.md §W1.
_CACHE_KEY_IGNORE_FIELDS = ("lang_name", "file_extension", "lineage")


def _cache_key(base_spec: dict) -> str:
    """Build a deterministic content hash of everything that affects the
    resolver's output.

    Strips fields the resolver doesn't actually use (lang_name,
    file_extension, lineage) so two slots that differ only in their
    label hit the same cache entry. Then hashes the remaining spec
    plus the version constants so any change to inputs OR resolver
    logic busts the cache, while pure-rename slots and reorderings
    of unrelated fields don't.

    Format: `sha256(stripped_spec_json + "|" + prompt_version + "|" +
    schema_version)`. The `|` separators prevent ambiguity (e.g. a
    base_spec ending in "1" and prompt_version "10" hashing the same
    as a base_spec ending in "11" and prompt_version "0")."""
    stripped = {k: v for k, v in base_spec.items()
                if k not in _CACHE_KEY_IGNORE_FIELDS}
    blob = (
        json.dumps(stripped, sort_keys=True, default=str)
        + "|prompt=" + str(RESOLVER_PROMPT_VERSION)
        + "|schema=" + str(RESOLVER_SCHEMA_VERSION)
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _cache_path(key: str, cache_dir: Path) -> Path:
    return cache_dir / f"{key}.json"


def resolve(base_spec: dict, *, client: LLMClient,
            use_cache: bool = True,
            cache_dir: Optional[Path] = None) -> dict:
    """Resolve a base spec through the LLM into a fully-realized spec.

    Phase 0.3 caching:
      - On `use_cache=True` (default), the result is cached on disk by
        sha256 of base_spec. Re-running with the same inputs returns the
        cached result without an LLM round-trip.
      - Pass `use_cache=False` for forced regeneration (the `--no-cache`
        flag in batch tooling).
      - Pass an explicit `cache_dir` to override the default location
        (mainly useful for tests so they don't pollute the workspace).
    """
    cache_dir = Path(cache_dir) if cache_dir is not None else _DEFAULT_CACHE_DIR
    key = _cache_key(base_spec)
    cache_file = _cache_path(key, cache_dir)

    if use_cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            # Re-validate on read so stale cached entries (e.g. produced by
            # an older schema version) get regenerated rather than silently
            # poisoning downstream generation.
            validate_spec(cached)
            # Telemetry: if the client has a recorder attached, record a
            # zero-token, zero-duration "cache hit" so summaries can show
            # what fraction of the resolver work was avoided.
            _record_cache_hit(client, key)
            return cached
        except Exception:
            # Corrupt or stale cache entry: fall through and regenerate.
            try:
                cache_file.unlink(missing_ok=True)
            except Exception:
                pass

    schema = load_schema()
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("{{BASE_SPEC}}", json.dumps(base_spec, indent=2))

    cust = base_spec.get("customization") or {}

    # Designer persona block (S10): prepended so it frames the whole task.
    pblock = persona_block(cust.get("persona"))
    if pblock:
        prompt = pblock + "\n\n---\n\n" + prompt

    # Hostile constraints (S10): surfaced as a high-priority ask.
    hc = cust.get("hostile_constraints")
    if hc:
        prompt += (
            "\n\n## User constraints (free-form, HIGH PRIORITY)\n\n"
            f"{hc}\n\n"
            "Honor every constraint where physically possible. For any "
            "constraint you cannot honor, add a `design_notes` entry "
            "explaining why and what you did instead."
        )

    resolved = client.call_json(prompt, schema, tag="resolver")
    # Customization fields are user-side: re-attach if the LLM stripped them.
    if cust and "customization" not in resolved:
        resolved["customization"] = cust
    elif cust:
        # Merge: LLM's customization wins on overlap, but our passthrough
        # fields (persona/era/etc.) must persist.
        merged = dict(cust)
        merged.update(resolved.get("customization") or {})
        resolved["customization"] = merged
    validate_spec(resolved)

    # Cache the success. Atomic write (.tmp + os.replace) so concurrent
    # batch runs hashing the same spec don't see a torn JSON file.
    if use_cache:
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(resolved, indent=2), encoding="utf-8")
            os.replace(tmp, cache_file)
        except Exception:
            # Cache write failures must never break generation.
            pass

    return resolved


def _record_cache_hit(client, key: str) -> None:
    """Record a zero-cost LLM call into the recorder marked as a cache
    hit, so summaries can answer 'how much did we spend vs. how much
    did we save?' Free no-op when no recorder is attached."""
    rec = getattr(client, "telemetry", None)
    if rec is None:
        return
    try:
        from .telemetry import LLMCallRecord
        rec.record_llm_call(LLMCallRecord(
            tag="resolver-cache-hit",
            model=getattr(client, "model", "unknown"),
            input_tokens=0, output_tokens=0,
            duration_seconds=0.0, attempts=1, success=True,
            error=None,
        ))
    except Exception:
        pass


def clear_resolver_cache(cache_dir: Optional[Path] = None) -> int:
    """Remove all cached resolver entries. Returns count of files deleted.
    Useful as a CLI knob and for test cleanup."""
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
