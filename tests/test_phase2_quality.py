"""Phase 2 Stage A — quality scorer tests.

Pins the contract for `forge.catalog.quality.score_language`:

  - Perfect language fixture scores high across the board.
  - Broken language (canonical tests failing) gets correctness=fail
    and rejection_reason names what failed.
  - Vanilla language (no customization) gets distinctiveness near 0.
  - Highly customized language gets distinctiveness near 1.
  - Missing files give completeness < 1 with the right files in the
    missing list.
  - The scorer is idempotent — same input, same report (modulo
    timestamps).

Tests use small synthetic fixture directories built per-test rather
than depending on a live batch run. The slow integration tests
against `generated/toylang/` are kept separate so the unit suite
runs fast (<5s).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from forge.catalog.quality import (
    CompletenessResult,
    CorrectnessResult,
    CoherenceResult,
    DistinctivenessResult,
    QualityReport,
    COMPLETENESS_THRESHOLD,
    DISTINCTIVENESS_FLAG_THRESHOLD,
    score_language,
    score_batch,
    write_batch_report,
    report_to_dict,
    _aggregate,
    _casing_of,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

_PERFECT_README = (
    "# canary_test\n\n"
    "canary_test is a small c_like language used to validate the "
    "Phase 2 quality scorer. It supports basic arithmetic, string "
    "manipulation, list and dictionary operations, conditional "
    "branching with if/else, and while-loop iteration. Variables are "
    "declared with var, functions with func, and values are returned "
    "with return. The language transpiles to Python so memory "
    "management is handled automatically. It includes a small standard "
    "library covering print, len, get, set, push, pop, range, str, "
    "int, and float. The test suite covers eight canonical programs.\n"
)
_PERFECT_LANGUAGE_MD = "# canary_test reference\n\n" + (
    "Standard variable declaration uses `var name = value;`. "
    "Functions are defined with `func name(params) { body }`. "
    "Conditional branching follows the c_like idiom: if (cond) "
    "{ ... } else { ... }. The while loop iterates until its "
    "condition becomes false. Comments are // line and /* block */. "
    "Strings use double quotes only. Booleans are true and false; "
    "the absent value is null. The standard library exposes print "
    "for output and len, get, set, push, pop, range, has for "
    "container manipulation. Integers and floats are decimal-only. "
    "Comparison operators include ==, !=, <, >, <=, >=. Logical "
    "operators are &&, ||, !. Arithmetic is +, -, *, /, %. The "
    "language is dynamically typed and uses host garbage collection.\n"
) * 2  # double for word count safety


def _make_perfect_lang(lang_dir: Path, *,
                       customization: Optional[dict] = None,
                       lang_name: str = "canary_test") -> Path:
    """Build a synthetic 'perfect' language directory with all
    expected artifacts populated."""
    lang_dir.mkdir(parents=True, exist_ok=True)
    cust = customization or {
        "persona": None, "era": None, "theme": None,
        "phrasebook": None, "feature_bans": [],
    }
    spec = {
        "lang_name": lang_name,
        "display_name": lang_name,
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": cust,
        "creative": {
            "readme_intro": (
                "canary_test is a clean baseline c_like language for "
                "validating the Phase 2 quality scorer. It uses standard "
                "syntax conventions familiar to any C-family developer "
                "and ships with a small standard library focused on "
                "common collection and I/O operations. The implementation "
                "transpiles to Python and inherits its memory model and "
                "host runtime. Use it as a starting point for kata work "
                "or as a reference when building variant languages."
            ),
        },
        "origin_story": (
            "canary_test was built by the Phase 2 test suite to validate "
            "that the quality scorer recognizes a healthy generation. "
            "It carries no customization and exhibits the family's "
            "canonical defaults. The story isn't elaborate; the language "
            "isn't elaborate. That's the point."
        ),
        "comment_syntax": {"line": "//", "block_open": "/*", "block_close": "*/"},
        "file_extension": ".can",
        "statement_terminator": ";",
    }
    (lang_dir / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8"
    )
    (lang_dir / "generation_summary.json").write_text(
        json.dumps({
            "lang_name": lang_name,
            "canonical_tests": {"passed": 8, "total": 8, "pass_rate": 1.0},
            "kata_pack": None,
            "pipeline_path": "templated",
            "llm": {"total_calls": 2, "total_input_tokens": 0,
                    "total_output_tokens": 0},
            "started_at": "2026-05-08T12:00:00Z",
            "wall_clock_seconds": 3.1,
        }, indent=2), encoding="utf-8"
    )
    # Component files. We only check existence (and size for README/
    # LANGUAGE.md), so a stub `pass` is enough for source files.
    for fname in ("parser.py", "codegen.py", "runtime.py",
                  "stdlib.py", "compile.py"):
        (lang_dir / fname).write_text("pass\n", encoding="utf-8")
    (lang_dir / "README.md").write_text(_PERFECT_README, encoding="utf-8")
    (lang_dir / "LANGUAGE.md").write_text(_PERFECT_LANGUAGE_MD, encoding="utf-8")
    (lang_dir / "repl.html").write_text("<html>pyodide stub</html>",
                                        encoding="utf-8")
    (lang_dir / "theme.css").write_text("body { color: black; }",
                                        encoding="utf-8")
    tests_dir = lang_dir / "tests"
    tests_dir.mkdir(exist_ok=True)
    for name in ("hello_world", "arithmetic", "variables", "conditionals",
                 "loops", "functions", "closures", "strings"):
        (tests_dir / f"{name}.can").write_text(f"# {name}\n", encoding="utf-8")
        (tests_dir / f"{name}.expected_output.txt").write_text(
            f"{name}\n", encoding="utf-8"
        )
    return lang_dir


def _stub_smoke_passing():
    """A `smoke_test` replacement that always passes, used when the
    fixture's component files are stubs (not real compilers) so the
    scorer's correctness check doesn't try to run them."""
    from forge.catalog.smoke_test import SmokeResult

    def fake(lang_dir, *, force_reverify=False):
        return SmokeResult(
            passed=True,
            canonical={"passed": 8, "total": 8, "pass_rate": 1.0,
                       "source": "fake_passing"},
            kata={"passed": 0, "total": 0, "pass_rate": 0.0,
                  "pack_key": "classics"},
            repl={"repl_html_ok": True, "compile_exit_code": 0,
                  "launches": True},
            failures=[], skips=[], duration_seconds=0.01,
        )
    return patch("forge.catalog.smoke_test.smoke_test", side_effect=fake)


def _stub_smoke_failing(*, canonical_failed: bool = False,
                        kata_failed: bool = False):
    from forge.catalog.smoke_test import SmokeResult

    def fake(lang_dir, *, force_reverify=False):
        failures = []
        if canonical_failed:
            failures.append("canonical: 5/8 passed (failed: closures, strings)")
        if kata_failed:
            failures.append("kata: 0/12 passed in pack 'classics' "
                            "(failed: two_sum, reverse_list, valid_parens)")
        return SmokeResult(
            passed=not failures,
            canonical={"passed": 5 if canonical_failed else 8,
                       "total": 8,
                       "pass_rate": 0.625 if canonical_failed else 1.0,
                       "source": "fake_failing"},
            kata={"passed": 0 if kata_failed else 0, "total": 0,
                  "pack_key": "classics"} if kata_failed else None,
            repl={"repl_html_ok": True, "compile_exit_code": 0,
                  "launches": True},
            failures=failures, skips=[], duration_seconds=0.01,
        )
    return patch("forge.catalog.smoke_test.smoke_test", side_effect=fake)


# ---------------------------------------------------------------------------
# Casing helper
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("snake_case_name", "snake_case"),
    ("kebab-case-name", "kebab-case"),
    ("PascalCaseName", "PascalCase"),
    ("camelCaseName", "camelCase"),
    ("lowercase", "lowercase"),
    ("UPPERCASE", "UPPERCASE"),
    ("", "unknown"),
])
def test_casing_helper(name, expected):
    assert _casing_of(name) == expected


# ---------------------------------------------------------------------------
# Perfect language fixture
# ---------------------------------------------------------------------------

def test_perfect_language_passes_overall(tmp_path):
    lang_dir = _make_perfect_lang(tmp_path / "canary_test")
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert report.overall_passed is True
    assert report.rejection_reason is None
    assert report.correctness.passed is True
    assert report.completeness.score == 1.0
    assert report.completeness.missing == []
    assert report.coherence.score == 1.0


def test_perfect_language_has_expected_metadata(tmp_path):
    lang_dir = _make_perfect_lang(tmp_path / "canary_test")
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert report.slot_id == "canary_test"
    # Compare resolved (absolute) paths so the test isn't sensitive to
    # whether tmp_path is already absolute on Windows vs POSIX.
    assert Path(report.lang_dir) == lang_dir.resolve()
    assert report.family == "c_like"
    assert report.pipeline_path == "templated"


# ---------------------------------------------------------------------------
# Broken language: canonical tests fail
# ---------------------------------------------------------------------------

def test_broken_language_canonical_fail_gets_rejected(tmp_path):
    lang_dir = _make_perfect_lang(tmp_path / "broken")
    with _stub_smoke_failing(canonical_failed=True):
        report = score_language(lang_dir)
    assert report.correctness.passed is False
    assert report.overall_passed is False
    assert report.rejection_reason is not None
    assert "correctness FAIL" in report.rejection_reason
    # The specific failure should be quoted in the rejection reason.
    assert "canonical" in report.rejection_reason.lower()


def test_broken_language_kata_fail_gets_rejected(tmp_path):
    lang_dir = _make_perfect_lang(tmp_path / "kata_broken")
    with _stub_smoke_failing(kata_failed=True):
        report = score_language(lang_dir)
    assert report.correctness.passed is False
    assert report.overall_passed is False
    assert "kata" in (report.rejection_reason or "").lower()


# ---------------------------------------------------------------------------
# Distinctiveness extremes
# ---------------------------------------------------------------------------

def test_vanilla_language_low_distinctiveness(tmp_path):
    """No customization, just creative content from the LLM. Should
    score low on surface (no overrides) and variety (no axes). Persona
    can still be moderate because creative.readme_intro + origin_story
    are populated."""
    lang_dir = _make_perfect_lang(tmp_path / "vanilla")
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    # Surface: 0 overrides, family_role_count=9 → 0.0
    assert report.distinctiveness.surface == 0.0
    # Variety: 0 axes exercised → 0.0
    assert report.distinctiveness.variety == 0.0
    # Overall low (only persona contributes).
    assert report.distinctiveness.score < 0.4
    # Should have a "no overrides" or "no customization" note.
    notes_joined = " ".join(report.distinctiveness.notes).lower()
    assert "surface" in notes_joined or "variety" in notes_joined


def test_highly_customized_language_high_distinctiveness(tmp_path):
    cust = {
        "persona": "stroustrup",
        "era": "1980s",
        "theme": "pirate",
        "phrasebook": "pirate",
        "feature_bans": ["no_inheritance"],
        "keyword_overrides": {
            "var": "loot", "func": "yarrn", "if": "ifnay",
            "else": "elseways", "while": "keelhaul",
            "return": "deliver", "true": "aye", "false": "nay",
            "null": "ghost",
        },
    }
    lang_dir = _make_perfect_lang(tmp_path / "themed", customization=cust)
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert report.distinctiveness.surface == 1.0   # all 9 c_like roles overridden
    assert report.distinctiveness.variety > 0.6    # 6 of 7 axes exercised
    assert report.distinctiveness.score > 0.7


# ---------------------------------------------------------------------------
# Completeness extremes
# ---------------------------------------------------------------------------

def test_missing_files_lower_completeness(tmp_path):
    """Remove a few artifacts and verify they show up in `missing`."""
    lang_dir = _make_perfect_lang(tmp_path / "incomplete")
    (lang_dir / "repl.html").unlink()
    (lang_dir / "theme.css").unlink()
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert report.completeness.score < 1.0
    assert "repl.html" in report.completeness.missing
    assert "theme.css" in report.completeness.missing
    # Both have weight 0.05, so completeness should be 1.0 - 0.10 = 0.9.
    assert abs(report.completeness.score - 0.9) < 0.01


def test_severely_incomplete_language_rejected(tmp_path):
    """A directory missing core files — parser.py, codegen.py — drops
    completeness below the 0.8 threshold and triggers rejection."""
    lang_dir = _make_perfect_lang(tmp_path / "severely_incomplete")
    (lang_dir / "parser.py").unlink()
    (lang_dir / "codegen.py").unlink()
    (lang_dir / "runtime.py").unlink()
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert report.completeness.score < COMPLETENESS_THRESHOLD
    assert report.overall_passed is False
    assert "completeness" in (report.rejection_reason or "").lower()


def test_short_readme_does_not_count_as_complete(tmp_path):
    """README.md must be present AND have substantive content. A 2-word
    README counts as missing."""
    lang_dir = _make_perfect_lang(tmp_path / "stub_readme")
    (lang_dir / "README.md").write_text("# stub\n", encoding="utf-8")
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert any("README.md" in m for m in report.completeness.missing)


def test_too_few_tests_counts_as_missing(tmp_path):
    """Tests directory must have ≥8 source files. Fewer counts as
    missing (it's the canonical-test-count contract)."""
    lang_dir = _make_perfect_lang(tmp_path / "few_tests")
    # Remove 5 test files.
    tests = lang_dir / "tests"
    for name in ("closures", "strings", "loops", "functions", "conditionals"):
        (tests / f"{name}.can").unlink()
        (tests / f"{name}.expected_output.txt").unlink()
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert any("tests" in m for m in report.completeness.missing)


# ---------------------------------------------------------------------------
# Coherence heuristics
# ---------------------------------------------------------------------------

def test_duplicate_keyword_overrides_drop_coherence(tmp_path):
    """If two roles map to the same target spelling (resolver
    confusion), the `overrides_unique` heuristic flags it."""
    cust = {
        "persona": None, "era": None, "theme": None,
        "phrasebook": None, "feature_bans": [],
        "keyword_overrides": {
            "var": "loot",
            "func": "loot",   # collision with var
        },
    }
    lang_dir = _make_perfect_lang(tmp_path / "collision", customization=cust)
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert report.coherence.overrides_unique is False
    assert report.coherence.score < 1.0
    notes = " ".join(report.coherence.notes)
    assert "collisions" in notes.lower() or "loot" in notes


def test_readme_without_lang_name_drops_coherence(tmp_path):
    lang_dir = _make_perfect_lang(tmp_path / "no_name_in_readme")
    # Replace README with something that doesn't mention canary_test.
    (lang_dir / "README.md").write_text(
        "# A language\n\n" + (
            "This is a perfectly fine README from a content perspective. "
            "It describes the syntax in detail, walks through the "
            "implementation choices, and presents some example programs. "
            "But it never names the language directly, which is a small "
            "coherence bug worth flagging.\n"
        ) * 3,
        encoding="utf-8",
    )
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    assert report.coherence.readme_mentions_name is False
    assert report.coherence.score < 1.0


# ---------------------------------------------------------------------------
# Idempotence + JSON serialization
# ---------------------------------------------------------------------------

def test_scorer_is_idempotent(tmp_path):
    """Scoring the same directory twice produces equal reports
    (modulo the timestamp + duration fields)."""
    lang_dir = _make_perfect_lang(tmp_path / "idem")
    with _stub_smoke_passing():
        r1 = score_language(lang_dir)
    with _stub_smoke_passing():
        r2 = score_language(lang_dir)
    # Check that the four scoring sub-results are identical.
    assert r1.correctness == r2.correctness
    assert r1.distinctiveness == r2.distinctiveness
    assert r1.coherence == r2.coherence
    assert r1.completeness == r2.completeness
    assert r1.overall_passed == r2.overall_passed
    assert r1.rejection_reason == r2.rejection_reason
    # slot_id, family, pipeline_path also identical.
    assert (r1.slot_id, r1.family, r1.pipeline_path) == (
        r2.slot_id, r2.family, r2.pipeline_path
    )


def test_report_serializes_to_json(tmp_path):
    lang_dir = _make_perfect_lang(tmp_path / "ser")
    with _stub_smoke_passing():
        report = score_language(lang_dir)
    d = report_to_dict(report)
    # Must be JSON-serializable without errors.
    s = json.dumps(d, indent=2)
    assert "slot_id" in s
    assert "correctness" in s
    assert "distinctiveness" in s
    # And re-parseable.
    parsed = json.loads(s)
    assert parsed["overall_passed"] is True


def test_write_batch_report_atomic(tmp_path):
    """write_batch_report uses tmp + os.replace so a partial write
    can't poison the output."""
    lang_dir = _make_perfect_lang(tmp_path / "lang")
    with _stub_smoke_passing():
        reports = [score_language(lang_dir)]
    out = tmp_path / "report.json"
    write_batch_report(reports, out)
    assert out.exists()
    # No leftover .tmp.
    assert not out.with_suffix(out.suffix + ".tmp").exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["report_count"] == 1
    assert payload["aggregate"]["total"] == 1
    assert payload["aggregate"]["overall_passed"] == 1


# ---------------------------------------------------------------------------
# Batch scorer
# ---------------------------------------------------------------------------

def test_score_batch_finds_only_language_dirs(tmp_path):
    """score_batch identifies language dirs by `resolved_spec.json`.
    Other entries (state.json file, batch_summary.json file, empty
    dirs) are skipped."""
    _make_perfect_lang(tmp_path / "lang_a")
    _make_perfect_lang(tmp_path / "lang_b")
    # Junk: a state file, a batch summary, and an empty dir.
    (tmp_path / "state.json").write_text("{}", encoding="utf-8")
    (tmp_path / "batch_summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / "empty_dir").mkdir()
    with _stub_smoke_passing():
        reports = score_batch(tmp_path)
    assert len(reports) == 2
    slot_ids = {r.slot_id for r in reports}
    assert slot_ids == {"canary_test"}  # both fixtures use the same default name


def test_score_batch_missing_input_dir_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        score_batch(tmp_path / "does_not_exist")


def test_aggregate_handles_empty_reports():
    assert _aggregate([]) == {"total": 0}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_runs_against_fixture_dir(tmp_path):
    from forge.catalog.quality import _main
    _make_perfect_lang(tmp_path / "lang_a")
    out = tmp_path / "out.json"
    with _stub_smoke_passing():
        rc = _main(["--input", str(tmp_path), "--output", str(out)])
    assert rc == 0
    assert out.exists()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["report_count"] == 1


def test_cli_rejects_missing_input(tmp_path):
    from forge.catalog.quality import _main
    rc = _main([
        "--input", str(tmp_path / "no_such_dir"),
        "--output", str(tmp_path / "out.json"),
    ])
    assert rc == 2
