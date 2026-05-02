"""End-to-end acceptance test.

Generates each of the 8 option combinations and verifies all 8 canonical tests
pass for each. Runs only when `ANTHROPIC_API_KEY` is set — these tests cost
real API calls and take minutes, so they're skipped by default in CI workflows
that don't have credentials.

To run locally:
    export ANTHROPIC_API_KEY=...
    pytest tests/test_end_to_end.py -k <combo_substring>
"""
from __future__ import annotations

import itertools
import os
import shutil
from pathlib import Path

import pytest

from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.llm_client import LLMClient
from forge.orchestrator.resolver import resolve
from forge.orchestrator.generator import generate_all
from forge.orchestrator.repair import repair_run
from forge.orchestrator.verifier import verify


HAS_KEY = bool(os.environ.get("ANTHROPIC_API_KEY"))


pytestmark = pytest.mark.skipif(
    not HAS_KEY,
    reason="ANTHROPIC_API_KEY not set — end-to-end tests require live API access",
)


COMBOS = list(itertools.product(
    ["c_like", "python_like"],
    ["static", "dynamic"],
    ["host_gc", "refcount"],
))


def _combo_id(combo):
    return f"{combo[0]}-{combo[1]}-{combo[2]}"


@pytest.mark.parametrize("syntax,typing,memory", COMBOS, ids=_combo_id)
def test_generate_combo(syntax, typing, memory, tmp_path):
    opts = {"syntax": syntax, "typing": typing, "memory": memory}
    name = f"e2e_{syntax}_{typing}_{memory}"
    output_root = tmp_path / "generated"

    base = build_spec(opts, name)
    client = LLMClient(log_dir=output_root / name / ".forge_log")
    resolved = resolve(base, client=client)
    lang_dir = generate_all(resolved, output_root=output_root, client=client)

    report = verify(lang_dir)
    if not report.all_passed:
        report = repair_run(lang_dir, client=client)

    assert report.all_passed, "\n" + report.summary()
