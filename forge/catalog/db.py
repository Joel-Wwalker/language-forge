"""Phase 2 Stage C: SQLite catalog database.

# WHAT THIS DOES

Stores metadata, quality scores, and curation state for languages
that survive the Phase 2 filter. The actual language source code
lives at `generated/<slot_id>/` (or wherever the batch ran); the DB
points at those directories rather than copying the source.

# DESIGN CHOICES

- **SQLite, not Postgres.** The catalog is finite (<1000 entries),
  read-heavy, single-writer. Network-accessible state and concurrent
  writers aren't needed. The instructions explicitly forbid
  over-engineering this.
- **Atomic writes via the same .tmp + os.replace pattern used for
  state.json.** Phase 1.5 hardened that path with a Windows retry
  loop; we reuse it here.
- **No source-code in the DB.** The catalog is metadata-only; the
  source tree is the source-of-truth for language files. This keeps
  the DB small (kilobytes per entry) and lets curation operations
  re-read or re-score without touching the DB.
- **`pending_review` as the default status** for entries Phase 2
  doesn't reject. Phase 3 (curation UI) is where things move to
  `approved` or `rejected`. Phase 2 only auto-rejects clear
  correctness/completeness failures.
- **Schema versioning baked in via PRAGMA user_version.** Phase 4
  may need to add columns; the migration helper checks the version
  before applying.

# PUBLIC API

    init_db(db_path)
    insert_batch_result(db_path, batch_dir, reports, dedup_results) -> batch_id
    list_languages(db_path, *, family=None, status=None, limit=None) -> [LanguageRow]
    get_language(db_path, slot_id) -> LanguageRow | None
    update_language_status(db_path, slot_id, status, reviewer_notes=None)
    list_duplicates(db_path, slot_id) -> [DuplicateRow]
    get_batch(db_path, batch_id) -> BatchRow | None
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterator, Optional

from .quality import QualityReport, report_to_dict
from .dedup import DedupResult, result_to_dict


# Schema version. Bump when adding columns; the migration helper
# checks PRAGMA user_version before applying.
#
# Version history:
#   v1 — Phase 2 initial schema (languages, duplicates, batches).
#   v2 — Phase 3 adds `tier` (TEXT) and `tags` (TEXT JSON) columns to
#        languages. Both nullable; pre-existing rows get NULL.
SCHEMA_VERSION = 2


# Status values. Pinned as a constants tuple so callers can validate
# without importing enum machinery.
STATUS_PENDING = "pending_review"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_VALUES = (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED)


# Module-level lock that serializes writes from multiple threads in
# the same process. SQLite itself handles cross-process locking via
# its file lock, but Python sqlite3 connection objects are NOT
# thread-safe by default and our atomic-write commit pattern needs to
# fully complete before the next writer starts.
_db_write_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Row dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LanguageRow:
    id: int
    slot_id: str
    display_name: str
    family: str
    typing: str
    memory: str
    persona: Optional[str]
    era: Optional[str]
    theme: Optional[str]
    phrasebook: Optional[str]
    feature_bans: list[str] = field(default_factory=list)
    resolved_spec_json: str = ""
    pipeline_path: str = "unknown"
    generation_summary_json: str = ""
    quality_report_json: str = ""
    added_at: str = ""
    status: str = STATUS_PENDING
    rejection_reason: Optional[str] = None
    reviewer_notes: Optional[str] = None
    batch_id: Optional[int] = None
    # Phase 3 additions (schema v2). NULL on pre-Phase-3 rows.
    tier: Optional[str] = None
    tags: list[str] = field(default_factory=list)


@dataclass
class DuplicateRow:
    id: int
    representative_slot_id: str
    duplicate_slot_id: str
    similarity_score: float


@dataclass
class BatchRow:
    id: int
    slot_plan_path: str
    output_dir: str
    started_at: str
    ended_at: Optional[str]
    total_slots: int
    passed_quality: int
    rejected_quality: int
    passed_dedup: int
    rejected_dedup: int


# ---------------------------------------------------------------------------
# Schema migrations
# ---------------------------------------------------------------------------

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS languages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    family TEXT NOT NULL,
    typing TEXT NOT NULL,
    memory TEXT NOT NULL,
    persona TEXT,
    era TEXT,
    theme TEXT,
    phrasebook TEXT,
    feature_bans TEXT,
    resolved_spec_json TEXT NOT NULL,
    pipeline_path TEXT NOT NULL,
    generation_summary_json TEXT NOT NULL,
    quality_report_json TEXT NOT NULL,
    added_at TEXT NOT NULL,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    reviewer_notes TEXT,
    batch_id INTEGER REFERENCES batches(id)
);

CREATE INDEX IF NOT EXISTS idx_languages_family ON languages(family);
CREATE INDEX IF NOT EXISTS idx_languages_status ON languages(status);
CREATE INDEX IF NOT EXISTS idx_languages_batch ON languages(batch_id);

CREATE TABLE IF NOT EXISTS duplicates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    representative_slot_id TEXT NOT NULL,
    duplicate_slot_id TEXT NOT NULL,
    similarity_score REAL NOT NULL,
    UNIQUE (representative_slot_id, duplicate_slot_id)
);

CREATE INDEX IF NOT EXISTS idx_duplicates_rep
    ON duplicates(representative_slot_id);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_plan_path TEXT NOT NULL,
    output_dir TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    total_slots INTEGER NOT NULL,
    passed_quality INTEGER NOT NULL,
    rejected_quality INTEGER NOT NULL,
    passed_dedup INTEGER NOT NULL,
    rejected_dedup INTEGER NOT NULL
);
"""


@contextmanager
def _connect(db_path: Path, *, write: bool = False) -> Iterator[sqlite3.Connection]:
    """Open a SQLite connection. Use `write=True` for write paths so
    we acquire the module-level lock first (prevents Python-level
    races inside one process)."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if write:
        _db_write_lock.acquire()
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            # Foreign keys aren't on by default; enable them so
            # batches.id REFERENCES languages.batch_id is enforced.
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()
    finally:
        if write:
            _db_write_lock.release()


def _apply_v2_migration(conn: sqlite3.Connection) -> None:
    """Phase 3 schema migration: add tier and tags columns to
    languages. Both nullable; pre-existing rows get NULL.

    SQLite ALTER TABLE ADD COLUMN is atomic and cheap on small tables.
    The columns can be added in any order; we add tier first, tags
    second."""
    # Check if columns already exist (idempotence on partial-migration).
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(languages)").fetchall()}
    if "tier" not in cols:
        conn.execute("ALTER TABLE languages ADD COLUMN tier TEXT")
    if "tags" not in cols:
        conn.execute("ALTER TABLE languages ADD COLUMN tags TEXT")


def init_db(db_path: str | Path) -> None:
    """Create the catalog DB if it doesn't exist, or apply migrations
    to bring an existing one up to the current schema version.

    Idempotent: running on an up-to-date DB is a no-op."""
    db_path = Path(db_path)
    with _connect(db_path, write=True) as conn:
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current == 0:
            # Fresh DB — apply v1 schema then any subsequent migrations.
            conn.executescript(_SCHEMA_V1)
            _apply_v2_migration(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        elif current == 1 and SCHEMA_VERSION >= 2:
            # Phase 2 → Phase 3 upgrade: add tier and tags columns.
            _apply_v2_migration(conn)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.commit()
        elif current < SCHEMA_VERSION:
            # A future schema bump landed without a migration here.
            raise RuntimeError(
                f"DB at {db_path} is at user_version {current}; expected "
                f"{SCHEMA_VERSION}. Migrations must be added when bumping "
                f"SCHEMA_VERSION."
            )
        elif current > SCHEMA_VERSION:
            raise RuntimeError(
                f"DB at {db_path} is at user_version {current}, but this "
                f"build only supports up to {SCHEMA_VERSION}. Upgrade the "
                f"forge.catalog package."
            )


# ---------------------------------------------------------------------------
# Insertion: a whole batch's results in one transaction
# ---------------------------------------------------------------------------

def insert_batch_result(db_path: str | Path,
                        batch_dir: str | Path,
                        slot_plan_path: str | Path,
                        reports: list[QualityReport],
                        dedup_results: list[DedupResult],
                        *,
                        started_at: Optional[str] = None) -> int:
    """Insert a batch's full results: one row in `batches`, one in
    `languages` per surviving (non-duplicate) report, plus
    `duplicates` rows for each dedup grouping.

    Returns the new batch_id.

    Idempotent: re-running with the same `slot_id`s skips the
    already-inserted ones (UNIQUE constraint on `slot_id` would
    otherwise raise IntegrityError; we trap and skip). The batch row
    is always inserted as a new row even on re-runs — that's how a
    user can audit when re-curation happened."""
    db_path = Path(db_path)
    init_db(db_path)
    batch_dir = str(Path(batch_dir).resolve())
    slot_plan_path = str(Path(slot_plan_path).resolve())
    started_at = started_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Map slot_id → DedupResult so we know which slot_ids are
    # representatives (insert) vs duplicates (skip; record in
    # duplicates table).
    rep_lookup: dict[str, DedupResult] = {
        d.representative_slot_id: d for d in dedup_results
    }
    dup_to_rep: dict[str, str] = {}
    for d in dedup_results:
        for dup_slot in d.duplicate_slot_ids:
            dup_to_rep[dup_slot] = d.representative_slot_id

    passed_quality = sum(1 for r in reports if r.overall_passed)
    rejected_quality = len(reports) - passed_quality
    # passed_dedup: number of representatives whose own report passes.
    # rejected_dedup: how many were collapsed into representatives.
    passed_dedup = sum(
        1 for d in dedup_results
        if next((r for r in reports
                 if r.slot_id == d.representative_slot_id), None)
        and next(r for r in reports
                 if r.slot_id == d.representative_slot_id).overall_passed
    )
    rejected_dedup = sum(len(d.duplicate_slot_ids) for d in dedup_results)

    with _connect(db_path, write=True) as conn:
        cur = conn.execute(
            "INSERT INTO batches "
            "(slot_plan_path, output_dir, started_at, total_slots, "
            "passed_quality, rejected_quality, passed_dedup, rejected_dedup) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (slot_plan_path, batch_dir, started_at, len(reports),
             passed_quality, rejected_quality, passed_dedup, rejected_dedup)
        )
        batch_id = cur.lastrowid

        # Insert each surviving (representative or unique) language.
        added_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for r in reports:
            if r.slot_id in dup_to_rep:
                # This is a duplicate — record the relationship instead
                # of creating a `languages` row. The representative's
                # row will be created (or already exists) elsewhere.
                conn.execute(
                    "INSERT OR IGNORE INTO duplicates "
                    "(representative_slot_id, duplicate_slot_id, "
                    "similarity_score) VALUES (?, ?, ?)",
                    (dup_to_rep[r.slot_id], r.slot_id, 1.0),
                )
                continue
            # Insert (or skip if already present from a prior run).
            spec = _read_spec(Path(r.lang_dir))
            summary = _read_summary(Path(r.lang_dir))
            cust = (spec.get("customization") or {})
            initial_status = (
                STATUS_REJECTED if not r.overall_passed
                else STATUS_PENDING
            )
            try:
                conn.execute(
                    "INSERT INTO languages ("
                    "slot_id, display_name, family, typing, memory, "
                    "persona, era, theme, phrasebook, feature_bans, "
                    "resolved_spec_json, pipeline_path, "
                    "generation_summary_json, quality_report_json, "
                    "added_at, status, rejection_reason, "
                    "reviewer_notes, batch_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?, ?, ?)",
                    (
                        r.slot_id,
                        spec.get("display_name") or r.slot_id,
                        r.family,
                        (spec.get("options") or {}).get("typing", "unknown"),
                        (spec.get("options") or {}).get("memory", "unknown"),
                        cust.get("persona"),
                        cust.get("era"),
                        cust.get("theme"),
                        cust.get("phrasebook"),
                        json.dumps(cust.get("feature_bans") or []),
                        json.dumps(spec, indent=2),
                        r.pipeline_path,
                        json.dumps(summary, indent=2),
                        json.dumps(report_to_dict(r), indent=2),
                        added_at,
                        initial_status,
                        r.rejection_reason,
                        None,
                        batch_id,
                    ),
                )
            except sqlite3.IntegrityError:
                # slot_id already in DB (idempotence on re-run). Skip.
                continue
        conn.commit()
    return batch_id


def _read_spec(lang_dir: Path) -> dict:
    p = lang_dir / "resolved_spec.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_summary(lang_dir: Path) -> dict:
    p = lang_dir / "generation_summary.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Read API
# ---------------------------------------------------------------------------

def list_languages(db_path: str | Path, *,
                   family: Optional[str] = None,
                   status: Optional[str] = None,
                   limit: Optional[int] = None) -> list[LanguageRow]:
    """Return rows matching the filters. Sorted by `slot_id` ascending
    for stable output."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    where = []
    args: list = []
    if family is not None:
        where.append("family = ?"); args.append(family)
    if status is not None:
        where.append("status = ?"); args.append(status)
    sql = "SELECT * FROM languages"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY slot_id"
    if limit is not None:
        sql += " LIMIT ?"; args.append(int(limit))
    with _connect(db_path) as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_language(r) for r in rows]


def get_language(db_path: str | Path, slot_id: str) -> Optional[LanguageRow]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM languages WHERE slot_id = ?", (slot_id,)
        ).fetchone()
    return _row_to_language(row) if row else None


def list_duplicates(db_path: str | Path,
                    representative_slot_id: str) -> list[DuplicateRow]:
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM duplicates WHERE representative_slot_id = ? "
            "ORDER BY duplicate_slot_id",
            (representative_slot_id,),
        ).fetchall()
    return [DuplicateRow(
        id=r["id"],
        representative_slot_id=r["representative_slot_id"],
        duplicate_slot_id=r["duplicate_slot_id"],
        similarity_score=float(r["similarity_score"]),
    ) for r in rows]


def get_batch(db_path: str | Path, batch_id: int) -> Optional[BatchRow]:
    db_path = Path(db_path)
    if not db_path.exists():
        return None
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM batches WHERE id = ?", (batch_id,)
        ).fetchone()
    if row is None:
        return None
    return BatchRow(
        id=row["id"],
        slot_plan_path=row["slot_plan_path"],
        output_dir=row["output_dir"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        total_slots=row["total_slots"],
        passed_quality=row["passed_quality"],
        rejected_quality=row["rejected_quality"],
        passed_dedup=row["passed_dedup"],
        rejected_dedup=row["rejected_dedup"],
    )


# ---------------------------------------------------------------------------
# Write API
# ---------------------------------------------------------------------------

def update_language_status(db_path: str | Path, slot_id: str,
                            status: str, *,
                            reviewer_notes: Optional[str] = None) -> bool:
    """Update a language's curation status. Returns True if a row was
    updated, False if no such slot_id exists."""
    if status not in STATUS_VALUES:
        raise ValueError(
            f"status must be one of {STATUS_VALUES}, got {status!r}"
        )
    db_path = Path(db_path)
    init_db(db_path)
    with _connect(db_path, write=True) as conn:
        if reviewer_notes is None:
            cur = conn.execute(
                "UPDATE languages SET status = ? WHERE slot_id = ?",
                (status, slot_id),
            )
        else:
            cur = conn.execute(
                "UPDATE languages SET status = ?, reviewer_notes = ? "
                "WHERE slot_id = ?",
                (status, reviewer_notes, slot_id),
            )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_language(row: sqlite3.Row) -> LanguageRow:
    feature_bans: list[str] = []
    raw_bans = row["feature_bans"]
    if raw_bans:
        try:
            feature_bans = json.loads(raw_bans)
        except Exception:
            feature_bans = []
    # tier / tags columns may not be present on schema-v1 rows that
    # haven't been migrated. Defensively read via dict access.
    tier = None
    tags: list[str] = []
    try:
        keys = row.keys() if hasattr(row, "keys") else []
    except Exception:
        keys = []
    if "tier" in keys:
        tier = row["tier"]
    if "tags" in keys and row["tags"]:
        try:
            parsed = json.loads(row["tags"])
            if isinstance(parsed, list):
                tags = [str(t) for t in parsed]
        except Exception:
            tags = []
    return LanguageRow(
        id=row["id"],
        slot_id=row["slot_id"],
        display_name=row["display_name"],
        family=row["family"],
        typing=row["typing"],
        memory=row["memory"],
        persona=row["persona"],
        era=row["era"],
        theme=row["theme"],
        phrasebook=row["phrasebook"],
        feature_bans=feature_bans,
        resolved_spec_json=row["resolved_spec_json"],
        pipeline_path=row["pipeline_path"],
        generation_summary_json=row["generation_summary_json"],
        quality_report_json=row["quality_report_json"],
        added_at=row["added_at"],
        status=row["status"],
        rejection_reason=row["rejection_reason"],
        reviewer_notes=row["reviewer_notes"],
        batch_id=row["batch_id"],
        tier=tier,
        tags=tags,
    )


# ---------------------------------------------------------------------------
# Phase 3 write helpers: notes, tier, tags, bulk
# ---------------------------------------------------------------------------

def update_language_notes(db_path: str | Path, slot_id: str,
                          reviewer_notes: Optional[str]) -> bool:
    """Update reviewer_notes on a language row WITHOUT changing status.
    Used by the curation UI's "save annotations as I'm reading" flow.

    Returns True if a row was updated, False if no such slot_id."""
    db_path = Path(db_path)
    init_db(db_path)
    with _connect(db_path, write=True) as conn:
        cur = conn.execute(
            "UPDATE languages SET reviewer_notes = ? WHERE slot_id = ?",
            (reviewer_notes, slot_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_language_rejection_reason(db_path: str | Path, slot_id: str,
                                     rejection_reason: Optional[str]) -> bool:
    """Update rejection_reason on a language row WITHOUT changing
    status. Used when the curator edits the reason on an already-
    rejected entry."""
    db_path = Path(db_path)
    init_db(db_path)
    with _connect(db_path, write=True) as conn:
        cur = conn.execute(
            "UPDATE languages SET rejection_reason = ? WHERE slot_id = ?",
            (rejection_reason, slot_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_language_tier(db_path: str | Path, slot_id: str,
                         tier: Optional[str]) -> bool:
    """Set the tier (free-form text; Phase 5 decides the scheme).
    Pass None to clear. Returns True if a row was updated."""
    db_path = Path(db_path)
    init_db(db_path)
    if tier is not None and not isinstance(tier, str):
        raise ValueError(f"tier must be a string or None, got {type(tier)}")
    with _connect(db_path, write=True) as conn:
        cur = conn.execute(
            "UPDATE languages SET tier = ? WHERE slot_id = ?",
            (tier, slot_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_language_tags(db_path: str | Path, slot_id: str,
                         tags: list[str]) -> bool:
    """Replace the tags array. Pass [] to clear. Each entry must be a
    non-empty string; duplicates are de-duped by the helper. Returns
    True if a row was updated."""
    if not isinstance(tags, list):
        raise ValueError(f"tags must be a list, got {type(tags)}")
    cleaned: list[str] = []
    seen: set[str] = set()
    for t in tags:
        if not isinstance(t, str):
            raise ValueError(f"each tag must be a string, got {type(t)}")
        s = t.strip()
        if s and s not in seen:
            cleaned.append(s)
            seen.add(s)
    db_path = Path(db_path)
    init_db(db_path)
    with _connect(db_path, write=True) as conn:
        cur = conn.execute(
            "UPDATE languages SET tags = ? WHERE slot_id = ?",
            (json.dumps(cleaned), slot_id),
        )
        conn.commit()
        return cur.rowcount > 0


def list_distinct_tags(db_path: str | Path) -> list[str]:
    """Return every distinct tag currently used across the catalog,
    sorted. Used by the UI's tag-autocomplete."""
    db_path = Path(db_path)
    if not db_path.exists():
        return []
    out: set[str] = set()
    with _connect(db_path) as conn:
        # tags column may not exist yet on a v1 DB.
        try:
            rows = conn.execute(
                "SELECT tags FROM languages WHERE tags IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        for r in rows:
            try:
                parsed = json.loads(r["tags"])
                if isinstance(parsed, list):
                    out.update(str(t) for t in parsed)
            except Exception:
                continue
    return sorted(out)


def add_tag_to_language(db_path: str | Path, slot_id: str,
                        tag: str) -> bool:
    """Append a tag to a language's tags array (no-op if already
    present). Returns True if the row exists (whether or not the tag
    was already there)."""
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("tag must be a non-empty string")
    tag = tag.strip()
    row = get_language(db_path, slot_id)
    if row is None:
        return False
    if tag in row.tags:
        return True
    return update_language_tags(db_path, slot_id, list(row.tags) + [tag])


def bulk_update_status(db_path: str | Path, slot_ids: list[str],
                      status: str, *,
                      reviewer_notes: Optional[str] = None,
                      rejection_reason: Optional[str] = None) -> int:
    """Apply a status update to multiple slots in one transaction.
    Returns the number of rows updated. Validates `status` before
    touching the DB."""
    if status not in STATUS_VALUES:
        raise ValueError(f"status must be one of {STATUS_VALUES}, "
                         f"got {status!r}")
    if not isinstance(slot_ids, list) or not slot_ids:
        return 0
    db_path = Path(db_path)
    init_db(db_path)
    n = 0
    with _connect(db_path, write=True) as conn:
        for slot_id in slot_ids:
            params = {"status": status, "slot_id": slot_id}
            sets = ["status = :status"]
            if reviewer_notes is not None:
                sets.append("reviewer_notes = :reviewer_notes")
                params["reviewer_notes"] = reviewer_notes
            if rejection_reason is not None and status == STATUS_REJECTED:
                sets.append("rejection_reason = :rejection_reason")
                params["rejection_reason"] = rejection_reason
            cur = conn.execute(
                f"UPDATE languages SET {', '.join(sets)} WHERE slot_id = :slot_id",
                params,
            )
            n += cur.rowcount
        conn.commit()
    return n


def bulk_add_tag(db_path: str | Path, slot_ids: list[str], tag: str) -> int:
    """Add a tag to multiple slots. Returns the number of rows
    affected (matching slot_ids that exist)."""
    if not isinstance(tag, str) or not tag.strip():
        raise ValueError("tag must be a non-empty string")
    if not isinstance(slot_ids, list) or not slot_ids:
        return 0
    n = 0
    for slot_id in slot_ids:
        if add_tag_to_language(db_path, slot_id, tag):
            n += 1
    return n


def backfill_customization_from_plan(
    db_path: str | Path,
    plan_path: str | Path,
    *,
    overwrite: bool = False,
) -> dict:
    """Phase 3 follow-up Item 3: rehydrate `theme`/`phrasebook`/
    `persona`/`era` columns on language rows from the original slot
    plan when the resolver normalized them away and `slot.json`
    wasn't preserved.

    The Phase 1.5 resolver consumes `theme` and `phrasebook` into
    concrete `keyword_overrides` + creative content, leaving the
    DB columns NULL even when the original plan slot had them set.
    The catalog runner SHOULD copy `slot.json` next to each
    generated language to preserve the original input — but the
    Phase 1.5 batch produced `catalog_raw_gate2_v2/` without those
    files (a runner bug to harden in Phase 4).

    This function fills the gap by reading the plan file directly
    and updating each row whose customization columns are NULL
    (default) or all rows (when `overwrite=True`).

    Returns a dict {`updated`, `skipped_already_set`,
    `skipped_no_match`} for reporting.

    Args:
      db_path: catalog DB
      plan_path: path to the slot plan JSON (typically
        `forge/catalog/slots/v1_phase1.json`)
      overwrite: if True, even non-NULL columns get updated from
        the plan. Default False — only fills NULL columns.
    """
    db_path = Path(db_path)
    plan_path = Path(plan_path)
    if not plan_path.exists():
        raise FileNotFoundError(f"plan not found: {plan_path}")
    init_db(db_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_by_id: dict[str, dict] = {s["slot_id"]: s for s in plan
                                    if isinstance(s, dict)
                                    and "slot_id" in s}

    updated = 0
    skipped_already_set = 0
    skipped_no_match = 0

    with _connect(db_path, write=True) as conn:
        rows = conn.execute(
            "SELECT slot_id, persona, era, theme, phrasebook "
            "FROM languages"
        ).fetchall()
        for r in rows:
            slot = plan_by_id.get(r["slot_id"])
            if slot is None:
                skipped_no_match += 1
                continue
            cust = slot.get("customization") or {}
            new_persona = cust.get("persona")
            new_era = cust.get("era")
            new_theme = cust.get("theme")
            new_phrasebook = cust.get("phrasebook")

            sets = []
            params: dict = {"slot_id": r["slot_id"]}
            if new_persona and (overwrite or r["persona"] is None):
                sets.append("persona = :persona")
                params["persona"] = new_persona
            if new_era and (overwrite or r["era"] is None):
                sets.append("era = :era")
                params["era"] = new_era
            if new_theme and (overwrite or r["theme"] is None):
                sets.append("theme = :theme")
                params["theme"] = new_theme
            if new_phrasebook and (overwrite or r["phrasebook"] is None):
                sets.append("phrasebook = :phrasebook")
                params["phrasebook"] = new_phrasebook

            if sets:
                conn.execute(
                    f"UPDATE languages SET {', '.join(sets)} "
                    f"WHERE slot_id = :slot_id",
                    params,
                )
                updated += 1
            else:
                skipped_already_set += 1
        conn.commit()

    return {
        "updated": updated,
        "skipped_already_set": skipped_already_set,
        "skipped_no_match": skipped_no_match,
        "plan_slots": len(plan_by_id),
    }
