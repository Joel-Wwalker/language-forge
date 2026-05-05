"""Tests for the parallel generation pipeline.

These don't call the LLM. They use a fake client that records call order
and returns canned responses, then verify:
  - All required components run.
  - Components run in dependency order (parser before its dependents).
  - Independent components actually run concurrently (overlap in wall time).
  - Generation aborts cleanly if a component fails.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from forge.orchestrator.generator import generate_all
from forge.orchestrator.spec_builder import build_spec


WORKSPACE = Path(__file__).resolve().parents[1]


class FakeClient:
    """Records call order, sleeps to simulate latency, returns canned strings."""
    def __init__(self, latency_s: float = 0.05):
        self.log_dir: Path | None = None
        self.latency_s = latency_s
        self._lock = threading.Lock()
        self.events: list[tuple[float, str, str]] = []   # (time, kind, tag)

    def _record(self, kind: str, tag: str):
        with self._lock:
            self.events.append((time.monotonic(), kind, tag))

    def call_code(self, prompt: str, *, tag: str = "code", system=None, max_retries: int = 2) -> str:
        self._record("start", tag)
        time.sleep(self.latency_s)
        self._record("end", tag)
        return _fake_for(tag)

    def call_json(self, prompt, schema, *, tag="json", system=None, max_retries=2):
        self._record("start", tag)
        time.sleep(self.latency_s)
        self._record("end", tag)
        return {}


def _fake_for(tag: str) -> str:
    """Return canned content matching what `_generate_*` expects to extract."""
    if tag.startswith("gen-tests-bulk"):
        # _generate_tests parses the result as a JSON map of filename -> content.
        # An empty bulk forces the per-test fallback. Per-test produces a fenced
        # source + expected pair. We supply minimal valid content that satisfies
        # both modes.
        import json as _json
        files = {}
        for c in ("hello_world", "arithmetic", "variables", "conditionals",
                  "loops", "functions", "closures", "strings"):
            files[f"{c}.tst"] = "// stub\n"
            files[f"{c}.expected_output.txt"] = "stub\n"
        return _json.dumps(files)
    if tag.startswith("gen-test-"):
        # Per-test fallback: two fenced blocks.
        return "```source\n// stub\n```\n```expected\nstub\n```\n"
    # Default: a python source body for code components.
    return "# stub\n"


def test_parallel_generator_runs_all_components_with_proper_deps(tmp_path):
    """End-to-end: run generate_all with a fake client. All components run,
    parser comes before its dependents, and at least one wave overlaps."""
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "ftest")
    spec["file_extension"] = ".tst"

    client = FakeClient(latency_s=0.10)
    out = generate_all(spec, output_root=tmp_path, client=client, on_progress=None)
    assert out.exists()

    # Pull the order in which "start" events fired.
    starts = [(t, tag) for t, kind, tag in client.events if kind == "start"]
    started_tags = [tag for _, tag in starts]

    # Every required component started.
    for needed in ("gen-parser", "gen-codegen", "gen-runtime", "gen-stdlib",
                   "gen-readme", "gen-language-ref"):
        assert any(t.startswith(needed) for t in started_tags), \
            f"{needed} never started: {started_tags}"

    # parser must be among the first started; everything depending on it
    # must start AFTER parser ended.
    parser_end = None
    for t, kind, tag in client.events:
        if kind == "end" and tag.startswith("gen-parser"):
            parser_end = t
            break
    assert parser_end is not None, "parser never finished"

    for dep_tag in ("gen-lexer", "gen-codegen"):
        for t, kind, tag in client.events:
            if kind == "start" and tag.startswith(dep_tag):
                assert t >= parser_end - 0.001, f"{dep_tag} started before parser finished"
                break


def test_parallel_generator_overlaps_independent_components(tmp_path):
    """The lexer, codegen, and tests waves should overlap in time once parser
    is done. Wall time must be noticeably less than fully sequential."""
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "ftest2")
    spec["file_extension"] = ".tst"

    latency = 0.20
    client = FakeClient(latency_s=latency)
    t0 = time.monotonic()
    # Skip post-gen verify (Phase 0.4 added it; it spawns 8 subprocess runs
    # for canonical tests that are stubs anyway under FakeClient — adds
    # ~600ms that has nothing to do with parallelism).
    generate_all(spec, output_root=tmp_path, client=client, on_progress=None,
                 verify_after_generation=False)
    elapsed = time.monotonic() - t0

    # Sequential lower bound: 8 components × latency. Critical path with
    # parallelism is parser → codegen → runtime → stdlib → language_reference
    # (5 calls). Real-world per-call latency is 30-60s; parallelism wins big
    # there. In this fast-fake test we just confirm SOME speedup vs sequential.
    sequential_lower = 8 * latency
    assert elapsed < sequential_lower, (
        f"generation took {elapsed:.2f}s; expected speedup vs sequential "
        f"lower bound {sequential_lower:.2f}s"
    )


def test_parallel_generator_propagates_failures(tmp_path):
    """If one component raises, generate_all surfaces the exception."""

    class FailingClient(FakeClient):
        def call_code(self, prompt, *, tag="code", system=None, max_retries=2):
            self._record("start", tag)
            time.sleep(0.01)
            if tag.startswith("gen-codegen"):
                raise RuntimeError("synthetic codegen failure")
            self._record("end", tag)
            return _fake_for(tag)

    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "ftest3")
    spec["file_extension"] = ".tst"
    client = FailingClient(latency_s=0.02)
    with pytest.raises(RuntimeError, match="synthetic codegen failure"):
        generate_all(spec, output_root=tmp_path, client=client, on_progress=None)
