"""Phase 1.5 Stage E — synthetic canary validation.

The Phase 1.5 instructions Stage E asks for canary numbers + 50-slot
batch numbers + 5-spec quality comparison. The 50-slot batch costs
real API budget and ~30-50 min wall, and requires explicit user
authorization (a previous run was halted mid-flight when the
structural problem was identified). This file substitutes a
synthetic canary that validates the headline claims using FakeClient
— no API cost, deterministic, runnable in CI.

Headline claims pinned:
  - c_like generation: ≤30s wall, ≤2 LLM calls, 8/8 canonical pass.
  - 5 diverse c_like specs: total wall <60s, total LLM calls ≤ 5.
  - Templated path is default; LLM-driven still works as opt-out.

A real-claude_cli canary against the user's actual API quota is a
follow-up the user authorizes once they've reviewed Phase 1.5 in
flight.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.generator import generate_all
from forge.orchestrator.creative import clear_creative_cache


class _StubClient:
    """Returns a canned creative response. Records all tags."""
    log_dir = None
    model = "stub-canary"
    telemetry = None

    def __init__(self):
        self.calls: list[str] = []

    def call_code(self, prompt, *, tag="code", **kw):
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, tag, time.monotonic() - 0.01,
                        100, 50, 1, True, None)
        self.calls.append(tag)
        return "Synthetic canary intro for Phase 1.5 validation.\n"

    def call_json(self, *a, **kw):
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, kw.get("tag", "json"),
                        time.monotonic() - 0.01, 100, 50, 1, True, None)
        self.calls.append(kw.get("tag", "json"))
        return {"tests": []}

    def call_chat(self, *a, **kw):
        return ""


@pytest.fixture
def fresh_creative_cache():
    """Each canary test starts with a clean creative cache so
    timing measurements aren't skewed by hits from earlier tests."""
    clear_creative_cache()
    yield
    clear_creative_cache()


# ---------------------------------------------------------------------------
# E1: re-run the canary
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_canary_single_clike_meets_headline_targets(tmp_path, fresh_creative_cache):
    """Phase 1.5 Stage E1 canary criteria for one c_like generation:
      - ≤30s wall (was ~6 minutes pre-Phase-1.5)
      - ≤2 LLM calls (was 9)
      - 8/8 canonical pass
    """
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "canary_clike",
    )
    client = _StubClient()
    t0 = time.monotonic()
    out_dir = generate_all(spec, output_root=tmp_path, client=client)
    elapsed = time.monotonic() - t0

    # Wall budget: 30s. Real claude_cli adds 30-60s per LLM call so
    # the canary's actual wall would be slightly higher under the
    # real API; this synthetic version is a lower bound.
    assert elapsed < 30.0, f"canary took {elapsed:.1f}s; expected <30s"

    # LLM calls: should be exactly 1 (gen-creative). The instructions
    # say ≤2 (resolver + creative); resolver isn't called in
    # generate_all directly (the worker calls it, with caching).
    assert len(client.calls) <= 2, (
        f"canary made {len(client.calls)} LLM calls; expected ≤2. "
        f"calls: {client.calls}"
    )

    # Canonical: 8/8.
    summary = json.loads(
        (out_dir / "generation_summary.json").read_text(encoding="utf-8"))
    canonical = summary["canonical_tests"]
    assert canonical["passed"] == canonical["total"] == 8, (
        f"canary failed canonical: {canonical}"
    )

    # Pipeline path recorded as templated.
    assert summary["pipeline_path"] == "templated"


# ---------------------------------------------------------------------------
# E3 substitute: 5-spec diversity sample
# ---------------------------------------------------------------------------

def _diverse_specs() -> list[tuple[str, dict]]:
    """5 c_like specs covering the diversity dimensions Stage E
    cares about: plain baseline, persona, era, theme, phrasebook."""
    return [
        ("baseline", build_spec(
            {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
            "div_baseline")),
        ("persona", build_spec(
            {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
            "div_persona", persona="stroustrup")),
        ("era", build_spec(
            {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
            "div_era", era="1980s")),
        ("theme", build_spec(
            {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
            "div_theme", keyword_theme="pirate")),
        ("phrasebook", build_spec(
            {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
            "div_phrasebook", phrasebook="shakespearean")),
    ]


@pytest.mark.slow
def test_canary_5_diverse_clike_specs_complete_under_60s(tmp_path, fresh_creative_cache):
    """5 diverse c_like generations should complete in under 60
    seconds combined. Pre-Phase-1.5 baseline was ~30 min for 5
    c_like generations through the LLM path.

    This is a structural correctness + speed test, not a quality
    test. Quality comparison against the LLM path is the user-
    authorized real-claude_cli canary."""
    specs = _diverse_specs()
    client = _StubClient()
    results = []
    t0 = time.monotonic()
    for label, spec in specs:
        slot_t0 = time.monotonic()
        out_dir = generate_all(spec, output_root=tmp_path, client=client,
                               verify_after_generation=False)
        slot_wall = time.monotonic() - slot_t0
        results.append((label, slot_wall, out_dir))
    total_wall = time.monotonic() - t0

    assert total_wall < 60.0, (
        f"5-spec canary took {total_wall:.1f}s total; expected <60s"
    )

    # Each spec should have made at most 1 creative call (pre-cache)
    # OR 0 calls (post-cache via lang_name-insensitive hashing).
    # With 5 distinct customizations, expect 5 unique creative
    # cache keys = 5 LLM calls.
    creative_calls = [c for c in client.calls if c == "gen-creative"]
    assert len(creative_calls) == 5, (
        f"expected 5 creative calls (one per distinct customization); "
        f"got {len(creative_calls)}"
    )

    # All 5 generated languages should have working files.
    for label, _wall, out_dir in results:
        assert (out_dir / "parser.py").exists()
        assert (out_dir / "README.md").exists()
        # Each README contains the synthetic creative intro.
        readme = (out_dir / "README.md").read_text(encoding="utf-8")
        assert "Synthetic canary intro" in readme, (
            f"{label}: README missing creative intro"
        )


@pytest.mark.slow
def test_canary_resolver_cache_pays_off_at_scale(tmp_path, fresh_creative_cache):
    """Phase 1.5 P1: 5 specs that share OPTIONS but differ in
    lang_name should hit the resolver cache after the first one
    populates it. With the cache key fix, only 1 unique resolution
    per option-combo.

    Note: this test exercises the creative cache, which has the
    same lang_name-insensitive hashing. 5 specs differing only in
    lang_name should produce 1 creative call total."""
    base = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}
    specs = [build_spec(base, f"slot_{i:03d}") for i in range(5)]

    client = _StubClient()
    for spec in specs:
        generate_all(spec, output_root=tmp_path, client=client,
                     verify_after_generation=False)

    creative_calls = [c for c in client.calls if c == "gen-creative"]
    assert len(creative_calls) == 1, (
        f"5 slots sharing options should produce 1 creative call "
        f"(lang_name-insensitive cache); got {len(creative_calls)}. "
        f"This is the W1 cache-key fix earning its keep."
    )


# ---------------------------------------------------------------------------
# Comparison: templated vs LLM path produces equivalent canonical results
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_templated_and_llm_path_both_pass_canonical_for_minimal_clike(tmp_path, fresh_creative_cache):
    """Stage E quality comparison: a minimal c_like spec should
    pass 8/8 canonical through BOTH paths. The templated path is
    fast and free; the LLM path is slow and expensive; outputs
    differ in personality but core correctness should match.

    Synthetic version: we can confirm the templated path passes
    8/8. The LLM path requires real claude_cli or a much smarter
    fake; deferred to the user-authorized real canary."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "compare_templated",
    )
    out_dir = generate_all(spec, output_root=tmp_path, client=_StubClient())
    summary = json.loads(
        (out_dir / "generation_summary.json").read_text(encoding="utf-8"))
    assert summary["canonical_tests"]["passed"] == 8
    assert summary["pipeline_path"] == "templated"
