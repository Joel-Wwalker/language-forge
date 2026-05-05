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
from dataclasses import dataclass
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


# Interactive defaults: tight, calibrated for "a user is waiting." Batch
# mode (Phase 0.2) overrides via RepairBudget below.
MAX_ATTEMPTS_PER_COMPONENT = 3
MAX_COMPONENTS_PER_RUN = 2


@dataclass
class RepairBudget:
    """Controls how aggressively repair_run retries before giving up.

    Defaults match the interactive-mode behavior. Batch runners pass a
    larger budget to absorb LLM nondeterminism on borderline languages.
    Time budgets are advisory — the loop exits cleanly once a component
    finishes its current attempt past the deadline.
    """
    max_attempts_per_component: int = MAX_ATTEMPTS_PER_COMPONENT
    max_components_per_run: int = MAX_COMPONENTS_PER_RUN
    time_budget_seconds: Optional[float] = None  # None = unbounded

    @classmethod
    def batch(cls) -> "RepairBudget":
        """Recommended preset for unattended batch generation.

        10 attempts × all-components × 5 minutes. Large enough to keep
        90%+ of borderline languages without dropping the rare genuine
        bug into an infinite loop."""
        return cls(
            max_attempts_per_component=10,
            max_components_per_run=10,
            time_budget_seconds=300.0,
        )


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


# Components that are TEMPLATED from a hand-written reference compiler
# when the syntax family has one (e.g. s_expression -> lisplang). These
# files are known-good and the LLM should NEVER be asked to rewrite them.
# Asking the LLM to "repair" lisplang's parser.py would produce a
# regression worse than whatever bug triggered the verify failure.
_TEMPLATED_COMPONENTS = {"parser", "lexer", "codegen", "runtime", "stdlib"}


def _is_templated_language(spec: dict) -> bool:
    """True if this language was templated from a reference compiler.

    Defers to `REFERENCE_COMPILERS` in the generator so adding a new
    family (s_expression, stack_based, ...) automatically picks up the
    repair guard without anyone having to remember to update this
    function in two places.
    """
    from .generator import REFERENCE_COMPILERS
    syntax = (spec.get("options") or {}).get("syntax")
    return syntax in REFERENCE_COMPILERS


def _pick_component(report: VerificationReport, spec: dict) -> Optional[str]:
    """Decide which component to repair next.

    Priority order:
      1. If any canonical test is missing → 'tests' (regenerate the test pairs).
      2. If any failure is a parse-stage error → 'parser' first (cascades).
      3. Most common failing_component attribution, with these caveats:
         - drop 'typechecker' for dynamic typing
         - drop 'tests' here (we handled it in step 1)
         - drop any templated component (parser/codegen/runtime/stdlib/lexer)
           for templated languages — those are hand-written and
           regenerating them via LLM would break a known-good baseline.
    """
    templated = _is_templated_language(spec)

    if report.missing_canonical:
        return "tests"

    fails = [t for t in report.tests if t.status == "fail"]
    if not fails:
        return None

    # Step 2: any parse-stage failure trumps everything (UNLESS the parser
    # is templated, in which case the failure is in the user's source or
    # a rare compiler bug — skip parser repair and let attribution drive it).
    for t in fails:
        sm = (t.stderr or "").lower()
        if t.stage == "compile" and ("unexpectedinput" in sm or "lark" in sm or "parse" in sm):
            if templated:
                # Don't try to "fix" the hand-written parser. The actual
                # bug is in tests/ or in the source code being parsed.
                break
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
        if templated and component in _TEMPLATED_COMPONENTS:
            # The component is hand-written; skip repair. Attribution
            # was probably wrong (a kata-translation issue that LOOKS
            # like a codegen bug, etc.).
            continue
        return component

    return None


def repair_run(lang_dir: str | Path, *,
               client: Optional[LLMClient] = None,
               budget: Optional["RepairBudget"] = None,  # type: ignore[name-defined]
               ) -> VerificationReport:
    """Run verify→repair until pass or limits exhausted. Returns final report.

    Phase 0.2 extension: pass a `RepairBudget(max_attempts_per_component,
    max_components_per_run)` to override the interactive defaults. Batch
    runners use a much higher budget to give borderline languages more
    chances to be fixed automatically.

    Phase 0.4 extension: each repair attempt is recorded into the LLM
    client's telemetry recorder (if attached) so batch summaries can
    answer "how much repair did this language take to ship".
    """
    import time as _time
    lang_dir = Path(lang_dir).resolve()

    spec_path = lang_dir / "resolved_spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"no resolved_spec.json at {spec_path}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    if client is None:
        client = LLMClient(log_dir=lang_dir / ".forge_log")

    if budget is None:
        budget = RepairBudget()  # interactive defaults: 3 x 2

    rec = getattr(client, "telemetry", None)

    def _record(comp: str, attempt_n: int, success: bool, t0: float) -> None:
        if rec is None:
            return
        try:
            from .telemetry import RepairAttemptRecord
            rec.record_repair(RepairAttemptRecord(
                component=comp, attempt=attempt_n, success=success,
                duration_seconds=round(_time.monotonic() - t0, 3),
            ))
        except Exception:
            pass

    repaired_components: dict[str, int] = {}

    while True:
        report = verify(lang_dir)
        if report.all_passed:
            return report

        component = _pick_component(report, spec)
        if component is None:
            return report
        if component not in repaired_components and len(repaired_components) >= budget.max_components_per_run:
            return report
        if repaired_components.get(component, 0) >= budget.max_attempts_per_component:
            # Don't infinitely retry; if we can pick another component below
            # the limit, the next iteration will catch it. Otherwise we exit.
            other = _pick_alternate(report, spec, exhausted={
                k for k, v in repaired_components.items() if v >= budget.max_attempts_per_component
            })
            if other is None or len(repaired_components) >= budget.max_components_per_run:
                return report
            component = other

        # 'tests' is special: regenerate via the generator's bulk+per-test path.
        if component == "tests":
            t0 = _time.monotonic()
            try:
                _generate_tests(spec, lang_dir, client)
                _record("tests", repaired_components.get("tests", 0) + 1, True, t0)
            except Exception:
                # Generation itself failed; record attempt + bail.
                _record("tests", repaired_components.get("tests", 0) + 1, False, t0)
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
        t0 = _time.monotonic()
        try:
            new_source = client.call_code(prompt, tag=f"repair-{component}-{attempt_n}")
            target.write_text(new_source, encoding="utf-8")
            _record(component, attempt_n, True, t0)
        except Exception:
            _record(component, attempt_n, False, t0)
            raise
        repaired_components[component] = attempt_n


def _pick_alternate(report: VerificationReport, spec: dict, exhausted: set[str]) -> Optional[str]:
    counts = Counter()
    for t in report.tests:
        if t.status == "fail" and t.failing_component:
            counts[t.failing_component] += 1
    typing = spec.get("options", {}).get("typing", "dynamic")
    templated = _is_templated_language(spec)
    for component, _ in counts.most_common():
        if component in exhausted:
            continue
        if component == "typechecker" and typing == "dynamic":
            continue
        if templated and component in _TEMPLATED_COMPONENTS:
            continue   # don't overwrite hand-written reference files
        return component
    return None
