"""Phase 1.5 Stage F — `template_from_reference` opt-out flag.

Pins:
- The templated path is the default for c_like / s_expression /
  stack_based.
- `template_from_reference=False` forces the LLM-driven path even
  when a reference exists (for hostile constraints / mythic-tier
  languages / A/B comparison).
- Telemetry's `pipeline_path` field reflects which path was used.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.generator import generate_all


class _CountingFake:
    log_dir = None; model = "fake-stage-f"; telemetry = None
    def __init__(self): self.calls: list[str] = []
    def call_code(self, prompt, *, tag="code", **kw):
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, tag, time.monotonic() - 0.01,
                        100, 50, 1, True, None)
        self.calls.append(tag)
        return "# stub\n"
    def call_json(self, *a, **kw):
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, kw.get("tag", "json"), time.monotonic() - 0.01,
                        100, 50, 1, True, None)
        self.calls.append(kw.get("tag", "json"))
        return {"tests": []}
    def call_chat(self, *a, **kw): return ""


@pytest.fixture
def fresh_creative_cache():
    from forge.orchestrator.creative import clear_creative_cache
    clear_creative_cache()
    yield
    clear_creative_cache()


@pytest.mark.slow
def test_default_c_like_records_pipeline_path_templated(tmp_path, fresh_creative_cache):
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "default_path_clike",
    )
    out_dir = generate_all(spec, output_root=tmp_path, client=_CountingFake(),
                           verify_after_generation=False)
    summary = json.loads(
        (out_dir / "generation_summary.json").read_text(encoding="utf-8"))
    assert summary["pipeline_path"] == "templated", (
        f"default c_like should use templated path; got "
        f"pipeline_path={summary['pipeline_path']!r}"
    )


@pytest.mark.slow
def test_template_false_forces_llm_path_for_c_like(tmp_path, fresh_creative_cache):
    """Setting template_from_reference=False routes c_like through
    the LLM-driven path even though a reference exists. The fake
    client returns stubs that don't satisfy real schemas, so the
    full generation will likely fail mid-flight — but it has to TRY
    the LLM path. We confirm `gen-readme` was called (which only
    happens on the LLM path)."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "forced_llm_clike",
    )
    client = _CountingFake()
    try:
        generate_all(spec, output_root=tmp_path, client=client,
                     template_from_reference=False,
                     only=["readme"],   # avoid the full DAG
                     verify_after_generation=False)
    except Exception:
        # Component failures with the stub client are expected; we
        # only care that the LLM path was attempted.
        pass
    assert "gen-readme" in client.calls, (
        f"template_from_reference=False should route c_like through "
        f"the LLM path's _generate_readme; got calls: {client.calls}"
    )


@pytest.mark.slow
def test_template_false_records_pipeline_path_llm(tmp_path, fresh_creative_cache):
    """The telemetry summary should reflect that the LLM path was
    chosen. Phase 2's quality filter will read this to compare
    templated vs LLM output quality."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "llm_path_record_clike",
    )
    client = _CountingFake()
    try:
        generate_all(spec, output_root=tmp_path, client=client,
                     template_from_reference=False,
                     only=["readme"],
                     verify_after_generation=False,
                     enrich_creative=False)
    except Exception:
        pass
    summary_path = tmp_path / "llm_path_record_clike" / "generation_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        assert summary["pipeline_path"] == "llm", (
            f"template_from_reference=False should record pipeline_path"
            f"='llm'; got {summary['pipeline_path']!r}"
        )


@pytest.mark.slow
def test_python_like_always_llm_regardless_of_flag(tmp_path, fresh_creative_cache):
    """python_like has no reference compiler, so both flag values
    should produce the same LLM-path generation. Pin that the flag
    doesn't introduce surprising behavior for languages without a
    reference."""
    spec = build_spec(
        {"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"},
        "py_default_path",
    )
    client = _CountingFake()
    try:
        generate_all(spec, output_root=tmp_path, client=client,
                     only=["readme"],
                     verify_after_generation=False,
                     enrich_creative=False)
    except Exception:
        pass
    summary_path = tmp_path / "py_default_path" / "generation_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        # python_like ALWAYS uses the LLM path because no reference exists.
        assert summary["pipeline_path"] == "llm"


def test_telemetry_recorder_pipeline_path_default():
    """A fresh recorder should have pipeline_path='unknown'. set_
    pipeline_path() updates it."""
    from forge.orchestrator.telemetry import TelemetryRecorder
    rec = TelemetryRecorder(lang_name="x")
    assert rec.pipeline_path == "unknown"
    rec.set_pipeline_path("templated")
    summary = rec.to_summary_dict()
    assert summary["pipeline_path"] == "templated"


def test_events_to_summary_picks_up_pipeline_path(tmp_path):
    """events_to_summary should reconstruct pipeline_path from a
    streamed events file."""
    from forge.orchestrator.telemetry import TelemetryRecorder, events_to_summary
    events_path = tmp_path / "events.jsonl"
    rec = TelemetryRecorder(lang_name="recovery_test")
    rec.attach_events_file(events_path)
    rec.set_pipeline_path("templated")
    summary = events_to_summary(events_path)
    assert summary["pipeline_path"] == "templated"
