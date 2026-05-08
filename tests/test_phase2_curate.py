"""Phase 2 Stage D — end-to-end curate pipeline tests.

Pins:
  - End-to-end: feed a fixture directory of N synthetic generated
    languages, run `curate`, verify the DB has the right rows with
    the right statuses.
  - Idempotence: running `curate` twice on the same input doesn't
    double-insert.
  - Resume after interruption: simulating a crash mid-pipeline and
    re-running yields the expected end state.
  - The CLI entry point (`_main`) returns 0 on success and 2 on bad
    inputs.

Uses the same `_make_perfect_lang` fixture pattern as Stage A's tests
to avoid coupling to actual Phase 1.5 generation.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from forge.catalog.curate import curate, _main
from forge.catalog.db import (
    STATUS_PENDING,
    STATUS_REJECTED,
    list_languages,
    list_duplicates,
    get_batch,
)
from forge.catalog.smoke_test import SmokeResult


# ---------------------------------------------------------------------------
# Fixture builders (copied from test_phase2_quality but separated to
# keep the test suites independent)
# ---------------------------------------------------------------------------

_README = (
    "# canary_test\n\n"
    "canary_test is a small c_like language used to validate the Phase 2 "
    "curation pipeline end-to-end. It supports basic arithmetic, string "
    "manipulation, list and dictionary operations, conditional branching, "
    "and while-loop iteration. Variables are declared with var, functions "
    "with func, and values are returned with return. The language "
    "transpiles to Python so memory management is automatic. The standard "
    "library covers print, len, get, set, push, pop, range, str, int, "
    "float. The test suite covers eight canonical programs.\n"
)
_LANGUAGE_MD = (
    "# canary_test reference\n\n"
    "Variable declaration uses `var name = value;`. Functions are "
    "defined with `func name(params) { body }`. Conditional branching "
    "follows the c_like idiom: if (cond) { ... } else { ... }. The "
    "while loop iterates until its condition becomes false. Comments "
    "are // line and /* block */. Strings use double quotes only. "
    "Booleans are true and false; the absent value is null. The "
    "standard library exposes print for output and len, get, set, "
    "push, pop, range, has for container manipulation. Integers and "
    "floats are decimal-only. Comparison operators include ==, !=, <, "
    ">, <=, >=. Logical operators are &&, ||, !. Arithmetic is +, -, "
    "*, /, %. The language is dynamically typed and uses host garbage "
    "collection. Errors panic (no exception handling). Loops support "
    "while only.\n"
) * 2


def _make_lang(parent: Path, slot_id: str, *,
               family: str = "c_like",
               keyword_overrides: dict | None = None,
               persona: str | None = None,
               theme: str | None = None) -> Path:
    """Build a synthetic generated-language directory."""
    d = parent / slot_id
    d.mkdir(parents=True, exist_ok=True)
    cust = {
        "persona": persona, "era": None, "theme": theme,
        "phrasebook": None, "feature_bans": [],
    }
    if keyword_overrides is not None:
        cust["keyword_overrides"] = keyword_overrides
    spec = {
        "lang_name": slot_id,
        "display_name": slot_id,
        "options": {"syntax": family, "typing": "dynamic", "memory": "host_gc"},
        "customization": cust,
        "creative": {"readme_intro": "A perfectly fine introduction "
                                     "covering forty or more words because "
                                     "the scorer's persona heuristic "
                                     "looks at length, and we want this "
                                     "fixture to score reasonably high "
                                     "on the persona dimension."},
        "origin_story": "An origin story long enough to count.  " * 12,
    }
    (d / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8"
    )
    (d / "generation_summary.json").write_text(
        json.dumps({"lang_name": slot_id, "pipeline_path": "templated"},
                   indent=2),
        encoding="utf-8",
    )
    for f in ("parser.py", "codegen.py", "runtime.py", "stdlib.py",
              "compile.py"):
        (d / f).write_text("pass\n", encoding="utf-8")
    (d / "README.md").write_text(_README, encoding="utf-8")
    (d / "LANGUAGE.md").write_text(_LANGUAGE_MD, encoding="utf-8")
    (d / "repl.html").write_text("<html>pyodide stub</html>", encoding="utf-8")
    (d / "theme.css").write_text("body{}", encoding="utf-8")
    tests = d / "tests"; tests.mkdir(exist_ok=True)
    for name in ("hello_world", "arithmetic", "variables", "conditionals",
                 "loops", "functions", "closures", "strings"):
        ext = ".can" if family == "c_like" else (
            ".lsp" if family == "s_expression" else ".f"
        )
        (tests / f"{name}{ext}").write_text(f"# {name}\n", encoding="utf-8")
        (tests / f"{name}.expected_output.txt").write_text(
            f"{name}\n", encoding="utf-8"
        )
    return d


def _stub_smoke_passing():
    def fake(lang_dir, *, force_reverify=False):
        return SmokeResult(
            passed=True,
            canonical={"passed": 8, "total": 8, "pass_rate": 1.0,
                       "source": "fake"},
            kata={"passed": 12, "total": 12, "pass_rate": 1.0,
                  "pack_key": "classics"},
            repl={"repl_html_ok": True, "compile_exit_code": 0,
                  "launches": True},
            failures=[], skips=[], duration_seconds=0.01,
        )
    return patch("forge.catalog.smoke_test.smoke_test", side_effect=fake)


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------

def test_curate_end_to_end_creates_db_with_right_rows(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _make_lang(batch_dir, "slot_a")
    _make_lang(batch_dir, "slot_b", theme="pirate",
               keyword_overrides={"var": "loot", "func": "yarrn"})
    _make_lang(batch_dir, "slot_c", family="s_expression")
    db = tmp_path / "catalog.db"

    with _stub_smoke_passing():
        summary = curate(batch_dir, db, verbose=False)

    assert summary["scored"]["total"] == 3
    assert summary["scored"]["overall_passed"] == 3
    # Three distinct fingerprints (different families / customizations).
    assert summary["dedup"]["unique_languages"] == 3
    assert summary["dedup"]["duplicates_collapsed"] == 0

    rows = list_languages(db)
    assert len(rows) == 3
    assert all(r.status == STATUS_PENDING for r in rows)

    batch = get_batch(db, summary["batch_id"])
    assert batch is not None
    assert batch.total_slots == 3
    assert batch.passed_quality == 3


def test_curate_collapses_duplicates(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    # Two slots with identical specs (same options + customization, no
    # overrides) → should dedup to one.
    _make_lang(batch_dir, "slot_x")
    _make_lang(batch_dir, "slot_y")
    # A third with a theme is distinct.
    _make_lang(batch_dir, "slot_z", theme="pirate")
    db = tmp_path / "catalog.db"

    with _stub_smoke_passing():
        summary = curate(batch_dir, db, verbose=False)

    assert summary["scored"]["total"] == 3
    assert summary["dedup"]["unique_languages"] == 2
    assert summary["dedup"]["duplicates_collapsed"] == 1

    rows = list_languages(db)
    # 2 representatives in `languages`; 1 entry in `duplicates`.
    assert len(rows) == 2
    rep_slot_ids = {r.slot_id for r in rows}
    # The duplicate-of relationship is recorded against whichever slot
    # was chosen as representative (deterministic by score then
    # slot_id; for identical scores the lower slot_id wins).
    representative = "slot_x"  # lower than slot_y
    assert representative in rep_slot_ids
    dups = list_duplicates(db, representative)
    assert len(dups) == 1
    assert dups[0].duplicate_slot_id == "slot_y"


def test_curate_idempotent_no_double_insert(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _make_lang(batch_dir, "slot_a")
    _make_lang(batch_dir, "slot_b", theme="pirate")
    db = tmp_path / "catalog.db"

    with _stub_smoke_passing():
        s1 = curate(batch_dir, db, verbose=False)
    with _stub_smoke_passing():
        s2 = curate(batch_dir, db, verbose=False)

    rows = list_languages(db)
    assert len(rows) == 2  # NOT 4 — no double-insert
    # Two batch rows, distinct ids.
    assert s1["batch_id"] != s2["batch_id"]
    assert get_batch(db, s1["batch_id"]) is not None
    assert get_batch(db, s2["batch_id"]) is not None


def test_curate_writes_reports_json(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _make_lang(batch_dir, "slot_a")
    db = tmp_path / "catalog.db"
    reports_dir = tmp_path / "custom_reports"

    with _stub_smoke_passing():
        summary = curate(batch_dir, db, reports_dir=reports_dir, verbose=False)

    assert Path(summary["reports_path"]).exists()
    payload = json.loads(
        Path(summary["reports_path"]).read_text(encoding="utf-8")
    )
    assert payload["report_count"] == 1
    assert payload["aggregate"]["overall_passed"] == 1


def test_curate_uses_default_reports_dir_when_none(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _make_lang(batch_dir, "slot_a")
    db = tmp_path / "catalog.db"

    with _stub_smoke_passing():
        summary = curate(batch_dir, db, verbose=False)

    # Default is <input>/.curation/
    assert Path(summary["reports_path"]).is_relative_to(
        batch_dir / ".curation"
    )


# ---------------------------------------------------------------------------
# Resume / partial-state behavior
# ---------------------------------------------------------------------------

def test_curate_resumes_after_partial_run(tmp_path):
    """Simulate a crash partway through: write some languages to the
    DB via a first curate(), then add more languages to the input
    dir, re-curate, and verify both old and new are present.

    Uses distinct customizations so dedup keeps them as separate
    representatives — the resume contract is about the DB picking
    up new languages, not about dedup behavior."""
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _make_lang(batch_dir, "slot_a", theme="pirate")
    _make_lang(batch_dir, "slot_b", theme="latin")
    db = tmp_path / "catalog.db"

    # First pass: only slot_a + slot_b in the dir.
    with _stub_smoke_passing():
        curate(batch_dir, db, verbose=False)
    assert len(list_languages(db)) == 2

    # Now add slot_c (simulating: more languages got generated after
    # the first curation pass) and re-curate.
    _make_lang(batch_dir, "slot_c", theme="cozy")
    with _stub_smoke_passing():
        curate(batch_dir, db, verbose=False)

    rows = list_languages(db)
    slot_ids = {r.slot_id for r in rows}
    assert slot_ids == {"slot_a", "slot_b", "slot_c"}


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------

def test_curate_cli_returns_0_on_success(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _make_lang(batch_dir, "slot_a")
    db = tmp_path / "catalog.db"
    with _stub_smoke_passing():
        rc = _main([
            "--input", str(batch_dir),
            "--db", str(db),
            "--quiet",
        ])
    assert rc == 0
    assert db.exists()


def test_curate_cli_returns_2_on_missing_input(tmp_path):
    rc = _main([
        "--input", str(tmp_path / "no_such_dir"),
        "--db", str(tmp_path / "catalog.db"),
    ])
    assert rc == 2


def test_curate_cli_records_slot_plan_path(tmp_path):
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    _make_lang(batch_dir, "slot_a")
    db = tmp_path / "catalog.db"
    plan = tmp_path / "myplan.json"
    plan.write_text("[]", encoding="utf-8")
    with _stub_smoke_passing():
        rc = _main([
            "--input", str(batch_dir),
            "--db", str(db),
            "--slot-plan", str(plan),
            "--quiet",
        ])
    assert rc == 0
    # The recorded slot_plan_path should match what we passed.
    with sqlite3.connect(str(db)) as conn:
        rows = conn.execute(
            "SELECT slot_plan_path FROM batches"
        ).fetchall()
    assert len(rows) == 1
    assert Path(rows[0][0]) == plan.resolve()
