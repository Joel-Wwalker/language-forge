"""Phase 0 (production roadmap) — telemetry + repair budget tests.

Pins the contracts established in:
  - Phase 0.4 (generation telemetry): every generation writes a
    `generation_summary.json` with all expected fields populated.
  - Phase 0.2 (configurable repair budget): repair_run accepts a
    RepairBudget that overrides the interactive defaults.

These contracts are pre-conditions for the batch pipeline (Phase 1+),
where you can't tail logs interactively to debug failures.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# TelemetryRecorder unit tests (pure data structure)
# ---------------------------------------------------------------------------

def test_telemetry_recorder_starts_empty():
    from forge.orchestrator.telemetry import TelemetryRecorder
    r = TelemetryRecorder(lang_name="x", seed=42)
    s = r.to_summary_dict()
    assert s["lang_name"] == "x"
    assert s["seed"] == 42
    assert s["llm"]["total_calls"] == 0
    assert s["llm"]["total_input_tokens"] == 0
    assert s["llm"]["total_output_tokens"] == 0
    assert s["repair"]["total_attempts"] == 0
    assert s["canonical_tests"] is None
    assert s["kata_pack"] is None
    assert s["errors"] == []
    assert "generator_version" in s


def test_telemetry_records_llm_call():
    from forge.orchestrator.telemetry import TelemetryRecorder, LLMCallRecord
    r = TelemetryRecorder(lang_name="x")
    r.record_llm_call(LLMCallRecord(
        tag="gen-codegen", model="claude-sonnet-4-5",
        input_tokens=1000, output_tokens=200,
        duration_seconds=2.5, attempts=1, success=True,
    ))
    r.record_llm_call(LLMCallRecord(
        tag="gen-codegen", model="claude-sonnet-4-5",
        input_tokens=500, output_tokens=100,
        duration_seconds=1.0, attempts=2, success=True,
    ))
    s = r.to_summary_dict()
    assert s["llm"]["total_calls"] == 2
    assert s["llm"]["total_input_tokens"] == 1500
    assert s["llm"]["total_output_tokens"] == 300
    assert s["llm"]["by_tag"]["gen-codegen"]["calls"] == 2
    assert s["llm"]["by_tag"]["gen-codegen"]["input_tokens"] == 1500


def test_telemetry_records_repair_attempts():
    from forge.orchestrator.telemetry import TelemetryRecorder, RepairAttemptRecord
    r = TelemetryRecorder(lang_name="x")
    r.record_repair(RepairAttemptRecord(component="codegen", attempt=1, success=False))
    r.record_repair(RepairAttemptRecord(component="codegen", attempt=2, success=True))
    r.record_repair(RepairAttemptRecord(component="parser", attempt=1, success=True))
    s = r.to_summary_dict()
    assert s["repair"]["total_attempts"] == 3
    assert s["repair"]["by_component"] == {"codegen": 2, "parser": 1}


def test_telemetry_records_errors():
    from forge.orchestrator.telemetry import TelemetryRecorder
    r = TelemetryRecorder(lang_name="x")
    r.record_error("verifier", "timeout after 60s\nstack trace details...")
    s = r.to_summary_dict()
    assert len(s["errors"]) == 1
    assert s["errors"][0]["stage"] == "verifier"
    # Multi-line errors are trimmed to one line.
    assert "\n" not in s["errors"][0]["message"]


def test_telemetry_canonical_pass_rate():
    from forge.orchestrator.telemetry import TelemetryRecorder
    r = TelemetryRecorder(lang_name="x")
    r.set_canonical_results(passed=7, total=8)
    s = r.to_summary_dict()
    assert s["canonical_tests"] == {"passed": 7, "total": 8, "pass_rate": pytest.approx(0.875)}


def test_telemetry_kata_pass_rate():
    from forge.orchestrator.telemetry import TelemetryRecorder
    r = TelemetryRecorder(lang_name="x")
    r.set_kata_results(passed=10, total=13)
    s = r.to_summary_dict()
    assert s["kata_pack"]["passed"] == 10
    assert s["kata_pack"]["total"] == 13
    assert s["kata_pack"]["pass_rate"] == pytest.approx(10 / 13)


def test_telemetry_writes_atomic_json(tmp_path):
    from forge.orchestrator.telemetry import TelemetryRecorder
    r = TelemetryRecorder(lang_name="x", seed=99)
    out = r.write_summary(tmp_path)
    assert out.exists()
    assert out.name == "generation_summary.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["lang_name"] == "x"
    assert data["seed"] == 99


def test_telemetry_thread_safe_appends():
    """Append from many threads concurrently. The recorder must not lose
    records (which would happen with naive list.append + len() in race
    conditions on some interpreters)."""
    import threading
    from forge.orchestrator.telemetry import TelemetryRecorder, LLMCallRecord
    r = TelemetryRecorder(lang_name="x")
    N_THREADS = 8
    PER_THREAD = 50

    def worker():
        for i in range(PER_THREAD):
            r.record_llm_call(LLMCallRecord(
                tag=f"t{i % 3}", model="m", input_tokens=10, output_tokens=5,
                duration_seconds=0.01, attempts=1, success=True,
            ))

    threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
    for t in threads: t.start()
    for t in threads: t.join()
    s = r.to_summary_dict()
    assert s["llm"]["total_calls"] == N_THREADS * PER_THREAD
    assert s["llm"]["total_input_tokens"] == N_THREADS * PER_THREAD * 10


# ---------------------------------------------------------------------------
# attach() / detach() integration with a fake client
# ---------------------------------------------------------------------------

class _FakeClient:
    """Minimal stand-in for LLMClient so we can drive telemetry without
    touching the network."""
    log_dir = None
    model = "fake-model"
    def __init__(self):
        self.calls = []


def test_attach_telemetry_sets_client_attribute():
    from forge.orchestrator.telemetry import TelemetryRecorder, attach, detach
    r = TelemetryRecorder(lang_name="x")
    c = _FakeClient()
    attach(c, r)
    assert c.telemetry is r
    detach(c)
    assert c.telemetry is None


def test_emit_telemetry_no_op_without_recorder():
    """If no recorder is attached, _emit_telemetry must not raise."""
    from forge.orchestrator.llm_client import _emit_telemetry
    c = _FakeClient()
    # No telemetry attribute at all — should be a clean no-op.
    _emit_telemetry(c, "tag", time.monotonic(), 0, 0, 1, True, None)


def test_emit_telemetry_records_into_attached_recorder():
    from forge.orchestrator.telemetry import TelemetryRecorder, attach
    from forge.orchestrator.llm_client import _emit_telemetry
    r = TelemetryRecorder(lang_name="x")
    c = _FakeClient()
    attach(c, r)
    _emit_telemetry(c, "test-tag", time.monotonic() - 1.0, 100, 50, 1, True, None)
    s = r.to_summary_dict()
    assert s["llm"]["total_calls"] == 1
    assert s["llm"]["calls"][0]["tag"] == "test-tag"
    assert s["llm"]["calls"][0]["input_tokens"] == 100
    assert s["llm"]["calls"][0]["output_tokens"] == 50
    assert s["llm"]["calls"][0]["success"] is True
    assert s["llm"]["calls"][0]["duration_seconds"] >= 0.9


# ---------------------------------------------------------------------------
# generate_all: writes generation_summary.json with all required fields
# ---------------------------------------------------------------------------

class _CountingFakeClient:
    """A more realistic fake client that records calls AND honors the
    telemetry attribute set by `generate_all`."""
    log_dir = None
    model = "fake-model"
    telemetry = None
    def __init__(self):
        self.tags = []

    def _emit(self, tag):
        from forge.orchestrator.llm_client import _emit_telemetry
        # Pretend the call took 0.1s and used 50 tokens.
        t0 = time.monotonic() - 0.1
        _emit_telemetry(self, tag, t0, 50, 25, 1, True, None)

    def call_code(self, prompt, *, tag="code", **kw):
        self.tags.append(tag)
        self._emit(tag)
        return "# stub"

    def call_json(self, *a, **kw):
        tag = kw.get("tag", "json")
        self.tags.append(tag)
        self._emit(tag)
        return {"tests": []}

    def call_chat(self, *a, **kw):
        tag = kw.get("tag", "chat")
        self.tags.append(tag)
        self._emit(tag)
        return "# stub"


def test_generate_all_writes_summary_for_templated_language(tmp_path):
    """End-to-end: generating a stack_based language must write a
    `generation_summary.json` with all required fields populated."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "telemetry_test_lang",
    )
    client = _CountingFakeClient()
    out_dir = generate_all(spec, output_root=tmp_path, client=client, seed=1234)

    summary_path = out_dir / "generation_summary.json"
    assert summary_path.exists(), "generation_summary.json was not written"
    data = json.loads(summary_path.read_text(encoding="utf-8"))

    # Required field checks per the roadmap acceptance criteria.
    assert data["lang_name"] == "telemetry_test_lang"
    assert data["seed"] == 1234
    assert "wall_clock_seconds" in data
    assert data["wall_clock_seconds"] >= 0.0
    assert "started_at" in data
    assert "llm" in data
    assert "total_calls" in data["llm"]
    assert "total_input_tokens" in data["llm"]
    assert "total_output_tokens" in data["llm"]
    assert "repair" in data
    assert "errors" in data
    # Templated languages may make zero LLM calls (auto-validation pipeline
    # test pins this), so we just check the field exists rather than > 0.
    assert isinstance(data["llm"]["total_calls"], int)
    # Canonical tests should have been run; field is non-null on success.
    # (May be None if verifier itself crashed; in that case there's an error.)
    assert data["canonical_tests"] is not None or data["errors"], (
        "expected canonical test results OR a recorded verifier error"
    )
    # Stamped with generator version.
    assert "generator_version" in data


def test_generate_all_summary_has_seed_when_provided(tmp_path):
    """The seed parameter must round-trip into the summary."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "seeded_lisp",
    )
    out = generate_all(spec, output_root=tmp_path,
                       client=_CountingFakeClient(), seed=42)
    data = json.loads((out / "generation_summary.json").read_text(encoding="utf-8"))
    assert data["seed"] == 42


def test_generate_all_summary_seed_none_by_default(tmp_path):
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all
    spec = build_spec(
        {"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
        "unseeded_lisp",
    )
    out = generate_all(spec, output_root=tmp_path, client=_CountingFakeClient())
    data = json.loads((out / "generation_summary.json").read_text(encoding="utf-8"))
    assert data["seed"] is None


# ---------------------------------------------------------------------------
# RepairBudget (Phase 0.2)
# ---------------------------------------------------------------------------

def test_repair_budget_defaults_match_interactive_mode():
    """The default RepairBudget must equal the historical hardcoded
    constants so existing interactive callers are unaffected."""
    from forge.orchestrator.repair import (
        RepairBudget, MAX_ATTEMPTS_PER_COMPONENT, MAX_COMPONENTS_PER_RUN,
    )
    b = RepairBudget()
    assert b.max_attempts_per_component == MAX_ATTEMPTS_PER_COMPONENT
    assert b.max_components_per_run == MAX_COMPONENTS_PER_RUN
    assert b.time_budget_seconds is None


def test_repair_budget_batch_preset_is_larger():
    from forge.orchestrator.repair import RepairBudget
    b = RepairBudget.batch()
    assert b.max_attempts_per_component > 3
    assert b.max_components_per_run > 2
    assert b.time_budget_seconds is not None
    assert b.time_budget_seconds > 0


def test_repair_run_accepts_budget_argument(tmp_path):
    """repair_run must accept a `budget=` kwarg without TypeError. We
    don't drive a full repair here (would need a broken language to
    repair), but the signature contract matters for batch callers."""
    import inspect
    from forge.orchestrator.repair import repair_run, RepairBudget
    sig = inspect.signature(repair_run)
    assert "budget" in sig.parameters, "repair_run must accept a `budget` kwarg"
    # Default should be None (i.e., interactive defaults).
    assert sig.parameters["budget"].default is None
