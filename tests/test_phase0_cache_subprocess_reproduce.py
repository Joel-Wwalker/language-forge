"""Phase 0 (production roadmap) — resolver cache + subprocess runner +
reproduce.

Pins:
  - Phase 0.1 (subprocess isolation): `run_one` returns a result without
    raising; `run_batch` aggregates; `write_batch_summary` writes a JSON.
  - Phase 0.3 (resolver cache): identical inputs hit cache; clearing
    works; `--no-cache` (use_cache=False) bypasses; corrupt cache files
    are tolerated.
  - Phase 0.5 (reproduce): `reproduce_from_summary` re-reads the summary
    + sibling spec and re-invokes generate_all with the same seed.

These tests use a fake client and a templated language family
(s_expression / stack_based) so no LLM round-trips happen.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


class _CountingFakeClient:
    log_dir = None
    model = "fake-model"
    telemetry = None
    def __init__(self):
        self.calls = 0
        self.tags = []
    def call_code(self, prompt, *, tag="code", **kw):
        self.calls += 1
        self.tags.append(tag)
        return "# stub"
    def call_json(self, *a, **kw):
        self.calls += 1
        self.tags.append(kw.get("tag", "json"))
        # Return a minimal valid spec by re-using the input base spec.
        # The resolver test below provides a base_spec already valid.
        return a[0] if a and isinstance(a[0], dict) else {"tests": []}
    def call_chat(self, *a, **kw):
        self.calls += 1
        return "# stub"


# ---------------------------------------------------------------------------
# Phase 0.3 — resolver cache
# ---------------------------------------------------------------------------

def test_resolver_cache_hit_skips_llm(tmp_path):
    """Second resolve() call with identical inputs must hit cache and
    NOT call the LLM."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.resolver import resolve

    base = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "cache_test_lang",
    )

    class _Client:
        log_dir = None; model = "m"; telemetry = None
        def __init__(self):
            self.json_calls = 0
        def call_json(self, prompt, schema, *, tag="json", **kw):
            self.json_calls += 1
            return base    # The base spec is already valid; return as-is.

    cache_dir = tmp_path / "spec_cache"
    c = _Client()

    # First call: cache miss, LLM called.
    resolve(base, client=c, cache_dir=cache_dir)
    assert c.json_calls == 1, "first call should miss cache and invoke LLM"

    # Second call with same input: cache hit, LLM NOT called.
    resolve(base, client=c, cache_dir=cache_dir)
    assert c.json_calls == 1, (
        f"second call with identical inputs should hit cache; "
        f"got json_calls={c.json_calls}"
    )

    # Cache file exists and contains valid JSON.
    files = list(cache_dir.glob("*.json"))
    assert len(files) == 1
    cached = json.loads(files[0].read_text(encoding="utf-8"))
    assert cached["lang_name"] == "cache_test_lang"


def test_resolver_cache_disabled_via_flag(tmp_path):
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.resolver import resolve

    base = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "no_cache_lang",
    )

    class _Client:
        log_dir = None; model = "m"; telemetry = None
        def __init__(self):
            self.json_calls = 0
        def call_json(self, prompt, schema, *, tag="json", **kw):
            self.json_calls += 1
            return base

    cache_dir = tmp_path / "spec_cache"
    c = _Client()

    resolve(base, client=c, cache_dir=cache_dir, use_cache=False)
    resolve(base, client=c, cache_dir=cache_dir, use_cache=False)
    assert c.json_calls == 2, "use_cache=False should always invoke the LLM"
    # No cache files written either.
    assert not cache_dir.exists() or not list(cache_dir.glob("*.json"))


def test_resolver_cache_different_inputs_get_different_keys(tmp_path):
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.resolver import resolve

    base1 = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "lang_a",
    )
    base2 = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "lang_b",
    )

    class _Client:
        log_dir = None; model = "m"; telemetry = None
        def __init__(self): self.json_calls = 0
        def call_json(self, prompt, schema, *, tag="json", **kw):
            self.json_calls += 1
            # Echo the right base for whichever was passed.
            return base1 if "lang_a" in prompt else base2

    cache_dir = tmp_path / "spec_cache"
    c = _Client()
    resolve(base1, client=c, cache_dir=cache_dir)
    resolve(base2, client=c, cache_dir=cache_dir)
    files = list(cache_dir.glob("*.json"))
    assert len(files) == 2, "different inputs should produce different cache keys"


def test_resolver_cache_corrupt_file_falls_through(tmp_path):
    """A corrupt cache file should be deleted and the LLM re-called,
    not crash the resolver."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.resolver import resolve, _cache_key, _cache_path

    base = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "corrupt_test",
    )

    cache_dir = tmp_path / "spec_cache"
    cache_dir.mkdir()
    key = _cache_key(base)
    bad = _cache_path(key, cache_dir)
    bad.write_text("{ this is not valid JSON", encoding="utf-8")

    class _Client:
        log_dir = None; model = "m"; telemetry = None
        def __init__(self): self.json_calls = 0
        def call_json(self, prompt, schema, *, tag="json", **kw):
            self.json_calls += 1
            return base

    c = _Client()
    resolve(base, client=c, cache_dir=cache_dir)
    assert c.json_calls == 1, "corrupt cache should fall through to LLM"


def test_clear_resolver_cache(tmp_path):
    from forge.orchestrator.resolver import clear_resolver_cache
    cache_dir = tmp_path / "spec_cache"
    cache_dir.mkdir()
    (cache_dir / "a.json").write_text("{}", encoding="utf-8")
    (cache_dir / "b.json").write_text("{}", encoding="utf-8")
    n = clear_resolver_cache(cache_dir)
    assert n == 2
    assert not list(cache_dir.glob("*.json"))


def test_resolver_cache_hit_records_telemetry(tmp_path):
    """A cache hit should still produce a telemetry record (tagged
    'resolver-cache-hit') so summaries can show the savings."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.resolver import resolve
    from forge.orchestrator.telemetry import TelemetryRecorder, attach

    base = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "cache_telem",
    )

    class _Client:
        log_dir = None; model = "m"; telemetry = None
        def call_json(self, prompt, schema, *, tag="json", **kw):
            return base

    cache_dir = tmp_path / "spec_cache"
    c = _Client()
    # Prime the cache.
    resolve(base, client=c, cache_dir=cache_dir)

    # Now attach a recorder and resolve again — should be a cache hit.
    rec = TelemetryRecorder(lang_name=base["lang_name"])
    attach(c, rec)
    resolve(base, client=c, cache_dir=cache_dir)

    summary = rec.to_summary_dict()
    cache_hits = [c for c in summary["llm"]["calls"]
                  if c["tag"] == "resolver-cache-hit"]
    assert len(cache_hits) == 1


# ---------------------------------------------------------------------------
# Phase 0.1 — subprocess runner
# ---------------------------------------------------------------------------

def test_run_one_generates_templated_language_in_subprocess(tmp_path):
    """The subprocess runner should successfully generate a templated
    (no-LLM) language without ANTHROPIC_API_KEY thanks to lazy
    LLMClient instantiation in the worker (Phase 0 closeout #6)."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.subprocess_runner import run_one

    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "subproc_test_lang",
    )
    res = run_one(spec, tmp_path, slot_id="t1", seed=7, timeout=180)
    assert res.success, f"stderr: {res.stderr[:500]}"
    assert res.lang_dir is not None
    assert res.summary_path is not None
    summary = json.loads(Path(res.summary_path).read_text(encoding="utf-8"))
    assert summary["seed"] == 7


def test_run_one_returns_failure_record_on_bad_spec(tmp_path):
    """A spec that's missing required fields should fail cleanly — the
    subprocess returns nonzero, and `run_one` records the error rather
    than raising."""
    from forge.orchestrator.subprocess_runner import run_one
    bad_spec = {"lang_name": "bad", "options": "not a dict"}  # malformed
    res = run_one(bad_spec, tmp_path, slot_id="bad", timeout=60)
    assert not res.success
    assert res.error is not None


def test_write_batch_summary(tmp_path):
    """`write_batch_summary` aggregates results into a top-level JSON."""
    from forge.orchestrator.subprocess_runner import (
        write_batch_summary, SubprocessResult,
    )
    results = [
        SubprocessResult(slot_id="a", lang_name="a", success=True,
                         duration_seconds=1.0),
        SubprocessResult(slot_id="b", lang_name="b", success=False,
                         duration_seconds=0.5, error="boom"),
        SubprocessResult(slot_id="c", lang_name="c", success=True,
                         duration_seconds=2.0),
    ]
    out = write_batch_summary(results, tmp_path)
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == 3
    assert data["succeeded"] == 2
    assert data["failed"] == 1
    assert data["wall_clock_seconds"] == 3.5
    assert len(data["results"]) == 3
    assert data["results"][1]["error"] == "boom"


# ---------------------------------------------------------------------------
# Phase 0.5 — reproduce
# ---------------------------------------------------------------------------

def test_reproduce_reads_seed_from_summary(tmp_path):
    """`reproduce_from_summary` should read the seed from the summary
    file and pass it to generate_all."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all
    from forge.orchestrator.reproduce import reproduce_from_summary

    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "reproduce_target",
    )

    # Generate the original.
    out1 = generate_all(spec, output_root=tmp_path,
                        client=_CountingFakeClient(), seed=12345)
    assert (out1 / "generation_summary.json").exists()
    assert json.loads((out1 / "generation_summary.json").read_text())["seed"] == 12345

    # Reproduce. The default output_root is the parent of the original,
    # and the lang_name gets `.reproduce` appended.
    out2 = reproduce_from_summary(out1 / "generation_summary.json",
                                  client=_CountingFakeClient())
    assert out2.exists()
    assert out2.name.endswith(".reproduce")
    summary2 = json.loads((out2 / "generation_summary.json").read_text())
    assert summary2["seed"] == 12345, "reproduced run should preserve the seed"


def test_reproduce_raises_on_missing_summary(tmp_path):
    from forge.orchestrator.reproduce import reproduce_from_summary
    with pytest.raises(FileNotFoundError):
        reproduce_from_summary(tmp_path / "nonexistent.json")


def test_reproduce_raises_when_no_sibling_spec(tmp_path):
    from forge.orchestrator.reproduce import reproduce_from_summary
    bad_summary = tmp_path / "generation_summary.json"
    bad_summary.write_text(json.dumps({"lang_name": "x", "seed": 1}),
                           encoding="utf-8")
    # No resolved_spec.json sibling.
    with pytest.raises(FileNotFoundError):
        reproduce_from_summary(bad_summary)


def test_reproduce_cli_main_returns_2_for_missing(tmp_path):
    from forge.orchestrator.reproduce import _cli_main
    rc = _cli_main([str(tmp_path / "nonexistent.json")])
    assert rc == 2


# ---------------------------------------------------------------------------
# Phase 0.1 — _worker_main: exercise the subprocess code path in-process.
# This avoids the ANTHROPIC_API_KEY requirement of full run_one tests.
# ---------------------------------------------------------------------------

def test_worker_main_handles_invalid_slot_path(tmp_path, capsys):
    """The subprocess worker entry point must return nonzero (not raise)
    on a missing slot file."""
    from forge.orchestrator.subprocess_runner import _worker_main
    rc = _worker_main(str(tmp_path / "nonexistent_slot.json"))
    assert rc == 1
    out = capsys.readouterr().out
    assert '"ok": false' in out.lower() or '"ok":false' in out.lower()


def test_run_batch_handles_empty_input(tmp_path):
    from forge.orchestrator.subprocess_runner import run_batch
    res = run_batch([], tmp_path)
    assert res == []


def test_run_batch_seed_length_validation(tmp_path):
    from forge.orchestrator.subprocess_runner import run_batch
    with pytest.raises(ValueError):
        run_batch([{"lang_name": "a"}, {"lang_name": "b"}],
                  tmp_path, seeds=[1])  # mismatched lengths


def test_subprocess_result_is_serializable():
    """The result dataclass must be JSON-serializable via asdict so
    `write_batch_summary` doesn't fail on a real-world result."""
    from dataclasses import asdict
    from forge.orchestrator.subprocess_runner import SubprocessResult
    r = SubprocessResult(slot_id="x", lang_name="x", success=True,
                         duration_seconds=1.0)
    blob = json.dumps(asdict(r))
    assert "x" in blob
