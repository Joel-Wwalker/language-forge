"""Variance-improvement — multi-section creative content tests.

The variance-improvement expanded `gen-creative` from one `readme_intro`
field to six voiced fields (readme_intro, design_philosophy,
what_its_good_at, what_its_bad_at, example_commentary, common_mistake).
Same one LLM call, same caching, just a richer schema.

This file pins:
  - `creative_content` returns all six fields when the LLM cooperates
  - Returns the available subset when the LLM omits fields
  - Falls back to {} on LLM failure (existing behavior preserved)
  - Word-count validation trims pathologically long fields, drops
    pathologically short ones
  - `_render_templated_readme` inlines all six fields at the right
    positions; omits missing sections gracefully
  - Cache version bump invalidates old single-field entries
  - End-to-end generation with a multi-section creative call still
    produces a passing language (slow)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from forge.orchestrator.creative import (
    creative_content, clear_creative_cache, _cache_key,
    CREATIVE_PROMPT_VERSION, _CREATIVE_FIELDS, _validate_field_word_count,
)
from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.generator import (
    generate_all, _render_templated_readme,
)


WORKSPACE = Path(__file__).resolve().parents[1]


# Six well-formed example fields. Each is sized inside its target
# word-count range so validation passes.
_FULL_SIX_FIELDS = {
    "readme_intro": (
        "Loot is a c_like dialect that traded the word 'function' for "
        "'yarrn' and the word 'variable' for 'loot'. The substitution "
        "is shallow but the affect is real: when you write `yarrn add "
        "(a, b) { plunder a + b; }`, you are not writing C. You are "
        "writing a small dialect that takes the trouble to dress like "
        "a pirate. Loot ships with the same primitives every c_like "
        "sibling has, just relabeled. If that sounds like a costume, "
        "it is. The costume is the point."
    ),
    "design_philosophy": (
        "Loot's authors believed that programmers identify with the "
        "tokens they type. Replace `var` with `loot`, replace `func` "
        "with `yarrn`, and the texture of writing code shifts even "
        "though the underlying semantics don't. The bans we kept are "
        "the boring kind — no inheritance, no exception handling — "
        "because pirates work on the deck above, not in the holds "
        "below. The language is intended to be readable in costume "
        "and skippable out of it."
    ),
    "what_its_good_at": (
        "Loot is good at small scripts where the costume is the point: "
        "expressing a single-file algorithm in pirate vocabulary, "
        "writing data-munging glue with no inheritance to argue about, "
        "and producing code that reads aloud well at a meeting where "
        "you want to make people laugh."
    ),
    "what_its_bad_at": (
        "Loot is bad at long programs: the joke wears thin past 200 "
        "lines, and the renamed keywords stop drawing the eye when "
        "every line uses them. It is also bad at exception-rich "
        "domains, since exception handling is banned. Use a real "
        "c_like for those."
    ),
    "example_commentary": (
        "Notice how the example uses `yarrn add` rather than `func "
        "add`. That single substitution is the heart of Loot: the "
        "rest of the program is c_like by construction (braces, "
        "semicolons, infix arithmetic). The costume only goes one "
        "layer deep, and that is enough to change how the program "
        "feels without changing what it does."
    ),
    "common_mistake": (
        "A common mistake is to import a c_like helper from a "
        "different sibling and expect `func` to work. Loot's parser "
        "rejects `func` outright because the grammar has been rewired "
        "to expect `yarrn`. Translate the keyword or rewrite the "
        "helper."
    ),
}


class _StubMultiSectionClient:
    """Stub LLM client that returns a configurable subset of the six
    creative fields. Tests pass `fields=` to control what gets returned.
    """
    log_dir = None
    model = "stub-multi-section"
    telemetry = None

    def __init__(self, fields: dict | None = None, fail: bool = False):
        self.calls: list[str] = []
        self.fields = fields if fields is not None else dict(_FULL_SIX_FIELDS)
        self.fail = fail

    def call_json(self, prompt, schema, *, tag="json", **kw):
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, tag, time.monotonic() - 0.01,
                        100, 50, 1, True, None)
        self.calls.append(tag)
        if self.fail:
            raise RuntimeError("synthetic LLM failure")
        return dict(self.fields)

    def call_code(self, *a, **kw):
        if self.fail:
            raise RuntimeError("synthetic LLM failure")
        return self.fields.get("readme_intro", "")

    def call_chat(self, *a, **kw):
        return ""


# ---------------------------------------------------------------------------
# 1. All six fields returned when LLM cooperates
# ---------------------------------------------------------------------------

def test_creative_returns_all_six_fields_when_llm_cooperates(tmp_path):
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "full_six_test",
    )
    client = _StubMultiSectionClient()
    result = creative_content(spec, client=client, cache_dir=tmp_path / "cc")
    assert set(result.keys()) == set(_CREATIVE_FIELDS)
    for field in _CREATIVE_FIELDS:
        assert result[field] == _FULL_SIX_FIELDS[field]


# ---------------------------------------------------------------------------
# 2. Partial response — LLM omits some fields
# ---------------------------------------------------------------------------

def test_creative_returns_partial_dict_when_llm_omits_fields(tmp_path):
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "partial_test",
    )
    # LLM returns only readme_intro + design_philosophy.
    partial = {
        "readme_intro": _FULL_SIX_FIELDS["readme_intro"],
        "design_philosophy": _FULL_SIX_FIELDS["design_philosophy"],
    }
    client = _StubMultiSectionClient(fields=partial)
    result = creative_content(spec, client=client, cache_dir=tmp_path / "cc")
    assert "readme_intro" in result
    assert "design_philosophy" in result
    assert "what_its_good_at" not in result
    assert "what_its_bad_at" not in result
    assert "example_commentary" not in result
    assert "common_mistake" not in result


# ---------------------------------------------------------------------------
# 3. Total LLM failure → {}
# ---------------------------------------------------------------------------

def test_creative_falls_back_to_empty_when_llm_fails(tmp_path):
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "fail_test",
    )
    client = _StubMultiSectionClient(fail=True)
    result = creative_content(spec, client=client, cache_dir=tmp_path / "cc")
    assert result == {}


# ---------------------------------------------------------------------------
# 4. Word-count validation
# ---------------------------------------------------------------------------

def test_creative_trims_pathologically_long_field(tmp_path):
    """If the LLM returns a 500-word what_its_bad_at, the validator
    trims it to roughly 2x the upper bound. Other fields unaffected."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "long_field_test",
    )
    # what_its_bad_at target is 40-80 words; hard cap is 80*2 = 160.
    huge = (". ".join(f"word{i}" for i in range(500)) + ".")
    overgrown = dict(_FULL_SIX_FIELDS)
    overgrown["what_its_bad_at"] = huge
    client = _StubMultiSectionClient(fields=overgrown)
    result = creative_content(spec, client=client, cache_dir=tmp_path / "cc")
    assert "what_its_bad_at" in result
    n = len(result["what_its_bad_at"].split())
    assert n <= 200, f"trimmed field should be ≤200 words; got {n}"
    # Other fields unaffected.
    assert result["readme_intro"] == _FULL_SIX_FIELDS["readme_intro"]


def test_creative_drops_pathologically_short_field(tmp_path):
    """A field that's wildly under its target (< half the lower bound)
    gets dropped from the result, but the rest of the dict remains."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "short_field_test",
    )
    # what_its_good_at lower bound is 40; half = 20; "ok" is 1 word.
    too_short = dict(_FULL_SIX_FIELDS)
    too_short["what_its_good_at"] = "ok"
    client = _StubMultiSectionClient(fields=too_short)
    result = creative_content(spec, client=client, cache_dir=tmp_path / "cc")
    assert "what_its_good_at" not in result
    # The other 5 still present.
    assert "readme_intro" in result
    assert "design_philosophy" in result


def test_validate_field_helper_directly():
    """Unit test the validator: too short → None, in range → as-is,
    too long → trimmed."""
    short = _validate_field_word_count("readme_intro", "tiny")
    assert short is None

    in_range = " ".join(["word"] * 100)
    assert _validate_field_word_count("readme_intro", in_range) == in_range

    too_long = ". ".join(["word"] * 600) + "."
    trimmed = _validate_field_word_count("readme_intro", too_long)
    assert trimmed is not None
    # readme_intro hard_cap = 180 * 2 = 360.
    assert len(trimmed.split()) <= 400


# ---------------------------------------------------------------------------
# 5. Renderer inlines all six fields at the right positions
# ---------------------------------------------------------------------------

def test_render_templated_readme_inlines_all_six_fields():
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "render_full_test",
    )
    spec["creative"] = dict(_FULL_SIX_FIELDS)
    out = _render_templated_readme(spec)

    # Each field's content appears.
    for field, value in _FULL_SIX_FIELDS.items():
        # Take a distinctive substring from each so we don't depend on
        # exact whitespace.
        snippet = value.split(".")[0]
        assert snippet in out, (
            f"field {field} (content: {snippet!r}) missing from rendered "
            f"README"
        )

    # Headings for the three "this language..." sections.
    assert "## What this language is good at" in out
    assert "## What this language is not good at" in out
    assert "## A common mistake" in out

    # Section ORDER: readme_intro should appear before design_philosophy,
    # which appears before what_its_good_at.
    intro_pos = out.find(_FULL_SIX_FIELDS["readme_intro"][:40])
    philo_pos = out.find(_FULL_SIX_FIELDS["design_philosophy"][:40])
    good_pos = out.find(_FULL_SIX_FIELDS["what_its_good_at"][:40])
    bad_pos = out.find(_FULL_SIX_FIELDS["what_its_bad_at"][:40])
    mistake_pos = out.find(_FULL_SIX_FIELDS["common_mistake"][:40])
    assert intro_pos < philo_pos < good_pos < bad_pos < mistake_pos, (
        f"section order broke: intro={intro_pos} philo={philo_pos} "
        f"good={good_pos} bad={bad_pos} mistake={mistake_pos}"
    )


def test_render_templated_readme_omits_missing_sections():
    """When only readme_intro + design_philosophy are present, the
    rendered README must NOT contain the headings for the four
    missing sections."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "render_partial_test",
    )
    spec["creative"] = {
        "readme_intro": _FULL_SIX_FIELDS["readme_intro"],
        "design_philosophy": _FULL_SIX_FIELDS["design_philosophy"],
    }
    out = _render_templated_readme(spec)

    # Present fields ARE rendered.
    assert _FULL_SIX_FIELDS["readme_intro"][:50] in out
    assert _FULL_SIX_FIELDS["design_philosophy"][:50] in out

    # Missing fields: no headings, no orphan content.
    assert "## What this language is good at" not in out
    assert "## What this language is not good at" not in out
    assert "## A common mistake" not in out
    assert _FULL_SIX_FIELDS["what_its_good_at"][:30] not in out
    assert _FULL_SIX_FIELDS["common_mistake"][:30] not in out


def test_render_templated_readme_empty_creative_fallback():
    """When spec has no `creative` key, the README still renders
    cleanly with no headings for the missing creative sections."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "no_creative_test",
    )
    # No spec["creative"] at all.
    out = _render_templated_readme(spec)
    assert "## What this language is good at" not in out
    assert "## A common mistake" not in out
    # Existing template sections still render.
    assert "# no_creative_test" in out
    assert "## At a glance" in out


# ---------------------------------------------------------------------------
# 6. Cache version bump invalidates old entries
# ---------------------------------------------------------------------------

def test_creative_prompt_version_is_2():
    """Variance-improvement bumped CREATIVE_PROMPT_VERSION from 1 to
    2. This pins the bump so a future edit that adds fields without
    bumping the version doesn't silently serve stale cached entries
    against a new renderer."""
    assert CREATIVE_PROMPT_VERSION == 2


def test_cache_version_in_key_invalidates_old_entries(tmp_path):
    """The CREATIVE_PROMPT_VERSION is folded into the cache key. An
    entry written under v1 wouldn't be served when the code is at v2
    because the key would differ. We verify this indirectly by
    writing a fake v1 file at what WOULD have been v1's key, then
    calling creative_content and asserting it hits the LLM (not the
    fake v1 cache)."""
    import hashlib
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "version_test",
    )
    cache_dir = tmp_path / "cc"
    cache_dir.mkdir()

    # Construct the v1 cache key the way pre-variance code did.
    from forge.orchestrator.creative import _CACHE_KEY_IGNORE_FIELDS
    stripped = {k: v for k, v in spec.items()
                if k not in _CACHE_KEY_IGNORE_FIELDS}
    v1_blob = (json.dumps(stripped, sort_keys=True, default=str)
               + "|prompt=1").encode("utf-8")
    v1_key = hashlib.sha256(v1_blob).hexdigest()[:16]
    (cache_dir / f"{v1_key}.json").write_text(
        json.dumps({"readme_intro": "stale v1 content"}), encoding="utf-8")

    # Now creative_content should NOT find a v2 cache entry (because we
    # wrote a v1 key) and should hit the stub LLM instead.
    client = _StubMultiSectionClient()
    result = creative_content(spec, client=client, cache_dir=cache_dir)
    assert client.calls == ["gen-creative"], (
        "the v1-keyed cache file should NOT have been served against the "
        f"v2 prompt; got calls={client.calls}"
    )
    # And the fresh result should be the multi-section one, not the
    # stale single-field one.
    assert result["readme_intro"] != "stale v1 content"
    assert set(result.keys()) == set(_CREATIVE_FIELDS)


# ---------------------------------------------------------------------------
# 7. End-to-end integration test (slow)
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_creative_cache():
    clear_creative_cache()
    yield
    clear_creative_cache()


@pytest.mark.slow
def test_full_generation_with_multi_section_creative_passes_canonical(
        tmp_path, fresh_creative_cache):
    """End-to-end: generate a complete c_like language with the multi-
    section creative call returning all six fields. Confirm:
      - exactly one gen-creative LLM call
      - resolved_spec.json snapshots the full six-field creative block
      - README renders all six sections
      - The 8 canonical tests still pass (the creative change doesn't
        break generation)"""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "end_to_end_test",
    )
    client = _StubMultiSectionClient()
    generate_all(spec, output_root=tmp_path, client=client,
                 verify_after_generation=True)
    assert client.calls == ["gen-creative"]

    # resolved_spec.json has all six fields
    saved = json.loads(
        (tmp_path / "end_to_end_test" / "resolved_spec.json").read_text(encoding="utf-8")
    )
    creative = saved.get("creative") or {}
    for field in _CREATIVE_FIELDS:
        assert field in creative, (
            f"resolved_spec.json missing field {field} from creative block"
        )

    # README rendered all six
    readme = (tmp_path / "end_to_end_test" / "README.md").read_text(encoding="utf-8")
    for field, value in _FULL_SIX_FIELDS.items():
        snippet = value.split(".")[0]
        assert snippet in readme

    # Canonical tests passed (verify_after_generation=True populates
    # generation_summary.json with the canonical_tests block).
    summary = json.loads(
        (tmp_path / "end_to_end_test" / "generation_summary.json").read_text(encoding="utf-8")
    )
    ct = summary.get("canonical_tests") or {}
    assert ct.get("passed", 0) == ct.get("total", 0) and ct.get("total", 0) > 0, (
        f"canonical tests must pass after multi-section creative; got {ct}"
    )
