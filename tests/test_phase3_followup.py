"""Phase 3 follow-up — regression tests for the five friction-fix items.

Pins:
  Item 1 — detail JSON includes canonical_summary + canonical_tests
           (per-test source/expected) read from <lang_dir>/tests/.
  Item 2 — detail JSON includes kata_pack read from
           <lang_dir>/katas.json. The "Open in kata workspace" link
           uses ?lang=<id>&view=kata.
  Item 3 — backfill_customization_from_plan() rehydrates DB columns
           from the original slot plan when both DB and slot.json
           are NULL. Facets endpoint surfaces the backfilled values.
  Item 4 — clicking a row in the catalog list updates STATE.
           selectedIndex (covered by static-source assertion since
           we don't run a JS engine in the test suite).
  Item 5 — Detail JSON exposes lang_dir_exists so the launch button
           can disable for missing dirs. The deep-link handler at
           the bottom of app.js wires ?lang=&view= to the existing
           openInPlayground / kata workspace.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge.catalog.db import (
    STATUS_PENDING, backfill_customization_from_plan,
    get_language, init_db, insert_batch_result, list_languages,
)
from forge.catalog.dedup import DedupResult
from forge.catalog.quality import (
    CompletenessResult, CorrectnessResult, CoherenceResult,
    DistinctivenessResult, QualityReport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_lang_dir(parent: Path, slot_id: str, *,
                   family: str = "c_like",
                   include_tests: bool = True,
                   include_kata_pack: bool = True,
                   theme: str | None = None) -> Path:
    d = parent / slot_id
    d.mkdir(parents=True, exist_ok=True)
    spec = {
        "lang_name": slot_id, "display_name": slot_id,
        "options": {"syntax": family, "typing": "dynamic", "memory": "host_gc"},
        "customization": {"theme": theme, "persona": None, "era": None,
                          "phrasebook": None, "feature_bans": []},
    }
    (d / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8")
    (d / "generation_summary.json").write_text(
        json.dumps({"lang_name": slot_id, "pipeline_path": "templated"},
                   indent=2), encoding="utf-8")
    (d / "README.md").write_text(f"# {slot_id}\n\nA fixture language.\n",
                                  encoding="utf-8")
    (d / "LANGUAGE.md").write_text("# ref\nReference doc.\n",
                                    encoding="utf-8")

    if include_tests:
        tests = d / "tests"
        tests.mkdir(exist_ok=True)
        for name, source, expected in [
            ("hello_world", 'print("hello, world!");\n', "hello, world!\n"),
            ("arithmetic", "var x = 1 + 1;\nprint(x);\n", "2\n"),
            ("variables", "var a = 5;\nprint(a);\n", "5\n"),
            ("conditionals", 'if (true) { print("yes"); }\n', "yes\n"),
            ("loops", "var i = 0;\nwhile (i < 3) { i = i + 1; }\nprint(i);\n", "3\n"),
            ("functions", "func f() { return 42; }\nprint(f());\n", "42\n"),
            ("strings", 'print("abc");\n', "abc\n"),
            ("closures", "func mk() { var c = 0; return c; }\nprint(mk());\n", "0\n"),
        ]:
            (tests / f"{name}.toy").write_text(source, encoding="utf-8")
            (tests / f"{name}.expected_output.txt").write_text(
                expected, encoding="utf-8")

    if include_kata_pack:
        (d / "katas.json").write_text(json.dumps({
            "lang": slot_id,
            "katas": [
                {
                    "id": "two_sum", "title": "Two Sum",
                    "difficulty": "easy",
                    "problem": "Given a list and a target, return two indices.",
                    "function_name": "two_sum",
                    "starter_code": "func two_sum() {}\n",
                    "reference_solution": "func two_sum() { return list(0,1); }\n",
                    "tests": [
                        {"call": "two_sum(list(2,7), 9)", "expected": "[0, 1]"},
                        {"call": "two_sum(list(3,3), 6)", "expected": "[0, 1]"},
                    ],
                },
                {
                    "id": "reverse_list", "title": "Reverse",
                    "difficulty": "easy",
                    "problem": "Reverse a list.",
                    "function_name": "reverse",
                    "starter_code": "", "reference_solution": "",
                    "tests": [{"call": "reverse(list(1,2,3))",
                               "expected": "[3, 2, 1]"}],
                },
            ],
            "dropped": [],
        }, indent=2), encoding="utf-8")
    return d


def _make_report(slot_id: str, lang_dir: Path, *,
                 family: str = "c_like",
                 canonical_passed: int = 8,
                 canonical_total: int = 8) -> QualityReport:
    return QualityReport(
        slot_id=slot_id,
        lang_dir=str(lang_dir.resolve()),
        family=family,
        pipeline_path="templated",
        correctness=CorrectnessResult(
            passed=(canonical_passed == canonical_total),
            canonical_tests={"passed": canonical_passed,
                             "total": canonical_total,
                             "pass_rate": canonical_passed / canonical_total,
                             "source": "fixture"},
            kata_pack=None,
            repl={"repl_html_ok": True, "compile_exit_code": 0,
                  "launches": True},
            failures=[] if canonical_passed == canonical_total
                     else [f"canonical: {canonical_passed}/{canonical_total} passed"],
            skips=[],
        ),
        distinctiveness=DistinctivenessResult(
            score=0.5, surface=0.5, persona=0.5, variety=0.5, notes=[]),
        coherence=CoherenceResult(
            score=1.0, overrides_unique=True, readme_mentions_name=True,
            readme_length_ok=True, stdlib_naming_consistent=True, notes=[]),
        completeness=CompletenessResult(score=1.0, present=[], missing=[]),
        overall_passed=(canonical_passed == canonical_total),
        rejection_reason=None,
        scored_at="2026-05-08T00:00:00Z",
    )


@pytest.fixture
def app_client_with_artifacts(tmp_path):
    """Build a Flask test client whose catalog_db is seeded with rows
    that have full lang_dir artifacts (canonical tests + kata pack)."""
    gen = tmp_path / "generated"
    gen.mkdir(parents=True, exist_ok=True)
    db = tmp_path / "catalog.db"
    reports = []
    dedup = []
    for sid in ["slot_001", "slot_002", "slot_003"]:
        d = _make_lang_dir(gen, sid)
        reports.append(_make_report(sid, d))
        dedup.append(DedupResult(sid, str(d), 4.0, fingerprint=f"fp_{sid}"))
    insert_batch_result(db, gen, "plan.json", reports, dedup)
    from forge.gui.app import create_app
    app = create_app(catalog_db_path=db, catalog_generated_root=gen)
    with app.test_client() as client:
        yield client, db, gen


# ===========================================================================
# Item 1 — Canonical test results in detail view
# ===========================================================================

def test_detail_includes_canonical_summary(app_client_with_artifacts):
    client, _, _ = app_client_with_artifacts
    r = client.get("/api/catalog/slot_001")
    assert r.status_code == 200
    data = r.get_json()
    assert "canonical_summary" in data
    summary = data["canonical_summary"]
    assert summary["passed"] == 8
    assert summary["total"] == 8


def test_detail_includes_canonical_tests_with_source_and_expected(
        app_client_with_artifacts):
    client, _, _ = app_client_with_artifacts
    r = client.get("/api/catalog/slot_001")
    data = r.get_json()
    tests = data["canonical_tests"]
    assert isinstance(tests, list)
    # The 8 canonical tests we wrote in the fixture.
    assert len(tests) == 8
    # hello_world should be first (sort priority).
    assert tests[0]["name"] == "hello_world"
    # Every test has source + expected.
    for t in tests:
        assert "source" in t and t["source"]
        assert "expected" in t


def test_detail_canonical_tests_empty_when_no_tests_dir(tmp_path):
    """If a generated language has no tests/ dir, canonical_tests
    is an empty list (not an error)."""
    gen = tmp_path / "generated"; gen.mkdir()
    d = _make_lang_dir(gen, "slot_x", include_tests=False)
    db = tmp_path / "catalog.db"
    rep = _make_report("slot_x", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_x", str(d), 4.0,
                                     fingerprint="fp")])
    from forge.gui.app import create_app
    app = create_app(catalog_db_path=db, catalog_generated_root=gen)
    with app.test_client() as client:
        r = client.get("/api/catalog/slot_x")
        assert r.get_json()["canonical_tests"] == []


# ===========================================================================
# Item 2 — Kata pack inline
# ===========================================================================

def test_detail_includes_kata_pack(app_client_with_artifacts):
    client, _, _ = app_client_with_artifacts
    r = client.get("/api/catalog/slot_001")
    data = r.get_json()
    pack = data["kata_pack"]
    assert pack is not None
    assert "katas" in pack
    assert len(pack["katas"]) == 2
    # Each kata has the fields the detail view shows.
    k = pack["katas"][0]
    for field in ("id", "title", "difficulty", "problem", "tests"):
        assert field in k


def test_detail_kata_pack_is_null_when_missing(tmp_path):
    """Languages without katas.json get kata_pack=None (not an error)."""
    gen = tmp_path / "generated"; gen.mkdir()
    d = _make_lang_dir(gen, "slot_x", include_kata_pack=False)
    db = tmp_path / "catalog.db"
    rep = _make_report("slot_x", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_x", str(d), 4.0,
                                     fingerprint="fp")])
    from forge.gui.app import create_app
    app = create_app(catalog_db_path=db, catalog_generated_root=gen)
    with app.test_client() as client:
        r = client.get("/api/catalog/slot_x")
        assert r.get_json()["kata_pack"] is None


# ===========================================================================
# Item 3 — Backfill customization from slot plan
# ===========================================================================

def test_backfill_fills_null_columns(tmp_path):
    """The core fix: a row with NULL theme/phrasebook gets filled
    in from the slot plan."""
    gen = tmp_path / "generated"; gen.mkdir()
    d = _make_lang_dir(gen, "slot_007", theme=None)  # NULL in resolved spec
    db = tmp_path / "catalog.db"
    rep = _make_report("slot_007", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_007", str(d), 4.0,
                                     fingerprint="fp")])

    # Pre-backfill: theme is NULL.
    pre = get_language(db, "slot_007")
    assert pre.theme is None

    # Build a plan file pointing slot_007 to theme=pirate.
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([
        {"slot_id": "slot_007",
         "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
         "customization": {"theme": "pirate", "persona": "stroustrup",
                           "era": "1980s", "phrasebook": None,
                           "feature_bans": []}},
    ]), encoding="utf-8")

    result = backfill_customization_from_plan(db, plan)
    assert result["updated"] == 1
    post = get_language(db, "slot_007")
    assert post.theme == "pirate"
    assert post.persona == "stroustrup"
    assert post.era == "1980s"


def test_backfill_does_not_overwrite_by_default(tmp_path):
    """A row that already has persona set keeps it unchanged unless
    overwrite=True."""
    gen = tmp_path / "generated"; gen.mkdir()
    d = _make_lang_dir(gen, "slot_x")
    db = tmp_path / "catalog.db"
    rep = _make_report("slot_x", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_x", str(d), 4.0, fingerprint="fp")])
    # Set persona manually so it's non-NULL.
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE languages SET persona = 'wirth' WHERE slot_id = 'slot_x'")
        conn.commit()

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([
        {"slot_id": "slot_x",
         "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
         "customization": {"persona": "stroustrup",
                           "era": "1990s", "theme": None,
                           "phrasebook": None, "feature_bans": []}},
    ]), encoding="utf-8")

    # Without overwrite: persona stays 'wirth' (already set), era gets filled.
    backfill_customization_from_plan(db, plan, overwrite=False)
    row = get_language(db, "slot_x")
    assert row.persona == "wirth"
    assert row.era == "1990s"


def test_backfill_overwrites_when_requested(tmp_path):
    gen = tmp_path / "generated"; gen.mkdir()
    d = _make_lang_dir(gen, "slot_x")
    db = tmp_path / "catalog.db"
    rep = _make_report("slot_x", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_x", str(d), 4.0, fingerprint="fp")])
    import sqlite3
    with sqlite3.connect(str(db)) as conn:
        conn.execute("UPDATE languages SET persona = 'wirth' WHERE slot_id = 'slot_x'")
        conn.commit()

    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([
        {"slot_id": "slot_x",
         "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
         "customization": {"persona": "stroustrup", "era": None,
                           "theme": None, "phrasebook": None,
                           "feature_bans": []}},
    ]), encoding="utf-8")
    backfill_customization_from_plan(db, plan, overwrite=True)
    row = get_language(db, "slot_x")
    assert row.persona == "stroustrup"


def test_backfill_ignores_rows_not_in_plan(tmp_path):
    """A row whose slot_id isn't in the plan file is skipped (logged
    as `skipped_no_match`) rather than erroring."""
    gen = tmp_path / "generated"; gen.mkdir()
    d = _make_lang_dir(gen, "slot_orphan")
    db = tmp_path / "catalog.db"
    rep = _make_report("slot_orphan", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_orphan", str(d), 4.0,
                                     fingerprint="fp")])
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([]), encoding="utf-8")  # empty plan
    result = backfill_customization_from_plan(db, plan)
    assert result["updated"] == 0
    assert result["skipped_no_match"] == 1


def test_facets_endpoint_picks_up_backfilled_values(
        tmp_path):
    """End-to-end: backfill writes themes to DB, facets endpoint
    surfaces them in the dropdown payload."""
    gen = tmp_path / "generated"; gen.mkdir()
    d = _make_lang_dir(gen, "slot_007", theme=None)
    db = tmp_path / "catalog.db"
    rep = _make_report("slot_007", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_007", str(d), 4.0,
                                     fingerprint="fp")])
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([
        {"slot_id": "slot_007",
         "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
         "customization": {"theme": "pirate", "phrasebook": "pirate",
                           "persona": "stroustrup", "era": "1980s",
                           "feature_bans": []}},
    ]), encoding="utf-8")
    backfill_customization_from_plan(db, plan)

    from forge.gui.app import create_app
    app = create_app(catalog_db_path=db, catalog_generated_root=gen)
    with app.test_client() as client:
        r = client.get("/api/catalog/facets")
        facets = r.get_json()
        assert "pirate" in facets["themes"]
        assert "pirate" in facets["phrasebooks"]
        assert "stroustrup" in facets["personas"]
        assert "1980s" in facets["eras"]


def test_backfill_cli_returns_0_on_success(tmp_path):
    from forge.catalog.backfill import _main
    gen = tmp_path / "generated"; gen.mkdir()
    d = _make_lang_dir(gen, "slot_x")
    db = tmp_path / "catalog.db"
    rep = _make_report("slot_x", d)
    insert_batch_result(db, gen, "plan.json", [rep],
                        [DedupResult("slot_x", str(d), 4.0,
                                     fingerprint="fp")])
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps([{"slot_id": "slot_x",
        "options": {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "customization": {"theme": "cozy"}}]), encoding="utf-8")
    rc = _main(["--db", str(db), "--plan", str(plan)])
    assert rc == 0
    assert get_language(db, "slot_x").theme == "cozy"


def test_backfill_cli_returns_2_on_missing_files(tmp_path):
    from forge.catalog.backfill import _main
    rc = _main(["--db", str(tmp_path / "no_db"),
                "--plan", str(tmp_path / "no_plan")])
    assert rc == 2


# ===========================================================================
# Item 4 — Click handler syncs keyboard cursor (verified at source level)
# ===========================================================================

def test_catalog_js_click_handler_syncs_selectedindex():
    """Item 4 is a 2-line frontend fix; we don't run JS in the test
    suite. But we can assert the source of catalog.js has the fix
    (the click handler must update STATE.selectedIndex before opening
    detail). This pins that the fix doesn't get reverted accidentally."""
    js = (Path(__file__).resolve().parents[1] / "forge" / "gui"
          / "static" / "catalog.js").read_text(encoding="utf-8")
    # The click handler that invokes openDetailByIndex must precede
    # it with an assignment to STATE.selectedIndex from the same idx.
    # Match a small window around the row click handler.
    import re
    m = re.search(
        r'row\.addEventListener\("click",\s*\(\)\s*=>\s*\{\s*'
        r'STATE\.selectedIndex\s*=\s*idx;\s*'
        r'openDetailByIndex\(idx\);\s*\}\s*\);',
        js,
    )
    assert m is not None, (
        "row click handler in catalog.js does not sync STATE."
        "selectedIndex with the clicked row's idx; this regression "
        "would re-introduce the cursor-vs-click desync from Phase 3 "
        "validation."
    )


# ===========================================================================
# Item 5 — Launch REPL deep-link
# ===========================================================================

def test_app_js_handles_lang_query_param():
    """The deep-link handler at the bottom of app.js must read
    ?lang=<slot_id>&view=playground|kata and route to the existing
    openInPlayground / kata-tab switching."""
    js = (Path(__file__).resolve().parents[1] / "forge" / "gui"
          / "static" / "app.js").read_text(encoding="utf-8")
    # Look for the handleDeepLink IIFE.
    assert "handleDeepLink" in js, (
        "app.js missing the handleDeepLink IIFE; ?lang= deep links "
        "from the catalog UI's Launch REPL button won't work"
    )
    # And the URLSearchParams read.
    assert "URLSearchParams(location.search)" in js
    # Both view names accepted.
    assert "view === 'kata' || view === 'katas'" in js


def test_catalog_js_renders_launch_buttons():
    """The catalog.js `renderLaunchRepl` function should generate the
    /?lang=...&view=playground link."""
    js = (Path(__file__).resolve().parents[1] / "forge" / "gui"
          / "static" / "catalog.js").read_text(encoding="utf-8")
    assert "renderLaunchRepl" in js
    assert "view=playground" in js
    assert "view=kata" in js


def test_catalog_index_html_loads_launch_buttons_section():
    """catalog.html doesn't need a static launch-buttons block — the
    section is injected by ensureSection() at render time. Pin that
    catalog.js exports that helper."""
    js = (Path(__file__).resolve().parents[1] / "forge" / "gui"
          / "static" / "catalog.js").read_text(encoding="utf-8")
    assert "ensureSection" in js


def test_lang_dir_exists_flag_in_detail(app_client_with_artifacts):
    """The detail JSON's lang_dir_exists flag is what the launch
    button binds to (disable when missing)."""
    client, _, _ = app_client_with_artifacts
    r = client.get("/api/catalog/slot_001")
    data = r.get_json()
    assert "lang_dir_exists" in data
    assert data["lang_dir_exists"] is True
