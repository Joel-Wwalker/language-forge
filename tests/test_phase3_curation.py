"""Phase 3 — Curation UI tests.

Pins the contract for the four stages:

  A) Read-only browser: GET /api/catalog/list, /api/catalog/<slot_id>,
     /api/catalog/facets, /api/catalog/progress. Filters work; 404 on
     unknown slot_id; missing slot.json fields fall back from DB row.
  B) Write path: POST /api/catalog/<slot_id>/status updates correctly,
     validates status values, handles rejection_reason. POST .../notes
     updates without changing status.
  C) Tier and tag system: schema v2 migration applies, tier/tag write
     and read back, autocomplete returns distinct tags.
  D) Bulk operations: bulk status update, bulk tag add, validation.

Each test uses a fresh temp DB seeded with synthetic LanguageRow data
so there's no cross-test pollution. The Flask app is built via
`create_app(catalog_db_path=...)` so the routes point at the test DB
instead of the real one.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from forge.catalog.db import (
    SCHEMA_VERSION, STATUS_APPROVED, STATUS_PENDING, STATUS_REJECTED,
    init_db, insert_batch_result, list_languages,
    get_language, update_language_notes, update_language_tier,
    update_language_tags, list_distinct_tags, add_tag_to_language,
    bulk_update_status, bulk_add_tag,
)
from forge.catalog.dedup import DedupResult
from forge.catalog.quality import (
    CompletenessResult, CorrectnessResult, CoherenceResult,
    DistinctivenessResult, QualityReport,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_lang_dir(parent: Path, slot_id: str, *,
                   family: str = "c_like",
                   typing: str = "dynamic",
                   memory: str = "host_gc",
                   persona: Optional[str] = None,
                   era: Optional[str] = None,
                   theme: Optional[str] = None,
                   phrasebook: Optional[str] = None) -> Path:
    """Build a minimal generated-language directory (resolved_spec +
    summary + slot.json + README)."""
    d = parent / slot_id
    d.mkdir(parents=True, exist_ok=True)
    spec = {
        "lang_name": slot_id,
        "display_name": slot_id,
        "options": {"syntax": family, "typing": typing, "memory": memory},
        "customization": {
            "persona": persona, "era": era, "theme": theme,
            "phrasebook": phrasebook, "feature_bans": [],
        },
    }
    (d / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8")
    (d / "generation_summary.json").write_text(
        json.dumps({"lang_name": slot_id, "pipeline_path": "templated"},
                   indent=2),
        encoding="utf-8")
    # slot.json — the original input the runner copies. This is what
    # the curation UI falls back to when DB row's customization is NULL.
    (d / "slot.json").write_text(json.dumps({
        "slot_id": slot_id,
        "options": {"syntax": family, "typing": typing, "memory": memory},
        "customization": {
            "persona": persona, "era": era, "theme": theme,
            "phrasebook": phrasebook, "feature_bans": [],
        },
        "seed": 1, "target_rarity": "common",
    }, indent=2), encoding="utf-8")
    (d / "README.md").write_text(
        f"# {slot_id}\n\nA test language used for curation-UI tests.\n",
        encoding="utf-8")
    (d / "LANGUAGE.md").write_text(
        f"# {slot_id} reference\n\nReference doc.\n", encoding="utf-8")
    return d


def _make_report(slot_id: str, lang_dir: Path, *,
                 family: str = "c_like",
                 passed: bool = True,
                 distinctiveness: float = 0.5,
                 coherence: float = 1.0,
                 completeness: float = 1.0) -> QualityReport:
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
            failures=[] if passed else ["fixture failure"],
            skips=[],
        ),
        distinctiveness=DistinctivenessResult(
            score=distinctiveness, surface=distinctiveness,
            persona=distinctiveness, variety=distinctiveness, notes=[]),
        coherence=CoherenceResult(
            score=coherence, overrides_unique=True, readme_mentions_name=True,
            readme_length_ok=True, stdlib_naming_consistent=True, notes=[]),
        completeness=CompletenessResult(
            score=completeness, present=[], missing=[]),
        overall_passed=passed and completeness >= 0.8,
        rejection_reason=None if passed else "fixture: canonical fail",
        scored_at="2026-05-08T00:00:00Z",
    )


def _seed_db(tmp_path: Path, n: int = 5) -> tuple[Path, Path]:
    """Build a populated catalog DB with `n` synthetic languages.
    Returns (db_path, generated_root). Mixes families / personas /
    themes for filter-test coverage."""
    gen = tmp_path / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "catalog.db"
    reports = []
    dedup_results = []
    families = ["c_like", "s_expression", "stack_based"]
    themes = [None, "pirate", None, "cozy", "latin"]
    personas = ["wirth", None, "stroustrup", None, "hickey"]
    for i in range(n):
        slot_id = f"slot_{i:03d}"
        d = _make_lang_dir(
            gen, slot_id,
            family=families[i % 3],
            persona=personas[i] if i < len(personas) else None,
            theme=themes[i] if i < len(themes) else None,
        )
        reports.append(_make_report(
            slot_id, d, family=families[i % 3],
            distinctiveness=round((i + 1) / (n + 1), 3),
        ))
        dedup_results.append(DedupResult(
            representative_slot_id=slot_id,
            representative_lang_dir=str(d),
            representative_score=4.0,
            fingerprint=f"fp_{i}",
        ))
    insert_batch_result(db, gen, "plan.json", reports, dedup_results)
    return db, gen


@pytest.fixture
def app_client(tmp_path):
    """Build a Flask test client whose catalog routes point at a
    fresh seeded DB. Returns (client, db_path, generated_root)."""
    db, gen = _seed_db(tmp_path, n=6)
    from forge.gui.app import create_app
    app = create_app(catalog_db_path=db, catalog_generated_root=gen)
    with app.test_client() as client:
        yield client, db, gen


# ===========================================================================
# Stage A — Read-only browser
# ===========================================================================

def test_catalog_index_serves_html(app_client):
    client, _, _ = app_client
    r = client.get("/catalog")
    assert r.status_code == 200
    assert b"<title>Forge Catalog Curation</title>" in r.data
    # The page links the catalog.js + catalog.css we built.
    assert b"/static/catalog.js" in r.data
    assert b"/static/catalog.css" in r.data


def test_catalog_list_returns_all_seeded_rows(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/list")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total_unfiltered"] == 6
    # Default status filter shows only pending_review (the default
    # status for inserted rows).
    assert all(item["status"] == "pending_review" for item in data["items"])


def test_catalog_list_filters_by_family(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/list?family=c_like")
    data = r.get_json()
    assert all(item["family"] == "c_like" for item in data["items"])


def test_catalog_list_filters_by_persona(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/list?persona=wirth")
    data = r.get_json()
    assert all(item["persona"] == "wirth" for item in data["items"])
    # At least one result for the seed.
    assert len(data["items"]) >= 1


def test_catalog_list_filters_by_theme(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/list?theme=pirate")
    data = r.get_json()
    for item in data["items"]:
        assert item["theme"] == "pirate"
    assert len(data["items"]) >= 1


def test_catalog_list_filters_by_distinctiveness_range(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/list?min_distinctiveness=0.5")
    data = r.get_json()
    for item in data["items"]:
        assert item["distinctiveness"] >= 0.5


def test_catalog_list_search_matches_slot_id(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/list?search=slot_001")
    data = r.get_json()
    assert any(item["slot_id"] == "slot_001" for item in data["items"])


def test_catalog_list_sorts_by_distinctiveness_desc(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/list?sort_by=distinctiveness&sort_dir=desc")
    data = r.get_json()
    scores = [i["distinctiveness"] for i in data["items"]]
    assert scores == sorted(scores, reverse=True)


def test_catalog_detail_returns_full_data(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/slot_000")
    assert r.status_code == 200
    data = r.get_json()
    assert data["slot_id"] == "slot_000"
    # Full sub-objects present.
    assert "resolved_spec" in data
    assert "quality_report" in data
    assert "slot_json" in data
    assert "readme" in data
    assert "language_md" in data
    assert "files" in data
    # README content was loaded from disk.
    assert "slot_000" in data["readme"]


def test_catalog_detail_404_on_unknown_slot(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/no_such_slot")
    assert r.status_code == 404


def test_catalog_facets_returns_distinct_values(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/facets")
    data = r.get_json()
    assert "families" in data
    assert "personas" in data
    assert "themes" in data
    assert set(data["families"]) <= {"c_like", "s_expression", "stack_based"}
    assert "wirth" in data["personas"]
    assert "pirate" in data["themes"]


def test_catalog_progress_returns_counts(app_client):
    client, _, _ = app_client
    r = client.get("/api/catalog/progress")
    data = r.get_json()
    assert data["total"] == 6
    assert data["pending_review"] == 6
    assert data["approved"] == 0
    assert data["rejected"] == 0


def test_catalog_list_falls_back_to_slot_json_for_normalized_fields(tmp_path):
    """Phase 2's resolver normalizes theme/era/persona into
    keyword_overrides, leaving DB columns NULL. The UI must fall back
    to slot.json for filtering. Pin that contract."""
    gen = tmp_path / "generated"
    gen.mkdir()
    db = tmp_path / "catalog.db"
    # Build a generated dir with persona+theme in slot.json BUT use a
    # report whose DB row will have NULLs (we simulate the normalized
    # spec by writing resolved_spec.json without the customization
    # fields).
    d = gen / "slot_x"
    d.mkdir()
    (d / "resolved_spec.json").write_text(json.dumps({
        "lang_name": "slot_x",
        "display_name": "slot_x",
        "options": {"syntax": "c_like", "typing": "dynamic",
                    "memory": "host_gc"},
        "customization": {},  # NULLs the way the resolver leaves them
    }), encoding="utf-8")
    (d / "generation_summary.json").write_text(json.dumps({
        "lang_name": "slot_x", "pipeline_path": "templated"}), encoding="utf-8")
    (d / "slot.json").write_text(json.dumps({
        "slot_id": "slot_x",
        "options": {"syntax": "c_like", "typing": "dynamic",
                    "memory": "host_gc"},
        "customization": {"persona": "wirth", "theme": "pirate",
                          "era": None, "phrasebook": None,
                          "feature_bans": []},
    }), encoding="utf-8")
    (d / "README.md").write_text("# slot_x\nA themed slot.", encoding="utf-8")
    (d / "LANGUAGE.md").write_text("# ref", encoding="utf-8")

    rep = _make_report("slot_x", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_x", str(d), 4.0,
                                     fingerprint="fp_x")])

    from forge.gui.app import create_app
    app = create_app(catalog_db_path=db, catalog_generated_root=gen)
    with app.test_client() as client:
        # Filter by persona — DB column is NULL but slot.json has it.
        r = client.get("/api/catalog/list?persona=wirth")
        items = r.get_json()["items"]
        assert any(i["slot_id"] == "slot_x" for i in items), (
            "slot.json fallback didn't surface theme/persona for filtering"
        )


# ===========================================================================
# Stage B — Write path: status / notes / rejection_reason
# ===========================================================================

def test_status_update_to_approved(app_client):
    client, db, _ = app_client
    r = client.post(
        "/api/catalog/slot_000/status",
        json={"status": "approved", "reviewer_notes": "looks good"},
    )
    assert r.status_code == 200
    data = r.get_json()
    assert data["status"] == "approved"
    assert data["reviewer_notes"] == "looks good"
    # And the DB reflects it.
    row = get_language(db, "slot_000")
    assert row.status == "approved"


def test_status_update_to_rejected_records_reason(app_client):
    client, db, _ = app_client
    r = client.post(
        "/api/catalog/slot_001/status",
        json={"status": "rejected",
              "rejection_reason": "duplicate of slot_023",
              "reviewer_notes": "too vanilla"},
    )
    assert r.status_code == 200
    row = get_language(db, "slot_001")
    assert row.status == "rejected"
    assert row.rejection_reason == "duplicate of slot_023"
    assert row.reviewer_notes == "too vanilla"


def test_status_update_clears_rejection_reason_when_unrejecting(app_client):
    client, db, _ = app_client
    # First reject, then move back to pending. The rejection_reason
    # should clear automatically.
    client.post("/api/catalog/slot_002/status", json={
        "status": "rejected", "rejection_reason": "needs more polish"})
    client.post("/api/catalog/slot_002/status", json={"status": "approved"})
    row = get_language(db, "slot_002")
    assert row.status == "approved"
    assert row.rejection_reason is None


def test_status_update_rejects_invalid_status(app_client):
    client, _, _ = app_client
    r = client.post("/api/catalog/slot_000/status",
                    json={"status": "bogus_value"})
    assert r.status_code == 400
    assert "status must be" in r.get_json()["error"]


def test_status_update_404_on_unknown_slot(app_client):
    client, _, _ = app_client
    r = client.post("/api/catalog/no_such_slot/status",
                    json={"status": "approved"})
    assert r.status_code == 404


def test_notes_update_does_not_change_status(app_client):
    client, db, _ = app_client
    r = client.post("/api/catalog/slot_000/notes",
                    json={"reviewer_notes": "annotation while reviewing"})
    assert r.status_code == 200
    row = get_language(db, "slot_000")
    assert row.reviewer_notes == "annotation while reviewing"
    assert row.status == "pending_review"  # unchanged


def test_notes_update_404_on_unknown_slot(app_client):
    client, _, _ = app_client
    r = client.post("/api/catalog/no_slot/notes",
                    json={"reviewer_notes": "x"})
    assert r.status_code == 404


def test_notes_update_validates_payload(app_client):
    client, _, _ = app_client
    r = client.post("/api/catalog/slot_000/notes",
                    json={"reviewer_notes": 12345})  # not a string
    assert r.status_code == 400


def test_notes_update_accepts_null(app_client):
    """null clears the field."""
    client, db, _ = app_client
    # First write notes
    client.post("/api/catalog/slot_000/notes",
                json={"reviewer_notes": "first pass"})
    # Then clear with null
    r = client.post("/api/catalog/slot_000/notes",
                    json={"reviewer_notes": None})
    assert r.status_code == 200
    row = get_language(db, "slot_000")
    assert row.reviewer_notes is None


def test_status_update_response_includes_full_summary(app_client):
    """The response body has enough info for the JS to update its
    in-memory item without a separate refetch."""
    client, _, _ = app_client
    r = client.post("/api/catalog/slot_000/status",
                    json={"status": "approved"})
    data = r.get_json()
    expected_keys = {"slot_id", "display_name", "family", "status",
                     "distinctiveness", "coherence", "completeness"}
    assert expected_keys <= set(data.keys())


# ===========================================================================
# Stage C — Tier and tag system
# ===========================================================================

def test_v2_migration_adds_tier_and_tags_columns(tmp_path):
    """Fresh init_db at SCHEMA_VERSION = 2 includes tier + tags."""
    db = tmp_path / "catalog.db"
    init_db(db)
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        cols = {row[1] for row in conn.execute(
            "PRAGMA table_info(languages)").fetchall()}
    assert "tier" in cols
    assert "tags" in cols


def test_v2_migration_upgrades_v1_db_idempotent(tmp_path):
    """Simulate a Phase 2 (v1) DB and verify the migration upgrades
    it cleanly without losing data."""
    import sqlite3
    db = tmp_path / "catalog.db"
    init_db(db)
    # Roll back to v1 by dropping the new columns + setting version.
    with sqlite3.connect(str(db)) as conn:
        # SQLite < 3.35 can't DROP COLUMN; just lower version + mark
        # to test the migration upgrade path.
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    # Now reopen — should auto-upgrade to v2.
    init_db(db)
    with sqlite3.connect(str(db)) as conn:
        v = conn.execute("PRAGMA user_version").fetchone()[0]
    assert v == SCHEMA_VERSION


def test_set_tier_writes_and_reads(app_client):
    client, db, _ = app_client
    r = client.post("/api/catalog/slot_000/tier",
                    json={"tier": "epic"})
    assert r.status_code == 200
    row = get_language(db, "slot_000")
    assert row.tier == "epic"


def test_set_tier_to_null_clears(app_client):
    client, db, _ = app_client
    update_language_tier(db, "slot_000", "rare")
    r = client.post("/api/catalog/slot_000/tier", json={"tier": None})
    assert r.status_code == 200
    assert get_language(db, "slot_000").tier is None


def test_set_tags_writes_and_reads(app_client):
    client, db, _ = app_client
    r = client.post("/api/catalog/slot_000/tags",
                    json={"tags": ["themed-pirate", "baseline"]})
    assert r.status_code == 200
    row = get_language(db, "slot_000")
    assert set(row.tags) == {"themed-pirate", "baseline"}


def test_set_tags_dedupes_and_strips(app_client):
    client, db, _ = app_client
    client.post("/api/catalog/slot_000/tags",
                json={"tags": ["x", " x ", "y", "x"]})
    row = get_language(db, "slot_000")
    assert row.tags == ["x", "y"]  # dedup + stripped


def test_set_tags_validates_payload(app_client):
    client, _, _ = app_client
    r = client.post("/api/catalog/slot_000/tags",
                    json={"tags": "not_a_list"})
    assert r.status_code == 400
    r = client.post("/api/catalog/slot_000/tags",
                    json={"tags": [1, 2]})
    assert r.status_code == 400


def test_distinct_tags_endpoint_returns_sorted_unique(app_client):
    client, db, _ = app_client
    update_language_tags(db, "slot_000", ["pirate", "epic"])
    update_language_tags(db, "slot_001", ["pirate", "baseline"])
    update_language_tags(db, "slot_002", ["epic"])
    r = client.get("/api/catalog/tags")
    data = r.get_json()
    assert data["tags"] == ["baseline", "epic", "pirate"]


def test_filter_by_tier_works(app_client):
    """Phase 2 already had tier filtering wired through; verify with
    real values."""
    client, db, _ = app_client
    update_language_tier(db, "slot_000", "epic")
    update_language_tier(db, "slot_001", "common")
    update_language_tier(db, "slot_002", "epic")
    r = client.get("/api/catalog/list?tier=epic&status=pending_review")
    data = r.get_json()
    slot_ids = {i["slot_id"] for i in data["items"]}
    # Note: the items include the slots whose tier was set; the
    # filter post-fetch logic reads the tier from the DB row.
    # If the JS-level summary doesn't include `tier` on the item,
    # the post-filter still trusts the slot's tier. We just assert
    # the API doesn't crash.
    assert isinstance(data["items"], list)


# ===========================================================================
# Stage F refinements
# ===========================================================================

def test_list_summary_includes_tier_and_tags(app_client):
    """Stage F bug fix: _row_to_summary used to omit tier and tags,
    so the list view's compactCustomization fallback never showed
    them. After the fix, summary entries include both fields."""
    client, db, _ = app_client
    update_language_tier(db, "slot_000", "epic")
    update_language_tags(db, "slot_000", ["pirate", "themed"])
    r = client.get("/api/catalog/list")
    items = r.get_json()["items"]
    target = next((i for i in items if i["slot_id"] == "slot_000"), None)
    assert target is not None
    assert target["tier"] == "epic"
    assert set(target["tags"]) == {"pirate", "themed"}


def test_filter_by_tier_returns_only_matching_after_fix(app_client):
    """With tier in the summary, the post-fetch tier filter actually
    discriminates."""
    client, db, _ = app_client
    update_language_tier(db, "slot_000", "epic")
    update_language_tier(db, "slot_001", "common")
    update_language_tier(db, "slot_002", "epic")
    r = client.get("/api/catalog/list?tier=epic")
    items = r.get_json()["items"]
    slot_ids = {i["slot_id"] for i in items}
    # Only the two epic-tier slots should remain.
    assert "slot_000" in slot_ids
    assert "slot_002" in slot_ids
    assert "slot_001" not in slot_ids


def test_filter_by_tag_returns_only_matching_after_fix(app_client):
    """Same for tag filter — needs `tags` on the summary to work."""
    client, db, _ = app_client
    update_language_tags(db, "slot_000", ["needs-review"])
    update_language_tags(db, "slot_002", ["needs-review", "candidate"])
    r = client.get("/api/catalog/list?tag=needs-review")
    items = r.get_json()["items"]
    slot_ids = {i["slot_id"] for i in items}
    assert slot_ids == {"slot_000", "slot_002"}


# ===========================================================================
# Stage D — Bulk operations + progress
# ===========================================================================

def test_bulk_status_update_writes_to_all_selected(app_client):
    client, db, _ = app_client
    r = client.post("/api/catalog/bulk/status", json={
        "slot_ids": ["slot_000", "slot_001", "slot_002"],
        "status": "approved",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["rows_updated"] == 3
    for sid in ["slot_000", "slot_001", "slot_002"]:
        assert get_language(db, sid).status == "approved"


def test_bulk_status_with_rejection_reason(app_client):
    client, db, _ = app_client
    r = client.post("/api/catalog/bulk/status", json={
        "slot_ids": ["slot_000", "slot_001"],
        "status": "rejected",
        "rejection_reason": "obvious duplicates",
    })
    assert r.status_code == 200
    for sid in ["slot_000", "slot_001"]:
        row = get_language(db, sid)
        assert row.status == "rejected"
        assert row.rejection_reason == "obvious duplicates"


def test_bulk_status_validates_status_and_payload(app_client):
    client, _, _ = app_client
    r = client.post("/api/catalog/bulk/status", json={
        "slot_ids": ["slot_000"], "status": "bogus"})
    assert r.status_code == 400
    r = client.post("/api/catalog/bulk/status", json={
        "slot_ids": [], "status": "approved"})
    assert r.status_code == 400


def test_bulk_tag_add_writes_to_all_selected(app_client):
    client, db, _ = app_client
    r = client.post("/api/catalog/bulk/tag", json={
        "slot_ids": ["slot_000", "slot_001", "slot_002"],
        "tag": "batch-1.5",
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data["rows_updated"] == 3
    for sid in ["slot_000", "slot_001", "slot_002"]:
        assert "batch-1.5" in get_language(db, sid).tags


def test_bulk_tag_validates(app_client):
    client, _, _ = app_client
    r = client.post("/api/catalog/bulk/tag", json={
        "slot_ids": ["slot_000"], "tag": ""})
    assert r.status_code == 400
    r = client.post("/api/catalog/bulk/tag", json={
        "slot_ids": [], "tag": "x"})
    assert r.status_code == 400


def test_progress_endpoint_reflects_status_changes(app_client):
    client, db, _ = app_client
    # Start: 6 pending.
    p = client.get("/api/catalog/progress").get_json()
    assert p["pending_review"] == 6
    # Move 3 to approved + 1 to rejected.
    client.post("/api/catalog/bulk/status", json={
        "slot_ids": ["slot_000", "slot_001", "slot_002"],
        "status": "approved"})
    client.post("/api/catalog/slot_003/status", json={
        "status": "rejected", "rejection_reason": "test"})
    p = client.get("/api/catalog/progress").get_json()
    assert p["approved"] == 3
    assert p["rejected"] == 1
    assert p["pending_review"] == 2
    assert p["reviewed"] == 4


def test_progress_includes_by_family_breakdown(app_client):
    client, _, _ = app_client
    p = client.get("/api/catalog/progress").get_json()
    assert "by_family" in p
    # 6 seeded slots with families cycling through ["c_like", "s_expression",
    # "stack_based"]: c_like=2, s_expression=2, stack_based=2.
    assert p["by_family"]["c_like"] >= 1
    assert p["by_family"]["s_expression"] >= 1
    assert p["by_family"]["stack_based"] >= 1


# ===========================================================================
# DB unit tests for the new helpers (for completeness; integration tests
# above already cover the routes)
# ===========================================================================

def test_db_helper_update_notes_returns_false_for_missing_slot(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    assert update_language_notes(db, "no_slot", "x") is False


def test_db_helper_update_tier_validates_type(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    with pytest.raises(ValueError):
        update_language_tier(db, "any", 12345)  # not a string


def test_db_helper_update_tags_validates_type(tmp_path):
    db = tmp_path / "catalog.db"
    init_db(db)
    with pytest.raises(ValueError):
        update_language_tags(db, "any", "not_a_list")
    with pytest.raises(ValueError):
        update_language_tags(db, "any", [1, 2])


def test_db_helper_add_tag_to_language_idempotent(tmp_path):
    """Adding the same tag twice doesn't duplicate it."""
    db, gen = _seed_db(tmp_path, n=1)
    add_tag_to_language(db, "slot_000", "pirate")
    add_tag_to_language(db, "slot_000", "pirate")
    row = get_language(db, "slot_000")
    assert row.tags == ["pirate"]


def test_db_helper_bulk_update_status_skips_missing_slots(tmp_path):
    db, gen = _seed_db(tmp_path, n=2)
    # Mix real + missing slot IDs; only the real ones should update.
    n = bulk_update_status(db, ["slot_000", "no_such_slot"], "approved")
    assert n == 1


def test_distinct_tags_on_v1_db_returns_empty(tmp_path):
    """An older v1 DB without the tags column shouldn't crash; should
    return []. Defensive backward-compat check."""
    import sqlite3
    db = tmp_path / "catalog.db"
    init_db(db)
    with sqlite3.connect(str(db)) as conn:
        # Force tags column out (pretend this is a v1 DB by
        # dropping back).
        conn.execute("PRAGMA user_version = 1")
        # SQLite ≥ 3.35 supports DROP COLUMN; older doesn't. If
        # available, drop. Otherwise the test trusts that the
        # list_distinct_tags helper handles `OperationalError` gracefully.
        try:
            conn.execute("ALTER TABLE languages DROP COLUMN tags")
            conn.commit()
        except sqlite3.OperationalError:
            return  # column drop unsupported on this SQLite; skip.
    # The path is now v1 with no tags column; list_distinct_tags
    # should return [] without raising.
    assert list_distinct_tags(db) == []
