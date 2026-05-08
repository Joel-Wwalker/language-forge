"""Phase 2 Stage A: read-only quality scorer for generated languages.

# WHAT THIS DOES

Given a directory containing one Phase-1.5-generated language, score it
across four quality dimensions and produce a `QualityReport`. The
report is JSON-serializable so a batch's worth of reports can be
written to disk for later inspection.

The scorer is **read-only**. It does not modify, delete, or write
anything inside the language directory. Its only effect is producing
the report (returned in-memory; the CLI writes it to a separate output
path).

# THE FOUR DIMENSIONS

Per `phase2-instructions.md`:

  1. **Correctness (binary, must-pass)** — all 8 canonical tests pass,
     kata pack runs cleanly, REPL launches, compile.py works. A
     language failing any of these gets rejected outright.

  2. **Distinctiveness (graded 0-1)** — how meaningfully different
     this language is from the family's defaults. Three sub-axes:
     surface (keyword overrides vs canonical), persona (creative-LLM
     output presence + length), customization variety (number of
     customization axes exercised).

  3. **Coherence (graded 0-1)** — does the language read like a
     coherent design? Heuristics: keyword overrides are unique (no
     two roles map to the same spelling), README intro mentions the
     language name, intro length is reasonable, stdlib renames (if
     any) follow a single naming convention.

  4. **Completeness (graded 0-1)** — checklist of expected artifacts:
     parser/codegen/runtime/stdlib/compile.py, tests/, README.md,
     LANGUAGE.md, resolved_spec.json, generation_summary.json,
     repl.html, theme.css.

# THE OVERALL VERDICT

`overall_passed` is True iff:
  - correctness == "pass"
  - completeness.score >= COMPLETENESS_THRESHOLD (default 0.8)

Distinctiveness and coherence are NEVER auto-rejected — low scores
flag for human review (Phase 3) but don't reject. The instructions are
explicit: "automation can do well" things gate; subjective things
surface to curation.

When `overall_passed` is False, `rejection_reason` carries a
human-readable explanation a Phase-3 curator can read and either agree
with or override.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# Thresholds. Pulled to module level so tests can import them and
# verify behavior at the boundary.
COMPLETENESS_THRESHOLD = 0.8
DISTINCTIVENESS_FLAG_THRESHOLD = 0.1
README_MIN_WORDS = 50
LANGUAGE_MD_MIN_WORDS = 100


# Files that count toward completeness. Each entry is (relpath, weight).
# Weights sum to 1.0 so the completeness score is a clean fraction of
# the maximum possible.
_REQUIRED_ARTIFACTS: list[tuple[str, float]] = [
    ("parser.py", 0.10),
    ("codegen.py", 0.10),
    ("runtime.py", 0.10),
    ("stdlib.py", 0.05),
    ("compile.py", 0.05),
    ("README.md", 0.10),
    ("LANGUAGE.md", 0.10),
    ("resolved_spec.json", 0.10),
    ("generation_summary.json", 0.10),
    ("tests", 0.10),          # directory; checked separately
    ("repl.html", 0.05),
    ("theme.css", 0.05),
]
assert abs(sum(w for _, w in _REQUIRED_ARTIFACTS) - 1.0) < 1e-9


# Customization axes that count toward distinctiveness's "variety"
# sub-score. Each axis a spec exercises adds 1/N where N is the axis
# count, so a fully-customized spec scores 1.0 on this sub-axis.
_CUSTOMIZATION_AXES = (
    "persona", "era", "theme", "phrasebook",
    "feature_bans", "keyword_overrides", "hostile_constraints",
)


# Canonical c_like / s_expression / stack_based keyword counts. Used
# for surface-distinctiveness ratios. These come from the
# `KEYWORD_ROLES_*` tuples in `forge/orchestrator/substitution.py`.
# Imported lazily so this module remains importable without forge's
# orchestrator being on the path (e.g., when the scorer runs in a
# Phase 3 UI context).
def _family_role_count(family: str) -> int:
    try:
        from forge.orchestrator.substitution import (
            KEYWORD_ROLES_C_LIKE,
            KEYWORD_ROLES_STACK_BASED,
            KEYWORD_ROLES_S_EXPRESSION,
        )
    except Exception:
        # Fallback — rough estimates from the audited role sets.
        sizes = {"c_like": 9, "stack_based": 15, "s_expression": 5}
        return sizes.get(family, 9)
    return {
        "c_like":       len(KEYWORD_ROLES_C_LIKE),
        "stack_based":  len(KEYWORD_ROLES_STACK_BASED),
        "s_expression": len(KEYWORD_ROLES_S_EXPRESSION),
    }.get(family, 9)


# ---------------------------------------------------------------------------
# Report dataclasses (JSON-serializable)
# ---------------------------------------------------------------------------

@dataclass
class CorrectnessResult:
    """Binary: pass or fail. Reason populated when failing."""
    passed: bool
    canonical_tests: dict           # {passed, total, pass_rate, source}
    kata_pack: Optional[dict]       # smoke's kata dict, or None
    repl: dict                      # {repl_html_ok, compile_exit_code, launches}
    failures: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)


@dataclass
class DistinctivenessResult:
    score: float                    # 0.0 to 1.0
    surface: float                  # keyword-override ratio
    persona: float                  # creative-content presence + length
    variety: float                  # customization-axis count / total axes
    notes: list[str] = field(default_factory=list)


@dataclass
class CoherenceResult:
    score: float                    # 0.0 to 1.0
    overrides_unique: bool          # no two roles map to same spelling
    readme_mentions_name: bool
    readme_length_ok: bool
    stdlib_naming_consistent: bool
    notes: list[str] = field(default_factory=list)


@dataclass
class CompletenessResult:
    score: float                    # weighted fraction of artifacts present
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


@dataclass
class QualityReport:
    """Top-level scorer output. JSON-serializable via dataclasses.asdict."""
    slot_id: str
    lang_dir: str
    family: str                     # 'c_like' | 's_expression' | 'stack_based' | 'unknown'
    pipeline_path: str              # 'templated' | 'llm' | 'unknown'
    correctness: CorrectnessResult
    distinctiveness: DistinctivenessResult
    coherence: CoherenceResult
    completeness: CompletenessResult
    overall_passed: bool
    rejection_reason: Optional[str]
    scored_at: str
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Per-dimension scorers
# ---------------------------------------------------------------------------

def _score_correctness(lang_dir: Path) -> CorrectnessResult:
    """Run the existing smoke_test() and adapt its result. Smoke is
    already the source-of-truth for "did this generation produce a
    working language?" — Phase 2 should not invent a parallel one."""
    try:
        from forge.catalog.smoke_test import smoke_test
    except Exception as e:
        # Defensive: if smoke_test can't be imported, treat as failure
        # rather than silently passing.
        return CorrectnessResult(
            passed=False,
            canonical_tests={"passed": 0, "total": 0, "pass_rate": 0.0,
                             "source": "smoke_import_failed"},
            kata_pack=None,
            repl={"repl_html_ok": False, "compile_exit_code": None,
                  "launches": False},
            failures=[f"correctness: smoke_test import failed: "
                      f"{type(e).__name__}: {e}"],
            skips=[],
        )

    res = smoke_test(lang_dir)
    return CorrectnessResult(
        passed=bool(res.passed),
        canonical_tests=dict(res.canonical),
        kata_pack=dict(res.kata) if res.kata else None,
        repl=dict(res.repl),
        failures=list(res.failures),
        skips=list(res.skips),
    )


def _score_distinctiveness(spec: dict, family: str) -> DistinctivenessResult:
    """Three sub-axes: surface (keyword overrides), persona (creative
    output), variety (customization axes exercised)."""
    notes: list[str] = []

    # -- Surface: how many keyword roles were overridden vs canonical?
    cust = spec.get("customization") or {}
    overrides = dict(cust.get("keyword_overrides") or {})
    family_role_count = _family_role_count(family)
    # Count overrides that are actual substitutions (new != canon).
    real_overrides = sum(
        1 for canon, new in overrides.items()
        if canon != new and isinstance(new, str) and new.strip()
    )
    surface = min(1.0, real_overrides / max(1, family_role_count))
    if real_overrides == 0:
        notes.append("surface: no keyword overrides — language reads as canonical for its family")
    elif real_overrides < family_role_count // 2:
        notes.append(
            f"surface: {real_overrides}/{family_role_count} role(s) overridden"
        )

    # -- Persona: creative-LLM output presence + substantive length
    creative = spec.get("creative")
    readme_intro = ""
    if isinstance(creative, dict):
        readme_intro = creative.get("readme_intro") or ""
    elif isinstance(creative, str):
        readme_intro = creative
    origin_story = spec.get("origin_story") or ""

    intro_words = len(readme_intro.split())
    story_words = len(origin_story.split())
    # Crude but defensible: a healthy creative output has both an
    # origin_story (~50+ words) and a readme_intro (~80+ words). We
    # cap each contribution at 1.0/2 so persona maxes at 1.0.
    persona_intro = min(0.5, intro_words / 160.0)  # 80 words -> 0.5
    persona_story = min(0.5, story_words / 100.0)  # 50 words -> 0.5
    persona = persona_intro + persona_story
    if intro_words < 30 and story_words < 20:
        notes.append("persona: creative content is sparse (no substantive intro or origin_story)")

    # -- Variety: how many customization axes are exercised?
    exercised = 0
    for axis in _CUSTOMIZATION_AXES:
        v = cust.get(axis)
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, tuple, dict)) and len(v) == 0:
            continue
        exercised += 1
    variety = min(1.0, exercised / len(_CUSTOMIZATION_AXES))
    if exercised == 0:
        notes.append("variety: no customization axes exercised — pure baseline language")

    # Aggregate. Equal weight on the three sub-axes, capped at 1.0.
    score = round((surface + persona + variety) / 3.0, 3)
    return DistinctivenessResult(
        score=score,
        surface=round(surface, 3),
        persona=round(persona, 3),
        variety=round(variety, 3),
        notes=notes,
    )


def _score_coherence(spec: dict, lang_dir: Path) -> CoherenceResult:
    """Heuristic coherence checks. Each heuristic is binary; the score
    is the fraction that passed."""
    notes: list[str] = []
    cust = spec.get("customization") or {}
    overrides = dict(cust.get("keyword_overrides") or {})

    # -- Heuristic 1: keyword overrides are unique (no two canonical
    # roles map to the same target spelling). Duplicate targets indicate
    # the resolver got confused and reused a word for two roles.
    new_values = [v for v in overrides.values()
                  if isinstance(v, str) and v.strip()]
    overrides_unique = len(new_values) == len(set(new_values))
    if not overrides_unique:
        # Find the duplicates for the note.
        seen: dict[str, list[str]] = {}
        for canon, new in overrides.items():
            if isinstance(new, str) and new.strip():
                seen.setdefault(new, []).append(canon)
        dups = {v: ks for v, ks in seen.items() if len(ks) > 1}
        notes.append(f"overrides: collisions: {dups}")

    # -- Heuristic 2: README intro mentions the language name
    readme_path = lang_dir / "README.md"
    readme_text = ""
    if readme_path.exists():
        try:
            readme_text = readme_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            readme_text = ""
    name_candidates = [
        spec.get("display_name") or "",
        spec.get("lang_name") or "",
    ]
    name_candidates = [n for n in name_candidates if n]
    readme_mentions_name = any(
        n.lower() in readme_text.lower() for n in name_candidates
    ) if name_candidates else False
    if not readme_mentions_name and name_candidates:
        notes.append(
            f"readme: doesn't mention any of {name_candidates}"
        )

    # -- Heuristic 3: README is non-trivial in length
    readme_words = len(readme_text.split())
    readme_length_ok = readme_words >= README_MIN_WORDS
    if not readme_length_ok:
        notes.append(
            f"readme: only {readme_words} words (threshold {README_MIN_WORDS})"
        )

    # -- Heuristic 4: stdlib naming convention is consistent (lazy
    # heuristic: if stdlib has renamed entries, all renamed names
    # share a casing convention).
    stdlib_naming_consistent = True
    stdlib_block = spec.get("stdlib")
    if isinstance(stdlib_block, dict):
        renamed = stdlib_block.get("renames") if "renames" in stdlib_block else None
        if isinstance(renamed, dict) and renamed:
            casing_styles = {_casing_of(name) for name in renamed.values()
                             if isinstance(name, str) and name.strip()}
            casing_styles.discard("unknown")
            if len(casing_styles) > 1:
                stdlib_naming_consistent = False
                notes.append(
                    f"stdlib: mixed naming styles in renames: {casing_styles}"
                )

    heuristics = [
        overrides_unique,
        readme_mentions_name,
        readme_length_ok,
        stdlib_naming_consistent,
    ]
    score = round(sum(1 for h in heuristics if h) / len(heuristics), 3)
    return CoherenceResult(
        score=score,
        overrides_unique=overrides_unique,
        readme_mentions_name=readme_mentions_name,
        readme_length_ok=readme_length_ok,
        stdlib_naming_consistent=stdlib_naming_consistent,
        notes=notes,
    )


def _casing_of(name: str) -> str:
    """Classify an identifier's casing style. Used for stdlib-rename
    consistency checks."""
    if not name:
        return "unknown"
    if "_" in name and name == name.lower():
        return "snake_case"
    if "-" in name:
        return "kebab-case"
    # Order matters: UPPERCASE is a subset of "starts with upper +
    # has upper rest" (which is also PascalCase). Check the
    # all-uppercase case first so it doesn't fall through to PascalCase.
    if name == name.upper() and any(c.isalpha() for c in name):
        return "UPPERCASE"
    if name == name.lower() and any(c.isalpha() for c in name):
        return "lowercase"
    if name[0].isupper() and any(c.isupper() for c in name[1:]):
        return "PascalCase"
    if name[0].islower() and any(c.isupper() for c in name):
        return "camelCase"
    return "unknown"


def _score_completeness(lang_dir: Path) -> CompletenessResult:
    """Weighted-sum check of expected artifacts. Tests directory is
    handled specially (must contain ≥8 .{ext} files OR an explicit
    canonical-test sentinel)."""
    present: list[str] = []
    missing: list[str] = []
    score = 0.0
    for relpath, weight in _REQUIRED_ARTIFACTS:
        target = lang_dir / relpath
        if relpath == "tests":
            # Must exist as a directory with content.
            if target.exists() and target.is_dir():
                # Count test source files (excluding .out.py and .txt expected).
                test_files = [
                    p for p in target.iterdir()
                    if p.is_file() and not p.name.endswith(".out.py")
                    and not p.name.endswith(".expected_output.txt")
                ]
                if len(test_files) >= 8:
                    present.append(relpath)
                    score += weight
                else:
                    missing.append(f"{relpath} (only {len(test_files)} files; "
                                   f"expected >=8)")
            else:
                missing.append(relpath)
        elif relpath in ("README.md", "LANGUAGE.md"):
            # Must exist AND be non-trivial.
            if not target.exists():
                missing.append(relpath)
            else:
                try:
                    text = target.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    text = ""
                threshold = (README_MIN_WORDS if relpath == "README.md"
                             else LANGUAGE_MD_MIN_WORDS)
                if len(text.split()) >= threshold:
                    present.append(relpath)
                    score += weight
                else:
                    missing.append(f"{relpath} (only "
                                   f"{len(text.split())} words; "
                                   f"threshold {threshold})")
        else:
            if target.exists():
                present.append(relpath)
                score += weight
            else:
                missing.append(relpath)
    return CompletenessResult(
        score=round(score, 3),
        present=present,
        missing=missing,
    )


# ---------------------------------------------------------------------------
# Public entry: score a single language
# ---------------------------------------------------------------------------

def score_language(lang_dir: str | Path, *,
                   family_baselines: Optional[dict] = None) -> QualityReport:
    """Score a generated language across all four quality dimensions.

    `family_baselines` is reserved for future per-family normalization
    (e.g., shared README templates that should NOT count as
    distinctiveness). Phase 2's first pass doesn't use it; the
    parameter is plumbed for Phase 3 / 4 extension.
    """
    t0 = time.monotonic()
    # Resolve to an absolute path. smoke_test()'s `_check_repl` uses
    # `cwd=str(lang_dir)` plus an absolute compile.py path; if lang_dir
    # was relative, the OS resolves compile.py relative to cwd a second
    # time and the path doubles ("...\slot_001\slot_001\compile.py").
    # Forcing absolute here is the simplest fix.
    lang_dir = Path(lang_dir).resolve()

    spec_path = lang_dir / "resolved_spec.json"
    spec: dict = {}
    if spec_path.exists():
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except Exception:
            spec = {}

    summary_path = lang_dir / "generation_summary.json"
    summary: dict = {}
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            summary = {}

    family = (spec.get("options") or {}).get("syntax") or "unknown"
    pipeline_path = summary.get("pipeline_path") or "unknown"
    slot_id = spec.get("lang_name") or lang_dir.name

    correctness = _score_correctness(lang_dir)
    distinctiveness = _score_distinctiveness(spec, family)
    coherence = _score_coherence(spec, lang_dir)
    completeness = _score_completeness(lang_dir)

    # Overall verdict.
    overall_passed = (
        correctness.passed
        and completeness.score >= COMPLETENESS_THRESHOLD
    )
    rejection_reason: Optional[str] = None
    if not overall_passed:
        bits = []
        if not correctness.passed:
            failed_msg = "; ".join(correctness.failures[:3]) or "smoke_test failed"
            bits.append(f"correctness FAIL: {failed_msg}")
        if completeness.score < COMPLETENESS_THRESHOLD:
            miss_preview = ", ".join(completeness.missing[:5])
            bits.append(f"completeness {completeness.score:.2f} < "
                        f"{COMPLETENESS_THRESHOLD} (missing: {miss_preview})")
        rejection_reason = "; ".join(bits)

    return QualityReport(
        slot_id=slot_id,
        lang_dir=str(lang_dir),
        family=family,
        pipeline_path=pipeline_path,
        correctness=correctness,
        distinctiveness=distinctiveness,
        coherence=coherence,
        completeness=completeness,
        overall_passed=overall_passed,
        rejection_reason=rejection_reason,
        scored_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        duration_seconds=round(time.monotonic() - t0, 3),
    )


# ---------------------------------------------------------------------------
# Batch scorer
# ---------------------------------------------------------------------------

def score_batch(input_dir: str | Path) -> list[QualityReport]:
    """Score every language directory immediately under `input_dir`.

    A language directory is identified by the presence of
    `resolved_spec.json`. Other entries (`state.json`, `batch_summary.json`,
    file leftovers) are skipped silently.

    Returns reports in the order encountered (typically slot_id order
    if the batch was named that way)."""
    input_dir = Path(input_dir)
    if not input_dir.exists():
        raise FileNotFoundError(f"input_dir does not exist: {input_dir}")
    reports: list[QualityReport] = []
    for entry in sorted(input_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "resolved_spec.json").exists():
            continue
        reports.append(score_language(entry))
    return reports


def report_to_dict(report: QualityReport) -> dict:
    """JSON-safe dict form of a report. Equivalent to
    dataclasses.asdict but kept as a public helper for callers that
    want to be explicit about serialization."""
    return asdict(report)


def write_batch_report(reports: list[QualityReport], output_path: Path) -> None:
    """Write a list of reports to a single JSON file using the
    atomic-write discipline established in Phase 1.5 (tmp + os.replace)
    so a crashed process can't leave partial JSON."""
    import os as _os
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scored_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "report_count": len(reports),
        "reports": [report_to_dict(r) for r in reports],
        "aggregate": _aggregate(reports),
    }
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _os.replace(tmp, output_path)


def _aggregate(reports: list[QualityReport]) -> dict:
    """Top-level rollup numbers for the report file."""
    total = len(reports)
    if total == 0:
        return {"total": 0}
    passed = sum(1 for r in reports if r.overall_passed)
    correctness_passed = sum(1 for r in reports if r.correctness.passed)
    by_family: dict[str, int] = {}
    for r in reports:
        by_family[r.family] = by_family.get(r.family, 0) + 1
    return {
        "total": total,
        "overall_passed": passed,
        "overall_failed": total - passed,
        "correctness_passed": correctness_passed,
        "by_family": by_family,
        "mean_distinctiveness": round(
            sum(r.distinctiveness.score for r in reports) / total, 3
        ),
        "mean_coherence": round(
            sum(r.coherence.score for r in reports) / total, 3
        ),
        "mean_completeness": round(
            sum(r.completeness.score for r in reports) / total, 3
        ),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import sys
    parser = argparse.ArgumentParser(
        prog="python -m forge.catalog.quality",
        description="Score generated languages across quality dimensions. "
                    "Phase 2 Stage A.",
    )
    parser.add_argument(
        "--input", required=True, type=Path,
        help="directory containing one or more generated languages "
             "(each as a subdirectory with resolved_spec.json)",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="JSON file to write the batch report into (atomic write)",
    )
    args = parser.parse_args(argv)

    if not args.input.exists():
        print(f"ERROR: input directory does not exist: {args.input}",
              file=sys.stderr)
        return 2

    print(f"scoring batch in {args.input}")
    reports = score_batch(args.input)
    if not reports:
        print(f"WARNING: no language directories found in {args.input}",
              file=sys.stderr)
    write_batch_report(reports, args.output)
    print(f"wrote {len(reports)} report(s) to {args.output}")

    agg = _aggregate(reports)
    if agg.get("total", 0) > 0:
        print(f"  overall_passed: {agg['overall_passed']}/{agg['total']}")
        print(f"  correctness_passed: {agg['correctness_passed']}/{agg['total']}")
        print(f"  by_family: {agg['by_family']}")
        print(f"  mean distinctiveness: {agg['mean_distinctiveness']:.2f}")
        print(f"  mean coherence: {agg['mean_coherence']:.2f}")
        print(f"  mean completeness: {agg['mean_completeness']:.2f}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
