"""Phase 3: catalog curation routes for the Forge GUI.

# WHAT THIS DOES

Mounts a set of `/catalog` and `/api/catalog/...` routes onto the
existing Flask app for browsing and triaging Phase 2's catalog DB.
A separate module (rather than appending to `app.py`'s already-2150-line
file) so the curation work has a clean home.

The routes are read-mostly in Stage A; Stage B adds writes; Stage C
adds the tier/tag system; Stage D adds bulk operations.

# WIRE-UP

`forge/gui/app.py:create_app()` calls
`mount_catalog_routes(app, catalog_db_path=...)` once. The DB path
defaults to `<workspace>/catalog.db` but can be overridden so tests
use temp DBs.

# WHAT WE READ FROM

- The Phase 2 catalog DB (forge.catalog.db) — `languages` rows,
  duplicates, batches.
- `generated/<slot_id>/slot.json` for fields the resolver normalized
  away (theme, era, persona may be NULL in DB rows because the
  resolver consumed them; the original slot.json keeps them).
- `generated/<slot_id>/README.md`, `LANGUAGE.md` for inline rendering.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from flask import Flask, Response, abort, jsonify, request, send_from_directory


# Directory containing this module — used to serve the catalog HTML/JS/CSS.
_HERE = Path(__file__).resolve().parent
_WORKSPACE = _HERE.parents[1]


# ---------------------------------------------------------------------------
# Helpers: row enrichment with slot.json fields the resolver normalized away
# ---------------------------------------------------------------------------

def _resolve_lang_dir(slot_id: str, generated_root: Path,
                      db_path: Path) -> Path:
    """Resolve the on-disk path to a generated language's directory.

    Phase 3 follow-up bug: the curation UI was assuming `generated_root
    / slot_id` (typically `<workspace>/<slot_id>/`) but Phase 2 batches
    actually live at `<workspace>/catalog_raw_gate2_v2/<slot_id>/` (or
    wherever `python -m forge.catalog.curate --input <dir>` was pointed
    at). The DB's `batches.output_dir` records the right path; we look
    it up per-slot via the row's batch_id.

    Resolution order:
      1. If the language row's batch's output_dir + slot_id exists, use that.
      2. Otherwise fall back to generated_root / slot_id (the legacy
         path that works when curation runs from the workspace itself).
    """
    try:
        from forge.catalog import db as catalog_db
        row = catalog_db.get_language(db_path, slot_id)
        if row is not None and row.batch_id is not None:
            batch = catalog_db.get_batch(db_path, row.batch_id)
            if batch is not None:
                candidate = Path(batch.output_dir) / slot_id
                if candidate.exists():
                    return candidate
    except Exception:
        pass
    return generated_root / slot_id


def _read_slot_json(lang_dir: Path) -> Optional[dict]:
    """Phase 2's instructions called this out specifically: theme/era/
    persona may be NULL in DB rows because the resolver normalizes them
    into keyword_overrides + creative output. The original `slot.json`
    (copied next to each generated language by `_copy_slot_json` in
    runner.py) keeps the user's input. We read it lazily when the UI
    needs filterable customization fields.

    Returns None if slot.json doesn't exist (caller falls back to
    whatever the DB row says).

    Phase 3 follow-up: takes a resolved lang_dir directly rather than
    composing one from generated_root + slot_id.
    """
    p = lang_dir / "slot.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _customization_for_row(row, generated_root: Path,
                           db_path: Optional[Path] = None) -> dict:
    """Resolve the user-facing customization fields for a row, falling
    back to slot.json when the DB row's columns are NULL."""
    persona = row.persona
    era = row.era
    theme = row.theme
    phrasebook = row.phrasebook
    if persona is None or era is None or theme is None or phrasebook is None:
        if db_path is not None:
            lang_dir = _resolve_lang_dir(row.slot_id, generated_root, db_path)
        else:
            lang_dir = generated_root / row.slot_id
        sj = _read_slot_json(lang_dir)
        if sj:
            cust = sj.get("customization") or {}
            persona = persona or cust.get("persona")
            era = era or cust.get("era")
            theme = theme or cust.get("theme")
            phrasebook = phrasebook or cust.get("phrasebook")
    return {
        "persona": persona, "era": era,
        "theme": theme, "phrasebook": phrasebook,
        "feature_bans": row.feature_bans,
    }


def _quality_summary(row) -> dict:
    """Extract a compact view of the quality report for list-view
    display. The full report is in `quality_report_json`; this is the
    pre-parsed subset that goes into list rows."""
    try:
        qr = json.loads(row.quality_report_json or "{}")
    except Exception:
        return {
            "distinctiveness": None, "coherence": None,
            "completeness": None, "correctness_passed": None,
        }
    return {
        "distinctiveness": (qr.get("distinctiveness") or {}).get("score"),
        "coherence": (qr.get("coherence") or {}).get("score"),
        "completeness": (qr.get("completeness") or {}).get("score"),
        "correctness_passed": (qr.get("correctness") or {}).get("passed"),
    }


def _row_to_summary(row, generated_root: Path,
                    db_path: Optional[Path] = None) -> dict:
    """Compact dict suitable for the list view.

    Phase 3 Stage F refinement: surface `tier` and `tags` on the
    summary so the list view's compact-customization line can show
    them, and so the JS-level tier/tag filters can match without
    refetching the full row."""
    cust = _customization_for_row(row, generated_root, db_path)
    quality = _quality_summary(row)
    return {
        "slot_id": row.slot_id,
        "display_name": row.display_name,
        "family": row.family,
        "typing": row.typing,
        "memory": row.memory,
        "persona": cust["persona"],
        "era": cust["era"],
        "theme": cust["theme"],
        "phrasebook": cust["phrasebook"],
        "feature_bans": cust["feature_bans"],
        "pipeline_path": row.pipeline_path,
        "status": row.status,
        "rejection_reason": row.rejection_reason,
        "reviewer_notes": row.reviewer_notes,
        "added_at": row.added_at,
        "distinctiveness": quality["distinctiveness"],
        "coherence": quality["coherence"],
        "completeness": quality["completeness"],
        "correctness_passed": quality["correctness_passed"],
        "tier": getattr(row, "tier", None),
        "tags": list(getattr(row, "tags", []) or []),
    }


def _read_canonical_tests(lang_dir: Path) -> list[dict]:
    """Phase 3 follow-up Item 1: surface canonical test results in
    the detail view. Reads the language's `tests/` directory and
    pairs each test source with its expected output and (if present)
    its `.out.py` actual output from the most recent run.

    Returns a list of dicts with `name`, `source`, `expected`,
    `actual`, and `passed` (best-effort — a test only counts as
    'passed' if the actual output exists and matches expected).

    Caps each output at ~80 lines / 4KB so the detail view stays
    fast to render even on tests that print megabytes."""
    tests_dir = lang_dir / "tests"
    if not tests_dir.exists() or not tests_dir.is_dir():
        return []
    out: list[dict] = []
    # Group files by stem: <name>.<ext>, <name>.expected_output.txt,
    # <name>.<ext>.out.py
    sources: dict[str, dict] = {}
    for entry in sorted(tests_dir.iterdir()):
        if not entry.is_file():
            continue
        name = entry.name
        if name.endswith(".expected_output.txt"):
            stem = name[: -len(".expected_output.txt")]
            sources.setdefault(stem, {})["expected_path"] = entry
        elif name.endswith(".out.py"):
            # Strip .<ext>.out.py to get the source stem.
            stem = entry.stem
            if stem.endswith(".out"):
                stem = stem[:-len(".out")]
            stem_no_ext = entry.name.rsplit(".", 2)[0]
            sources.setdefault(stem_no_ext, {})["actual_path"] = entry
        else:
            stem = entry.stem
            sources.setdefault(stem, {})["source_path"] = entry
    for stem, paths in sources.items():
        if "source_path" not in paths:
            continue
        try:
            source = paths["source_path"].read_text(
                encoding="utf-8", errors="replace")[:4096]
        except Exception:
            source = ""
        expected = ""
        if "expected_path" in paths:
            try:
                expected = paths["expected_path"].read_text(
                    encoding="utf-8", errors="replace")
            except Exception:
                expected = ""
        # Cap displayed output at 80 lines.
        if expected.count("\n") > 80:
            expected = "\n".join(expected.splitlines()[:80]) + "\n..."
        # Whether this test ran successfully isn't preserved on disk
        # in a structured way; the canonical_tests aggregate count in
        # generation_summary covers it. We surface the aggregate via
        # a separate field; the per-test entries here are for "let
        # the curator read what the language ACTUALLY does".
        out.append({
            "name": stem,
            "source": source,
            "expected": expected,
        })
    # Sort with hello_world first (the canonical "does it run?" test),
    # then alphabetical.
    out.sort(key=lambda t: (t["name"] != "hello_world", t["name"]))
    return out


def _read_kata_pack(lang_dir: Path) -> Optional[dict]:
    """Phase 3 follow-up Item 2: surface the kata pack inline in the
    detail view. Reads `<lang_dir>/katas.json` if present (that's
    where the kata pipeline persists curated/translated katas).
    Returns the pack dict or None if missing.

    The pack's full contents — including reference solutions — are
    included so the detail view can show the curator what the
    language is being asked to do, with what test cases."""
    kata_path = lang_dir / "katas.json"
    if not kata_path.exists():
        return None
    try:
        return json.loads(kata_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _row_to_detail(row, generated_root: Path,
                   db_path: Optional[Path] = None) -> dict:
    """Full detail dict for the per-language view. Includes full
    quality report, parsed spec, README + LANGUAGE.md content (for
    inline rendering), file list, and the original slot.json.

    Phase 3 follow-up bug fix: resolve the lang_dir from the row's
    batch's output_dir (the actual on-disk location) rather than
    assuming `generated_root / slot_id`. The default generated_root
    is `<workspace>/`, but Phase 1.5 batches live at
    `<workspace>/catalog_raw_gate2_v2/<slot_id>/` — using the batch's
    output_dir resolves correctly without requiring the user to
    pass --catalog-generated-root.
    """
    summary = _row_to_summary(row, generated_root, db_path)
    try:
        spec = json.loads(row.resolved_spec_json or "{}")
    except Exception:
        spec = {}
    try:
        gen_summary = json.loads(row.generation_summary_json or "{}")
    except Exception:
        gen_summary = {}
    try:
        quality_report = json.loads(row.quality_report_json or "{}")
    except Exception:
        quality_report = {}

    # Resolve the actual on-disk path for this language.
    if db_path is not None:
        lang_dir = _resolve_lang_dir(row.slot_id, generated_root, db_path)
    else:
        lang_dir = generated_root / row.slot_id

    slot_json = _read_slot_json(lang_dir) or {}

    # Phase 3 follow-up: if the lang_dir is missing or empty (e.g.
    # the source files were lost from disk but the DB still has the
    # spec snapshot), fall back to the spec's creative.readme_intro +
    # origin_story so the curator has SOMETHING to read. Better than
    # showing "(README.md missing)" with no context.
    fallback_readme = ""
    creative_block = (spec.get("creative") or {})
    if isinstance(creative_block, dict):
        readme_intro = creative_block.get("readme_intro") or ""
    else:
        readme_intro = str(creative_block) if creative_block else ""
    origin_story = spec.get("origin_story") or ""
    if readme_intro or origin_story:
        parts = []
        if readme_intro:
            parts.append("# README intro (from spec)\n\n" + readme_intro.strip())
        if origin_story:
            parts.append("\n## Origin story\n\n" + origin_story.strip())
        fallback_readme = "\n\n".join(parts).strip() + "\n"

    # Read README and LANGUAGE.md content if present.
    readme_text = ""
    language_md_text = ""
    file_list: list[dict] = []
    if lang_dir.exists() and lang_dir.is_dir():
        for fn in ("README.md", "LANGUAGE.md", "INSTALL.md"):
            fp = lang_dir / fn
            if fp.exists():
                try:
                    text = fp.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    text = ""
                if fn == "README.md":
                    readme_text = text
                elif fn == "LANGUAGE.md":
                    language_md_text = text
        # File listing for the detail view (size + line count).
        for entry in sorted(lang_dir.iterdir()):
            if entry.is_file():
                try:
                    size = entry.stat().st_size
                    if entry.suffix in (".py", ".md", ".css", ".html",
                                        ".json", ".txt", ".toml"):
                        line_count = sum(
                            1 for _ in entry.open(encoding="utf-8",
                                                  errors="replace")
                        )
                    else:
                        line_count = None
                except Exception:
                    size = None
                    line_count = None
                file_list.append({
                    "name": entry.name,
                    "size_bytes": size,
                    "line_count": line_count,
                    "type": "file",
                })
            elif entry.is_dir() and entry.name not in ("__pycache__",
                                                        ".forge_log"):
                # One-level directory listing — useful for tests/, examples/.
                try:
                    children = sum(1 for c in entry.iterdir() if c.is_file())
                except Exception:
                    children = 0
                file_list.append({
                    "name": entry.name + "/",
                    "size_bytes": None,
                    "line_count": children,
                    "type": "dir",
                })

    # Phase 3 follow-up Item 1: canonical test results visible in
    # detail view. The aggregate (8/8 passed) comes from the quality
    # report's correctness block; per-test source + expected come from
    # _read_canonical_tests. The curator gets both at-a-glance pass
    # rate and "let me see what this language actually does" content.
    canonical_summary = (quality_report.get("correctness") or {}).get(
        "canonical_tests") or {}
    canonical_tests = _read_canonical_tests(lang_dir)

    # Phase 3 follow-up Item 2: kata pack inline. Surface the curated
    # katas.json so the curator can see what problems the language
    # was asked to solve, with what tests, without leaving the
    # detail view.
    kata_pack = _read_kata_pack(lang_dir)

    # If on-disk README is missing/empty, swap in the spec-derived
    # fallback so the curator still has something to read.
    effective_readme = readme_text if readme_text.strip() else fallback_readme

    # readme_source flag tells the frontend whether to label the
    # rendering as on-disk or recovered from the DB spec.
    readme_source = (
        "on_disk" if readme_text.strip()
        else ("db_spec" if fallback_readme else "missing")
    )

    return {
        **summary,
        "resolved_spec": spec,
        "generation_summary": gen_summary,
        "quality_report": quality_report,
        "slot_json": slot_json,
        "lang_dir": str(lang_dir),
        "lang_dir_exists": lang_dir.exists(),
        "readme": effective_readme,
        "readme_source": readme_source,
        "language_md": language_md_text,
        "files": file_list,
        "canonical_summary": canonical_summary,
        "canonical_tests": canonical_tests,
        "kata_pack": kata_pack,
    }


# ---------------------------------------------------------------------------
# Filter resolution
# ---------------------------------------------------------------------------

_VALID_SORT_FIELDS = {
    "slot_id", "distinctiveness", "coherence",
    "completeness", "added_at",
}


def _parse_filters(args: dict) -> dict:
    """Pull filter parameters from a request.args (or dict-like) into
    a normalized dict. Unknown values fall back to defaults."""
    return {
        "family": args.get("family") or None,
        "status": args.get("status") or None,
        "persona": args.get("persona") or None,
        "era": args.get("era") or None,
        "theme": args.get("theme") or None,
        "phrasebook": args.get("phrasebook") or None,
        "tier": args.get("tier") or None,
        "tag": args.get("tag") or None,
        "min_distinctiveness": _to_float(args.get("min_distinctiveness")),
        "max_distinctiveness": _to_float(args.get("max_distinctiveness")),
        "search": (args.get("search") or "").strip().lower() or None,
        "sort_by": (
            args.get("sort_by")
            if args.get("sort_by") in _VALID_SORT_FIELDS
            else "slot_id"
        ),
        "sort_dir": "desc" if args.get("sort_dir") == "desc" else "asc",
        "limit": _to_int(args.get("limit")),
        "offset": _to_int(args.get("offset")) or 0,
    }


def _to_float(v) -> Optional[float]:
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v) -> Optional[int]:
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _row_passes_filters(summary: dict, filters: dict) -> bool:
    """Apply the filters that the DB-level query couldn't (i.e. those
    that depend on enriched-from-slot.json fields, plus the
    distinctiveness range and free-text search). Returns True if the
    row should be included."""
    for axis in ("persona", "era", "theme", "phrasebook"):
        want = filters.get(axis)
        if want and summary.get(axis) != want:
            return False
    min_d = filters.get("min_distinctiveness")
    if min_d is not None:
        d = summary.get("distinctiveness")
        if d is None or d < min_d:
            return False
    max_d = filters.get("max_distinctiveness")
    if max_d is not None:
        d = summary.get("distinctiveness")
        if d is None or d > max_d:
            return False
    # Tier and tag (Stage C — present here for forward compat).
    want_tier = filters.get("tier")
    if want_tier and summary.get("tier") != want_tier:
        return False
    want_tag = filters.get("tag")
    if want_tag:
        tags = summary.get("tags") or []
        if want_tag not in tags:
            return False
    search = filters.get("search")
    if search:
        haystack = " ".join(filter(None, [
            summary.get("slot_id", ""),
            summary.get("display_name", ""),
            summary.get("persona", "") or "",
            summary.get("era", "") or "",
            summary.get("theme", "") or "",
            summary.get("phrasebook", "") or "",
            summary.get("rejection_reason", "") or "",
            summary.get("reviewer_notes", "") or "",
        ])).lower()
        if search not in haystack:
            return False
    return True


def _sort_summaries(summaries: list[dict], sort_by: str,
                    sort_dir: str) -> list[dict]:
    """Sort summaries by the requested key. Missing values sort last
    in asc order, first in desc order (consistent with what curators
    expect: 'show me the highest-distinctiveness candidates' shouldn't
    bury them under None entries)."""
    reverse = sort_dir == "desc"

    def keyfn(s: dict):
        v = s.get(sort_by)
        if v is None:
            # Sentinel that puts None last on asc, first on desc.
            return (1 if not reverse else 0, 0, "")
        if isinstance(v, (int, float)):
            return (0, -v if reverse else v, s.get("slot_id", ""))
        return (0, str(v), s.get("slot_id", ""))

    return sorted(summaries, key=keyfn)


# ---------------------------------------------------------------------------
# Public mounting function
# ---------------------------------------------------------------------------

def mount_catalog_routes(app: Flask, *,
                         catalog_db_path: Optional[Path] = None,
                         generated_root: Optional[Path] = None) -> None:
    """Attach catalog browsing + curation routes to a Flask app.

    `catalog_db_path` defaults to `<workspace>/catalog.db`.
    `generated_root` defaults to `<workspace>/`.

    Tests can pass overrides to point at temp DBs / fixture dirs.
    """
    db_path = Path(catalog_db_path) if catalog_db_path else _WORKSPACE / "catalog.db"
    gen_root = Path(generated_root) if generated_root else _WORKSPACE

    # Lazy-import the DB layer so unit tests that don't touch curation
    # don't pay for it.
    from forge.catalog import db as catalog_db

    # ------------------------------------------------------------------
    # GET /catalog — main catalog browse HTML page
    # ------------------------------------------------------------------

    @app.route("/catalog")
    def catalog_index():  # type: ignore[no-redef]
        return send_from_directory(str(_HERE / "static"), "catalog.html")

    # ------------------------------------------------------------------
    # GET /api/catalog/list — list view with filters
    # ------------------------------------------------------------------

    @app.route("/api/catalog/list")
    def catalog_list():  # type: ignore[no-redef]
        filters = _parse_filters(request.args)

        # The DB query covers the columnar filters cleanly; everything
        # else is filtered post-query. With <1000 rows this is fine.
        rows = catalog_db.list_languages(
            db_path,
            family=filters["family"],
            status=filters["status"],
        )
        summaries = [_row_to_summary(r, gen_root, db_path) for r in rows]
        # Stage C tier/tag fields aren't on LanguageRow yet (Stage C
        # adds them via migration). Until then summaries don't carry
        # tier/tags, but the filter still works against missing.
        filtered = [s for s in summaries if _row_passes_filters(s, filters)]
        filtered = _sort_summaries(filtered, filters["sort_by"],
                                   filters["sort_dir"])

        total_unfiltered = len(rows)
        total_filtered = len(filtered)
        offset = filters["offset"] or 0
        limit = filters["limit"]
        paged = filtered[offset:offset + limit] if limit else filtered[offset:]

        return jsonify({
            "items": paged,
            "total_filtered": total_filtered,
            "total_unfiltered": total_unfiltered,
            "offset": offset,
            "limit": limit,
            "filters": filters,
        })

    # ------------------------------------------------------------------
    # GET /api/catalog/<slot_id> — full detail
    # ------------------------------------------------------------------

    @app.route("/api/catalog/<slot_id>")
    def catalog_detail(slot_id: str):  # type: ignore[no-redef]
        row = catalog_db.get_language(db_path, slot_id)
        if row is None:
            abort(404, description=f"slot_id {slot_id!r} not in catalog")
        return jsonify(_row_to_detail(row, gen_root, db_path))

    # ------------------------------------------------------------------
    # GET /api/catalog/facets — distinct values for filter dropdowns
    # ------------------------------------------------------------------

    @app.route("/api/catalog/facets")
    def catalog_facets():  # type: ignore[no-redef]
        """Return distinct values present in the current DB for each
        filterable field. Used by the frontend to populate the filter
        dropdowns. We use the slot.json fallback so themes/eras/personas
        the resolver normalized away still appear."""
        rows = catalog_db.list_languages(db_path)
        summaries = [_row_to_summary(r, gen_root, db_path) for r in rows]
        def distinct(field: str) -> list:
            return sorted({s[field] for s in summaries
                           if s.get(field) not in (None, "")})
        return jsonify({
            "families": distinct("family"),
            "statuses": distinct("status"),
            "personas": distinct("persona"),
            "eras": distinct("era"),
            "themes": distinct("theme"),
            "phrasebooks": distinct("phrasebook"),
            "total": len(rows),
        })

    # ------------------------------------------------------------------
    # GET /api/catalog/progress — curation progress counts
    # ------------------------------------------------------------------

    @app.route("/api/catalog/progress")
    def catalog_progress():  # type: ignore[no-redef]
        rows = catalog_db.list_languages(db_path)
        counts = {"approved": 0, "rejected": 0, "pending_review": 0}
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        total = len(rows)
        reviewed = counts["approved"] + counts["rejected"]
        return jsonify({
            "total": total,
            "approved": counts["approved"],
            "rejected": counts["rejected"],
            "pending_review": counts["pending_review"],
            "reviewed": reviewed,
            "remaining": counts["pending_review"],
            "by_family": _counts_by(rows, "family"),
        })

    # ==================================================================
    # Stage B — write path: status / notes / rejection_reason
    # ==================================================================

    @app.route("/api/catalog/<slot_id>/status", methods=["POST"])
    def catalog_set_status(slot_id):  # type: ignore[no-redef]
        body = request.get_json(silent=True) or {}
        status = body.get("status")
        if status not in catalog_db.STATUS_VALUES:
            return jsonify({
                "error": f"status must be one of "
                         f"{list(catalog_db.STATUS_VALUES)}, got {status!r}"
            }), 400
        # Verify the slot exists before doing partial updates.
        existing = catalog_db.get_language(db_path, slot_id)
        if existing is None:
            return jsonify({"error": f"slot_id {slot_id!r} not in catalog"}), 404

        # Apply primary status update.
        catalog_db.update_language_status(
            db_path, slot_id, status,
            reviewer_notes=body.get("reviewer_notes"),
        )
        # Rejection reason: only meaningful when status=rejected.
        if "rejection_reason" in body:
            catalog_db.update_language_rejection_reason(
                db_path, slot_id, body.get("rejection_reason"),
            )
        elif status != catalog_db.STATUS_REJECTED:
            # Clear stale rejection_reason when moving away from rejected.
            catalog_db.update_language_rejection_reason(db_path, slot_id, None)

        updated = catalog_db.get_language(db_path, slot_id)
        return jsonify(_row_to_summary(updated, gen_root, db_path))

    @app.route("/api/catalog/<slot_id>/notes", methods=["POST"])
    def catalog_set_notes(slot_id):  # type: ignore[no-redef]
        body = request.get_json(silent=True) or {}
        notes = body.get("reviewer_notes")
        if notes is not None and not isinstance(notes, str):
            return jsonify({"error": "reviewer_notes must be a string or null"}), 400
        if not catalog_db.update_language_notes(db_path, slot_id, notes):
            return jsonify({"error": f"slot_id {slot_id!r} not in catalog"}), 404
        return jsonify({"ok": True, "slot_id": slot_id})

    # ==================================================================
    # Stage C — tier and tag system
    # ==================================================================

    @app.route("/api/catalog/<slot_id>/tier", methods=["POST"])
    def catalog_set_tier(slot_id):  # type: ignore[no-redef]
        body = request.get_json(silent=True) or {}
        tier = body.get("tier")
        if tier is not None and not isinstance(tier, str):
            return jsonify({"error": "tier must be a string or null"}), 400
        try:
            ok = catalog_db.update_language_tier(db_path, slot_id, tier)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not ok:
            return jsonify({"error": f"slot_id {slot_id!r} not in catalog"}), 404
        return jsonify({"ok": True, "slot_id": slot_id, "tier": tier})

    @app.route("/api/catalog/<slot_id>/tags", methods=["POST"])
    def catalog_set_tags(slot_id):  # type: ignore[no-redef]
        body = request.get_json(silent=True) or {}
        tags = body.get("tags")
        if not isinstance(tags, list):
            return jsonify({"error": "tags must be a list of strings"}), 400
        try:
            ok = catalog_db.update_language_tags(db_path, slot_id, tags)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if not ok:
            return jsonify({"error": f"slot_id {slot_id!r} not in catalog"}), 404
        # Re-read so the response carries the canonicalized tag list.
        row = catalog_db.get_language(db_path, slot_id)
        return jsonify({"ok": True, "slot_id": slot_id, "tags": row.tags})

    @app.route("/api/catalog/tags")
    def catalog_distinct_tags():  # type: ignore[no-redef]
        return jsonify({"tags": catalog_db.list_distinct_tags(db_path)})

    # ==================================================================
    # Stage D — bulk operations
    # ==================================================================

    @app.route("/api/catalog/bulk/status", methods=["POST"])
    def catalog_bulk_status():  # type: ignore[no-redef]
        body = request.get_json(silent=True) or {}
        slot_ids = body.get("slot_ids")
        status = body.get("status")
        if not isinstance(slot_ids, list) or not slot_ids:
            return jsonify({"error": "slot_ids must be a non-empty list"}), 400
        if status not in catalog_db.STATUS_VALUES:
            return jsonify({
                "error": f"status must be one of "
                         f"{list(catalog_db.STATUS_VALUES)}, got {status!r}"
            }), 400
        try:
            n = catalog_db.bulk_update_status(
                db_path, slot_ids, status,
                reviewer_notes=body.get("reviewer_notes"),
                rejection_reason=body.get("rejection_reason"),
            )
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        return jsonify({
            "ok": True,
            "rows_updated": n,
            "slot_ids": slot_ids,
            "status": status,
        })

    @app.route("/api/catalog/bulk/tag", methods=["POST"])
    def catalog_bulk_tag():  # type: ignore[no-redef]
        body = request.get_json(silent=True) or {}
        slot_ids = body.get("slot_ids")
        tag = body.get("tag")
        if not isinstance(slot_ids, list) or not slot_ids:
            return jsonify({"error": "slot_ids must be a non-empty list"}), 400
        if not isinstance(tag, str) or not tag.strip():
            return jsonify({"error": "tag must be a non-empty string"}), 400
        n = catalog_db.bulk_add_tag(db_path, slot_ids, tag.strip())
        return jsonify({
            "ok": True,
            "rows_updated": n,
            "slot_ids": slot_ids,
            "tag": tag.strip(),
        })


def _counts_by(rows, field: str) -> dict:
    out: dict = {}
    for r in rows:
        v = getattr(r, field, None) or "(unknown)"
        out[v] = out.get(v, 0) + 1
    return out
