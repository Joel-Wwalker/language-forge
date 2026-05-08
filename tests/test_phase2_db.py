"""Phase 2 Stage C — catalog DB tests.

Pins:
  - Schema migrations apply cleanly on a fresh DB.
  - Inserting a batch creates the right rows in `languages`,
    `duplicates`, and `batches`.
  - `list_languages` filters work (by family, status).
  - `update_language_status` writes and reads back.
  - The DB is idempotent — re-inserting the same batch's reports
    doesn't double-insert languages.
  - Status validation rejects unknown status values.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from forge.catalog.db import (
    BatchRow,
    DuplicateRow,
    LanguageRow,
    SCHEMA_VERSION,
    STATUS_APPROVED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_VALUES,
    get_batch,
    get_language,
    init_db,
    insert_batch_result,
    list_duplicates,
    list_languages,
    update_language_status,
)
from forge.catalog.dedup import DedupResult
from forge.catalog.quality import (
    CompletenessResult,
    CorrectnessResult,
    CoherenceResult,
    DistinctivenessResult,
    QualityReport,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _write_lang_dir(parent: Path, slot_id: str, *,
                    family: str = "c_like",
                    typing: str = "dynamic",
                    memory: str = "host_gc",
                    persona: str = None,
                    theme: str = None) -> Path:
    """Build a minimal lang_dir with resolved_spec.json + summary."""
    lang_dir = parent / slot_id
    lang_dir.mkdir(parents=True, exist_ok=True)
    spec = {
        "lang_name": slot_id,
        "display_name": slot_id,
        "options": {"syntax": family, "typing": typing, "memory": memory},
        "customization": {
            "persona": persona, "era": None, "theme": theme,
            "phrasebook": None, "feature_bans": [],
        },
    }
    (lang_dir / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8"
    )
    (lang_dir / "generation_summary.json").write_text(
        json.dumps({"lang_name": slot_id, "pipeline_path": "templated"},
                   indent=2),
        encoding="utf-8",
    )
    return lang_dir


def _make_report(slot_id: str, lang_dir: Path, *,
                 family: str = "c_like",
                 passed: bool = True) -> QualityReport:
    return QualityReport(
        slot_id=slot_id,
        lang_dir=str(lang_dir.resolve()),
        family=family,
        pipeline_path="templated",
        correctness=CorrectnessResult(
            passed=passed,
            canonical_tests={"passed": 8 if passed else 0, "total": 8,
                             "pass_rate": 1.0, "source": "fixture"},
            kata_pack=None,
            repl={"repl_html_ok": True, "compile_exit_code": 0,
                  "launches": True},
            failures=[] if passed else ["canonical: 0/8 (fixture)"],
            skips=[],
        ),
        distinctiveness=DistinctivenessResult(
            score=0.5, surface=0.5, persona=0.5, variety=0.5, notes=[],
        ),
        coherence=CoherenceResult(
            score=1.0, overrides_unique=True, readme_mentions_name=True,
            readme_length_ok=True, stdlib_naming_consistent=True, notes=[],
        ),
        completeness=CompletenessResult(score=1.0, present=[], missing=[]),
        overall_passed=passed,
        rejection_reason=None if passed else "fixture: canonical fail",
        scored_at="2026-05-08T00:00:00Z",
    )


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def test_init_db_creates_schema_on_fresh_path(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    assert db.exists()
    # Verify expected tables exist.
    with sqlite3.connect(str(db)) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert {"languages", "duplicates", "batches"} <= names


def test_init_db_sets_user_version(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    with sqlite3.connect(str(db)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION


def test_init_db_is_idempotent(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db); init_db(db); init_db(db)
    # No error; tables still present.
    with sqlite3.connect(str(db)) as conn:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert "languages" in names


def test_init_db_rejects_future_schema_version(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    # Bump user_version manually to simulate a future schema.
    with sqlite3.connect(str(db)) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 99}")
        conn.commit()
    with pytest.raises(RuntimeError, match="only supports up to"):
        init_db(db)


# ---------------------------------------------------------------------------
# Batch insertion
# ---------------------------------------------------------------------------

def test_insert_batch_creates_expected_rows(tmp_path):
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    a = _write_lang_dir(batch_dir, "slot_a", theme="pirate")
    b = _write_lang_dir(batch_dir, "slot_b")
    c = _write_lang_dir(batch_dir, "slot_c", family="s_expression")

    reports = [
        _make_report("slot_a", a),
        _make_report("slot_b", b),
        _make_report("slot_c", c, family="s_expression"),
    ]
    # No duplicates in this fixture — three distinct languages.
    dedup_results = [
        DedupResult(representative_slot_id="slot_a",
                    representative_lang_dir=str(a),
                    representative_score=4.0, fingerprint="fp_a"),
        DedupResult(representative_slot_id="slot_b",
                    representative_lang_dir=str(b),
                    representative_score=4.0, fingerprint="fp_b"),
        DedupResult(representative_slot_id="slot_c",
                    representative_lang_dir=str(c),
                    representative_score=4.0, fingerprint="fp_c"),
    ]
    batch_id = insert_batch_result(
        db, batch_dir, "plan.json", reports, dedup_results,
    )
    assert isinstance(batch_id, int) and batch_id > 0

    langs = list_languages(db)
    assert len(langs) == 3
    assert {l.slot_id for l in langs} == {"slot_a", "slot_b", "slot_c"}
    assert all(l.status == STATUS_PENDING for l in langs)
    assert all(l.batch_id == batch_id for l in langs)

    batch = get_batch(db, batch_id)
    assert batch is not None
    assert batch.total_slots == 3
    assert batch.passed_quality == 3


def test_insert_batch_records_duplicates(tmp_path):
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    a = _write_lang_dir(batch_dir, "slot_a")
    b = _write_lang_dir(batch_dir, "slot_b")
    reports = [_make_report("slot_a", a), _make_report("slot_b", b)]
    # b is a duplicate of a.
    dedup_results = [DedupResult(
        representative_slot_id="slot_a",
        representative_lang_dir=str(a),
        representative_score=4.0,
        duplicate_slot_ids=["slot_b"],
        fingerprint="fp_ab",
    )]
    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)

    langs = list_languages(db)
    assert {l.slot_id for l in langs} == {"slot_a"}  # only the representative

    dups = list_duplicates(db, "slot_a")
    assert len(dups) == 1
    assert dups[0].duplicate_slot_id == "slot_b"


def test_insert_batch_marks_failed_correctness_as_rejected(tmp_path):
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    a = _write_lang_dir(batch_dir, "slot_a")
    b = _write_lang_dir(batch_dir, "slot_b")
    reports = [
        _make_report("slot_a", a, passed=True),
        _make_report("slot_b", b, passed=False),
    ]
    dedup_results = [
        DedupResult("slot_a", str(a), 4.0, fingerprint="fp_a"),
        DedupResult("slot_b", str(b), 2.0, fingerprint="fp_b"),
    ]
    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)

    a_row = get_language(db, "slot_a")
    b_row = get_language(db, "slot_b")
    assert a_row.status == STATUS_PENDING
    assert b_row.status == STATUS_REJECTED
    assert b_row.rejection_reason is not None


def test_insert_batch_idempotent(tmp_path):
    """Re-running insert_batch_result with the same reports doesn't
    duplicate language rows. (Slot_id is UNIQUE in the schema; the
    INSERT OR IGNORE / try-except path catches the constraint.)"""
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    a = _write_lang_dir(batch_dir, "slot_a")
    reports = [_make_report("slot_a", a)]
    dedup_results = [DedupResult("slot_a", str(a), 4.0, fingerprint="fp")]

    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)
    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)
    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)

    langs = list_languages(db)
    assert len(langs) == 1


def test_insert_batch_creates_new_batch_row_per_call(tmp_path):
    """Each insert_batch_result call creates a new batches row, even
    if the languages it inserts already exist. This is the audit trail
    showing when re-curation happened."""
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    a = _write_lang_dir(batch_dir, "slot_a")
    reports = [_make_report("slot_a", a)]
    dedup_results = [DedupResult("slot_a", str(a), 4.0, fingerprint="fp")]
    bid1 = insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)
    bid2 = insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)
    assert bid1 != bid2
    assert get_batch(db, bid1) is not None
    assert get_batch(db, bid2) is not None


# ---------------------------------------------------------------------------
# Read filtering
# ---------------------------------------------------------------------------

def test_list_languages_filters_by_family(tmp_path):
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    a = _write_lang_dir(batch_dir, "slot_a", family="c_like")
    b = _write_lang_dir(batch_dir, "slot_b", family="stack_based")
    c = _write_lang_dir(batch_dir, "slot_c", family="s_expression")
    reports = [
        _make_report("slot_a", a, family="c_like"),
        _make_report("slot_b", b, family="stack_based"),
        _make_report("slot_c", c, family="s_expression"),
    ]
    dedup_results = [
        DedupResult(s.slot_id, s.lang_dir, 4.0, fingerprint=f"fp_{s.slot_id}")
        for s in reports
    ]
    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)

    cl = list_languages(db, family="c_like")
    assert [l.slot_id for l in cl] == ["slot_a"]
    sb = list_languages(db, family="stack_based")
    assert [l.slot_id for l in sb] == ["slot_b"]


def test_list_languages_filters_by_status(tmp_path):
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    a = _write_lang_dir(batch_dir, "slot_a")
    b = _write_lang_dir(batch_dir, "slot_b")
    reports = [
        _make_report("slot_a", a, passed=True),
        _make_report("slot_b", b, passed=False),
    ]
    dedup_results = [
        DedupResult("slot_a", str(a), 4.0, fingerprint="fp_a"),
        DedupResult("slot_b", str(b), 2.0, fingerprint="fp_b"),
    ]
    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)

    pend = list_languages(db, status=STATUS_PENDING)
    rej = list_languages(db, status=STATUS_REJECTED)
    assert [l.slot_id for l in pend] == ["slot_a"]
    assert [l.slot_id for l in rej] == ["slot_b"]


def test_list_languages_respects_limit(tmp_path):
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    reports = []
    dedup_results = []
    for i in range(5):
        sid = f"slot_{i:03d}"
        d = _write_lang_dir(batch_dir, sid)
        reports.append(_make_report(sid, d))
        dedup_results.append(
            DedupResult(sid, str(d), 4.0, fingerprint=f"fp_{i}")
        )
    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)
    rows = list_languages(db, limit=3)
    assert len(rows) == 3


def test_list_languages_on_missing_db_returns_empty(tmp_path):
    assert list_languages(tmp_path / "nonexistent.db") == []


def test_get_language_returns_none_for_missing(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    assert get_language(db, "slot_999") is None


# ---------------------------------------------------------------------------
# Status update
# ---------------------------------------------------------------------------

def test_update_language_status_writes_and_reads_back(tmp_path):
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    a = _write_lang_dir(batch_dir, "slot_a")
    insert_batch_result(
        db, batch_dir, "plan.json",
        [_make_report("slot_a", a)],
        [DedupResult("slot_a", str(a), 4.0, fingerprint="fp")],
    )
    ok = update_language_status(
        db, "slot_a", STATUS_APPROVED, reviewer_notes="looks good"
    )
    assert ok is True
    row = get_language(db, "slot_a")
    assert row.status == STATUS_APPROVED
    assert row.reviewer_notes == "looks good"


def test_update_language_status_rejects_unknown_status(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    with pytest.raises(ValueError, match="status must be one of"):
        update_language_status(db, "any_slot", "bogus_status")


def test_update_language_status_returns_false_for_missing_slot(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    ok = update_language_status(db, "slot_does_not_exist", STATUS_APPROVED)
    assert ok is False


# ---------------------------------------------------------------------------
# Concurrent writes
# ---------------------------------------------------------------------------

def test_concurrent_status_updates_dont_corrupt_db(tmp_path):
    """Phase 1.5 hardening: state writes had to survive concurrency.
    The DB write lock should give the same property — N threads
    each updating distinct slots all succeed, and the DB stays
    consistent."""
    db = tmp_path / "catalog.db"
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    reports = []
    dedup_results = []
    for i in range(8):
        sid = f"slot_{i:03d}"
        d = _write_lang_dir(batch_dir, sid)
        reports.append(_make_report(sid, d))
        dedup_results.append(
            DedupResult(sid, str(d), 4.0, fingerprint=f"fp_{i}")
        )
    insert_batch_result(db, batch_dir, "plan.json", reports, dedup_results)

    errors: list[Exception] = []

    def updater(i: int):
        try:
            for _ in range(5):
                update_language_status(
                    db, f"slot_{i:03d}", STATUS_APPROVED,
                    reviewer_notes=f"thread {i}",
                )
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=updater, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"concurrent updates raised: {errors[0]!r}"

    # All 8 should be APPROVED now.
    approved = list_languages(db, status=STATUS_APPROVED)
    assert len(approved) == 8


# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

def test_status_values_are_documented():
    assert STATUS_VALUES == ("pending_review", "approved", "rejected")
    assert STATUS_PENDING == "pending_review"
    assert STATUS_APPROVED == "approved"
    assert STATUS_REJECTED == "rejected"
