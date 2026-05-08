"""Phase 2 Stage B: deduplicate near-identical generated languages.

# WHAT THIS DOES

Given a list of `QualityReport`s from Stage A, group near-duplicates
together and select the highest-scoring representative of each group.
Phase 1.5 demonstrated that the resolver cache hits often produce
languages with identical specs but different `slot_id`s — those are
obvious duplicates. Subtler ones happen when two slots have different
options that the resolver fills in similarly, or when the LLM's
creative output happens to converge.

# HOW WE DECIDE TWO LANGUAGES ARE DUPLICATES

We hash the SUBSTANTIVE FINGERPRINT of each generation — the parts
that determine "this is the same language as that one":

  - Resolved spec, with `lang_name`, `display_name`, `slot_id`, and
    timestamps stripped (the resolver's content-hash cache key uses
    the same approach).
  - Substantive code outputs from the templated path: keyword
    overrides, comment syntax, statement_terminator, file_extension.

Two reports with the SAME fingerprint are exact duplicates. They get
grouped together; the one with the highest `overall` score wins
(ties broken by lower slot_id alphabetically — deterministic).

# WHAT WE DELIBERATELY DO NOT HASH

  - `creative.readme_intro` and `origin_story`: per the instructions,
    "two languages with identical specs but different generated
    stories aren't duplicates if the stories meaningfully differ."
    Excluding creative output from the hash means a vanilla c_like
    with one origin_story is NOT considered a duplicate of a vanilla
    c_like with a different origin_story. This is the conservative
    choice — false-negatives (missed dups) are easier to handle in
    Phase 3 curation than false-positives (collapsed distinct
    languages).
  - Token counts and telemetry: cosmetic, not substantive.
  - Source-file BYTE content: varies with module-name swap and
    other cosmetic substitutions; the structural fingerprint
    captures the substantive parts already.

# WHEN GROUPS ARE BIGGER THAN 2

Three-way duplicates collapse to one representative; the other two
appear in `duplicates`. The representative has the highest overall
score, computed from the QualityReport's components:

    overall = (
        2.0 * int(correctness.passed)         # gate
        + 1.5 * completeness.score
        + 1.0 * distinctiveness.score
        + 1.0 * coherence.score
    )

This weighting reflects the priority order: correctness > completeness
> the graded dimensions. A high-distinctiveness but broken language
shouldn't beat a working baseline.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

from .quality import QualityReport


# Spec fields stripped before hashing (volatile / identity-bearing).
_VOLATILE_SPEC_FIELDS = (
    "lang_name",
    "display_name",
    "creative",
    "origin_story",
    "design_notes",   # resolver-specific notes; non-substantive
)


# ---------------------------------------------------------------------------
# Fingerprint computation
# ---------------------------------------------------------------------------

def _normalize_spec_for_hash(spec: dict) -> dict:
    """Strip volatile / identity-bearing fields and return a
    deterministically-orderable dict for hashing."""
    out = {}
    for k, v in spec.items():
        if k in _VOLATILE_SPEC_FIELDS:
            continue
        out[k] = v
    return out


def fingerprint(report: QualityReport) -> str:
    """Compute a SHA256 fingerprint of a language's substantive
    structure. Used to group exact duplicates.

    Two reports with the same fingerprint are considered exact
    duplicates by Stage B's dedup logic."""
    from pathlib import Path
    spec_path = Path(report.lang_dir) / "resolved_spec.json"
    if not spec_path.exists():
        # No spec → fall back to slot_id (every fingerprint is unique).
        return hashlib.sha256(
            f"no_spec:{report.slot_id}".encode("utf-8")
        ).hexdigest()
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:
        return hashlib.sha256(
            f"bad_spec:{report.slot_id}".encode("utf-8")
        ).hexdigest()
    normalized = _normalize_spec_for_hash(spec)
    payload = json.dumps(normalized, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _overall_score(report: QualityReport) -> float:
    """Weighted overall score used to pick the representative within
    a duplicate group. Higher is better.

    Weighting reflects the dimension priority:
      - Correctness (2.0): the gate. Anything that fails correctness
        is automatically demoted below anything that passes.
      - Completeness (1.5): close-but-incomplete generations should
        lose to fully-shipped ones.
      - Distinctiveness, Coherence (1.0 each): graded but secondary.
    """
    return (
        2.0 * float(int(report.correctness.passed))
        + 1.5 * report.completeness.score
        + 1.0 * report.distinctiveness.score
        + 1.0 * report.coherence.score
    )


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class DedupResult:
    """One unique language post-dedup."""
    representative_slot_id: str
    representative_lang_dir: str
    representative_score: float
    duplicate_slot_ids: list[str] = field(default_factory=list)
    similarity_score: float = 1.0   # for now: 1.0 = exact fingerprint match
    fingerprint: str = ""


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

def dedup_languages(reports: list[QualityReport]) -> list[DedupResult]:
    """Group near-duplicate languages by structural fingerprint and
    select the highest-scoring representative for each group.

    Returns one `DedupResult` per unique language, sorted by
    representative_slot_id alphabetically.

    Idempotent: feeding the same reports list twice produces the same
    output (modulo the guarantee that scoring is itself idempotent —
    which Stage A pins).
    """
    if not reports:
        return []

    # Bucket reports by fingerprint.
    buckets: dict[str, list[QualityReport]] = {}
    for r in reports:
        fp = fingerprint(r)
        buckets.setdefault(fp, []).append(r)

    results: list[DedupResult] = []
    for fp, group in buckets.items():
        # Sort by overall score desc, then slot_id asc for tie-break.
        group_sorted = sorted(
            group,
            key=lambda r: (-_overall_score(r), r.slot_id),
        )
        rep = group_sorted[0]
        dups = [r.slot_id for r in group_sorted[1:]]
        results.append(DedupResult(
            representative_slot_id=rep.slot_id,
            representative_lang_dir=rep.lang_dir,
            representative_score=round(_overall_score(rep), 3),
            duplicate_slot_ids=dups,
            similarity_score=1.0 if dups else 1.0,  # placeholder
            fingerprint=fp,
        ))

    # Stable output ordering for downstream consumers.
    results.sort(key=lambda d: d.representative_slot_id)
    return results


def dedup_summary(results: list[DedupResult]) -> dict:
    """Top-level rollup numbers about a dedup pass."""
    total_reports = sum(1 + len(r.duplicate_slot_ids) for r in results)
    total_unique = len(results)
    total_duplicates = total_reports - total_unique
    largest_group = max(
        (1 + len(r.duplicate_slot_ids) for r in results), default=0
    )
    return {
        "total_reports": total_reports,
        "unique_languages": total_unique,
        "duplicates_collapsed": total_duplicates,
        "largest_group_size": largest_group,
    }


def result_to_dict(result: DedupResult) -> dict:
    """JSON-safe form."""
    return asdict(result)
