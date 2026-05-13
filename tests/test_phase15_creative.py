"""Phase 1.5 Stage D — small creative-content LLM call.

Pins:
- `creative_content(spec, ...)` returns a dict with `readme_intro`
  when the LLM responds.
- The cache is lang_name-insensitive (matches the resolver's P1 fix):
  two slots that differ only in slot_id share one cache hit.
- `creative_content` falls back to {} on any LLM failure (must never
  break generation).
- `_render_templated_readme` inlines `spec["creative"]["readme_intro"]`
  when present.
- The wiring in `generate_all` calls creative_content exactly once
  per generation, fires the `gen-creative` tag in telemetry, and is
  skippable via `enrich_creative=False`.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from forge.orchestrator.creative import (
    creative_content, clear_creative_cache, _cache_key,
    CREATIVE_PROMPT_VERSION,
)
from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.generator import (
    generate_all, _render_templated_readme,
)


WORKSPACE = Path(__file__).resolve().parents[1]


# A 100-word readme_intro that passes the variance-improvement word-
# count floor (the minimum is 40 words for readme_intro / 2 = 20-ish).
# Tests that don't care about specific content reuse this.
_DEFAULT_README_INTRO = (
    "This is a stub readme_intro produced by the test client. It "
    "exists only to give the renderer something concrete to inline. "
    "The variance-improvement validation requires that readme_intro "
    "be at least 40 words long after stripping whitespace, so this "
    "sentence keeps padding the count to make sure it lands inside "
    "the loose validation window the creative module enforces against "
    "real LLM outputs. None of this content is meant to be "
    "evocative. Tests assert on shape, not voice."
)


class _StubCreativeClient:
    """Returns a canned JSON response for `gen-creative`. Records every
    call so tests can pin call counts.

    Variance-improvement: the call surface is now `call_json` against
    a 6-field schema. By default this client returns just `readme_intro`
    (the only required field) — tests that need more fields pass them
    via `extra_fields`.
    """
    log_dir = None
    model = "stub-creative"
    telemetry = None

    def __init__(self, response: str = _DEFAULT_README_INTRO,
                 extra_fields: dict | None = None):
        self.calls: list[str] = []
        self.response = response
        self.extra_fields = extra_fields or {}

    def call_json(self, prompt, schema, *, tag="json", **kw):
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, tag, time.monotonic() - 0.01,
                        100, 50, 1, True, None)
        self.calls.append(tag)
        result = {"readme_intro": self.response}
        result.update(self.extra_fields)
        return result

    def call_code(self, *a, **kw):
        # Legacy method; kept for compatibility with other code paths.
        return self.response

    def call_chat(self, *a, **kw):
        return ""


# ---------------------------------------------------------------------------
# creative_content unit tests
# ---------------------------------------------------------------------------

def test_creative_content_returns_readme_intro(tmp_path):
    """Variance-improvement: the result still has `readme_intro` (the
    required field). Additional fields may or may not be present
    depending on what the LLM returned; here the stub only returns
    readme_intro, so the dict has exactly that key."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "creative_test",
    )
    client = _StubCreativeClient()
    result = creative_content(spec, client=client, cache_dir=tmp_path / "cc")
    assert "readme_intro" in result
    assert result["readme_intro"] == _DEFAULT_README_INTRO
    assert client.calls == ["gen-creative"]


def test_creative_content_caches_by_content_hash(tmp_path):
    """Two calls with the same spec hit the cache on the second call."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "cache_test",
    )
    cache_dir = tmp_path / "cc"
    client = _StubCreativeClient()  # default response passes validation
    r1 = creative_content(spec, client=client, cache_dir=cache_dir)
    r2 = creative_content(spec, client=client, cache_dir=cache_dir)
    assert r1 == r2
    assert client.calls == ["gen-creative"], (
        f"second call should hit cache; got {client.calls}"
    )


def test_creative_cache_lang_name_insensitive(tmp_path):
    """Phase 1.5 P1-aligned: two slots differing only in lang_name
    must share one cache entry. Without this, a 50-slot batch where
    slots share options pays the creative-LLM cost 50 times."""
    spec_a = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "slot_001",
    )
    spec_b = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "slot_002",
    )
    cache_dir = tmp_path / "cc"
    client = _StubCreativeClient()
    creative_content(spec_a, client=client, cache_dir=cache_dir)
    creative_content(spec_b, client=client, cache_dir=cache_dir)
    assert len(client.calls) == 1, (
        f"creative cache should be lang_name-insensitive; got "
        f"{len(client.calls)} calls (expected 1)"
    )
    # Exactly one cache file on disk.
    files = list(cache_dir.glob("*.json"))
    assert len(files) == 1


def test_creative_cache_distinct_options_get_distinct_keys(tmp_path):
    """Sanity counterpart: different options → different cache keys."""
    spec_a = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "shared_name",
    )
    spec_b = build_spec(
        {"syntax": "python_like", "typing": "static", "memory": "refcount"},
        "shared_name",
    )
    assert _cache_key(spec_a) != _cache_key(spec_b)


def test_creative_use_cache_false_bypasses_cache(tmp_path):
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "no_cache_test",
    )
    cache_dir = tmp_path / "cc"
    client = _StubCreativeClient()
    creative_content(spec, client=client, cache_dir=cache_dir)
    creative_content(spec, client=client, cache_dir=cache_dir, use_cache=False)
    assert len(client.calls) == 2, "use_cache=False should re-call the LLM"


def test_creative_content_swallows_llm_failures(tmp_path):
    """A failing LLM client must NOT break generation. creative_content
    should return an empty dict and let templated renderers fall back
    to no intro."""
    class _FailingClient:
        log_dir = None; model = "fail"; telemetry = None
        calls: list = []
        def call_json(self, *a, **kw):
            raise RuntimeError("synthetic LLM failure")
        def call_code(self, *a, **kw):
            raise RuntimeError("synthetic LLM failure")
        def call_chat(self, *a, **kw): return ""

    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "failing_test",
    )
    result = creative_content(
        spec, client=_FailingClient(), cache_dir=tmp_path / "cc")
    assert result == {}, (
        f"creative_content should swallow LLM failures and return {{}}; "
        f"got {result}"
    )


def test_clear_creative_cache(tmp_path):
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "clear_test",
    )
    cache_dir = tmp_path / "cc"
    client = _StubCreativeClient()
    creative_content(spec, client=client, cache_dir=cache_dir)
    assert len(list(cache_dir.glob("*.json"))) == 1
    n = clear_creative_cache(cache_dir)
    assert n == 1
    assert len(list(cache_dir.glob("*.json"))) == 0


def test_creative_drops_too_short_readme_intro(tmp_path):
    """Variance-improvement: the loose-validation pass drops fields
    that are pathologically short (less than half the lower bound).
    For readme_intro the lower bound is 80, so anything under ~40
    words gets dropped — and since readme_intro is required, the
    whole creative block returns {} when its headline is missing."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "short_intro_test",
    )
    client = _StubCreativeClient(response="Tiny.")
    result = creative_content(spec, client=client, cache_dir=tmp_path / "cc")
    assert result == {}, (
        f"a 1-word readme_intro should fail validation and trigger "
        f"the empty-creative fallback; got {result}"
    )


# ---------------------------------------------------------------------------
# Templated README inlines readme_intro
# ---------------------------------------------------------------------------

def test_templated_readme_inlines_creative_intro_when_present():
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "intro_test",
    )
    spec["creative"] = {"readme_intro": "MY DISTINCTIVE INTRO PARAGRAPH"}
    out = _render_templated_readme(spec)
    assert "MY DISTINCTIVE INTRO PARAGRAPH" in out


def test_templated_readme_omits_intro_when_absent():
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "no_intro_test",
    )
    # No spec["creative"]; renderer must not crash and not insert
    # any placeholder.
    out = _render_templated_readme(spec)
    # The rest of the template still renders.
    assert "# no_intro_test" in out
    assert "## At a glance" in out


# ---------------------------------------------------------------------------
# generate_all wiring
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_creative_cache():
    """The wiring tests use generate_all which writes to the DEFAULT
    creative cache dir (`.forge_cache/creative/`). Earlier test runs
    pollute it with stub responses; clear before each wiring test so
    the test exercises a fresh LLM call path."""
    clear_creative_cache()
    yield
    clear_creative_cache()


@pytest.mark.slow
def test_generate_all_calls_creative_once_for_clike(tmp_path, fresh_creative_cache):
    """Stage D wiring: a default c_like generation through generate_all
    triggers exactly one `gen-creative` call."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "wiring_test",
    )
    # Stub returns default 100-word readme_intro (validation passes).
    client = _StubCreativeClient()
    generate_all(spec, output_root=tmp_path, client=client,
                 verify_after_generation=False)
    assert client.calls == ["gen-creative"], (
        f"expected exactly one gen-creative call; got {client.calls}"
    )
    # The README should contain the creative intro.
    readme = (tmp_path / "wiring_test" / "README.md").read_text(encoding="utf-8")
    assert "stub readme_intro produced by the test client" in readme


@pytest.mark.slow
def test_generate_all_skips_creative_when_only_set(tmp_path):
    """Per-component re-runs (only=...) should NOT trigger the
    creative call. Otherwise a user clicking "regenerate readme"
    in the GUI would burn a creative-LLM call every time."""
    # First generate fully to set up the lang dir.
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "only_skip_test",
    )
    pre_client = _StubCreativeClient(response="Pre-existing intro.")
    generate_all(spec, output_root=tmp_path, client=pre_client,
                 verify_after_generation=False)

    # Now re-run with only=["readme"]. Creative should NOT fire again.
    rerun_client = _StubCreativeClient(response="Should not appear.")
    generate_all(spec, output_root=tmp_path, client=rerun_client,
                 only=["readme"], verify_after_generation=False)
    assert "gen-creative" not in rerun_client.calls, (
        f"creative should not fire on per-component reruns; "
        f"got {rerun_client.calls}"
    )


@pytest.mark.slow
def test_generate_all_enrich_creative_false_skips_call(tmp_path):
    """`enrich_creative=False` opts out of the creative call entirely.
    For fully-offline batch runs."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "no_creative_test",
    )
    client = _StubCreativeClient()
    generate_all(spec, output_root=tmp_path, client=client,
                 enrich_creative=False, verify_after_generation=False)
    assert client.calls == [], (
        f"enrich_creative=False should skip the creative call; "
        f"got {client.calls}"
    )


@pytest.mark.slow
def test_generate_all_persists_creative_in_resolved_spec(tmp_path, fresh_creative_cache):
    """The creative content should land inside resolved_spec.json so
    subsequent steps (verifier, smoke test, repair) see it."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "persist_test",
    )
    client = _StubCreativeClient()  # default 100-word intro
    generate_all(spec, output_root=tmp_path, client=client,
                 verify_after_generation=False)
    saved = json.loads(
        (tmp_path / "persist_test" / "resolved_spec.json").read_text(encoding="utf-8")
    )
    assert saved.get("creative", {}).get("readme_intro") == _DEFAULT_README_INTRO
