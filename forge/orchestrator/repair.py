"""Stage 5: Repair Loop.

When verification fails, ask the LLM to rewrite the failing component file.

Heuristics applied:

  1. Cascade-aware ordering: parser failures cause downstream codegen errors,
     so when ANY test reports a parse error we repair `parser` first.
  2. Skip impossible attributions: a `typechecker` attribution is dropped when
     the spec is dynamically typed (no typechecker.py exists).
  3. Treat `missing` canonicals as a tests-component failure, re-run the
     tests generator before retrying anything else.
  4. After all per-component repairs are exhausted with no improvement,
     surface the failure with full context.

Spec limits: 3 attempts per component, 2 distinct components repaired per run.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Optional

from .generator import (
    COMPONENT_FILENAMES,
    _load_prompt,
    _interp,
    _sibling_context,
    _generate_tests,
)
from .llm_client import LLMClient
from .verifier import VerificationReport, verify


MAX_ATTEMPTS_PER_COMPONENT = 3
MAX_COMPONENTS_PER_RUN = 2


def _filename_for(component: str) -> str:
    return COMPONENT_FILENAMES.get(component, f"{component}.py")


def _build_report_blob(report: VerificationReport) -> str:
    parts = []
    failing = [t for t in report.tests if t.status == "fail"]
    if failing:
        parts.append("Failing tests:")
        for t in failing:
            parts.append(f"\n--- {t.name} (stage={t.stage}, attributed={t.failing_component}) ---")
            if t.expected is not None:
                parts.append(f"expected stdout:\n{t.expected}")
            if t.actual is not None:
                parts.append(f"actual stdout:\n{t.actual}")
            if t.stderr:
                parts.append(f"stderr:\n{t.stderr.strip()[-1500:]}")
            if t.returncode is not None:
                parts.append(f"returncode: {t.returncode}")
    if report.missing_canonical:
        parts.append(f"\nMissing canonical tests: {', '.join(report.missing_canonical)}")
    return "\n".join(parts) if parts else "(no actionable details)"


def _pick_component(report: VerificationReport, spec: dict) -> Optional[str]:
    """Decide which component to repair next.

    Priority order:
      1. If any canonical test is missing → 'tests' (regenerate the test pairs).
      2. If any failure is a parse-stage error → 'parser' first (cascades).
      3. Most common failing_component attribution, with these caveats:
         - drop 'typechecker' for dynamic typing
         - drop 'tests' here (we handled it in step 1)
    """
    if report.missing_canonical:
        return "tests"

    fails = [t for t in report.tests if t.status == "fail"]
    if not fails:
        return None

    # Step 2: any parse-stage failure trumps everything
    for t in fails:
        sm = (t.stderr or "").lower()
        if t.stage == "compile" and ("unexpectedinput" in sm or "lark" in sm or "parse" in sm):
            return "parser"

    # Step 3: most common attribution, filtered
    counts = Counter()
    for t in fails:
        if t.failing_component:
            counts[t.failing_component] += 1
    if not counts:
        return None

    typing = spec.get("options", {}).get("typing", "dynamic")
    for component, _ in counts.most_common():
        if component == "typechecker" and typing == "dynamic":
            continue
        if component == "tests":  # already handled above; would loop
            continue
        return component

    return None


def repair_run(lang_dir: str | Path, *, client: Optional[LLMClient] = None) -> VerificationReport:
    """Run verify→repair until pass or limits exhausted. Returns final report."""
    lang_dir = Path(lang_dir).resolve()

    spec_path = lang_dir / "resolved_spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"no resolved_spec.json at {spec_path}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    if client is None:
        client = LLMClient(log_dir=lang_dir / ".forge_log")

    repaired_components: dict[str, int] = {}

    while True:
        report = verify(lang_dir)
        if report.all_passed:
            return report

        component = _pick_component(report, spec)
        if component is None:
            return report
        if component not in repaired_components and len(repaired_components) >= MAX_COMPONENTS_PER_RUN:
            return report
        if repaired_components.get(component, 0) >= MAX_ATTEMPTS_PER_COMPONENT:
            # Don't infinitely retry; if we can pick another component below
            # the limit, the next iteration will catch it. Otherwise we exit.
            other = _pick_alternate(report, spec, exhausted={
                k for k, v in repaired_components.items() if v >= MAX_ATTEMPTS_PER_COMPONENT
            })
            if other is None or len(repaired_components) >= MAX_COMPONENTS_PER_RUN:
                return report
            component = other

        # 'tests' is special: regenerate via the generator's bulk+per-test path.
        if component == "tests":
            try:
                _generate_tests(spec, lang_dir, client)
            except Exception:
                # Generation itself failed; record attempt + bail.
                repaired_components[component] = repaired_components.get(component, 0) + 1
                continue
            repaired_components[component] = repaired_components.get(component, 0) + 1
            continue

        filename = _filename_for(component)
        target = lang_dir / filename
        current = target.read_text(encoding="utf-8") if target.exists() else "(file missing)"
        lang = "python" if filename.endswith(".py") else "markdown"

        prompt = _interp(
            _load_prompt("repair"),
            spec,
            COMPONENT=component,
            FILENAME=filename,
            LANG=lang,
            CURRENT_SOURCE=current,
            FAILURE_REPORT=_build_report_blob(report),
        ) + _sibling_context(component, lang_dir)
        attempt_n = repaired_components.get(component, 0) + 1
        new_source = client.call_code(prompt, tag=f"repair-{component}-{attempt_n}")
        target.write_text(new_source, encoding="utf-8")
        repaired_components[component] = attempt_n


def _pick_alternate(report: VerificationReport, spec: dict, exhausted: set[str]) -> Optional[str]:
    counts = Counter()
    for t in report.tests:
        if t.status == "fail" and t.failing_component:
            counts[t.failing_component] += 1
    typing = spec.get("options", {}).get("typing", "dynamic")
    for component, _ in counts.most_common():
        if component in exhausted:
            continue
        if component == "typechecker" and typing == "dynamic":
            continue
        return component
    return None
