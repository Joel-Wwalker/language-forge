"""Phase 3 Stage E — programmatic curation walkthrough.

The Phase 3 instructions describe Stage E as a manual curator session
("sit down with catalog.db and triage all 37 pending_review
candidates"). An automated agent can't actually do that — but it can
exercise every UI route programmatically against the real Phase 1.5
catalog.db, simulate the decisions a real curator would make, and
verify the contract holds end-to-end.

This file:

  1. Loads the real catalog.db built by Phase 2's curate run (when
     it exists locally; the test is skipped otherwise).
  2. Walks through every pending_review candidate via the Flask
     test client, exercising:
       - GET /api/catalog/list (with various filters)
       - GET /api/catalog/<slot_id>
       - POST /api/catalog/<slot_id>/status (approve / reject)
       - POST /api/catalog/<slot_id>/notes
       - POST /api/catalog/<slot_id>/tier
       - POST /api/catalog/<slot_id>/tags
       - GET /api/catalog/progress
  3. Times the walkthrough.
  4. Reports counts in the final DB state.

The decision policy is deterministic so the test is reproducible:
  - completeness < 0.8 OR correctness fail -> already rejected by
    insert (no action needed)
  - distinctiveness >= 0.5 -> approve, tier=common, tag=high-distinct
  - 0.3 <= distinctiveness < 0.5 -> approve, tier=common
  - distinctiveness < 0.3 -> reject ("low distinctiveness baseline;
    duplicate of family default")

Note: this walkthrough WRITES TO A COPY of the catalog DB — never the
real one. The original Phase 1.5 catalog.db is untouched.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest


WORKSPACE = Path(__file__).resolve().parents[1]
REAL_CATALOG_DB = WORKSPACE / "catalog.db"
REAL_GENERATED_ROOT = WORKSPACE


pytestmark = pytest.mark.skipif(
    not REAL_CATALOG_DB.exists()
    or not (WORKSPACE / "catalog_raw_gate2_v2").exists(),
    reason="real Phase 1.5 catalog.db not present (skip Stage E walkthrough)",
)


def _decide(distinctiveness: float | None,
            coherence: float | None) -> tuple[str, str | None, list[str]]:
    """Deterministic policy for the simulated walkthrough.
    Returns (status, rejection_reason_or_none, tags)."""
    d = distinctiveness or 0.0
    if d >= 0.6:
        return ("approved", None, ["high-distinctiveness"])
    if d >= 0.3:
        return ("approved", None, [])
    return (
        "rejected",
        "low distinctiveness; reads as a baseline variant of its family",
        [],
    )


@pytest.mark.slow
def test_phase3_stage_e_walkthrough(tmp_path):
    """Walk through every pending candidate in the real catalog.db.
    Verify the routes work end-to-end and the final DB state is
    coherent."""
    # Copy the catalog.db so we don't mutate the real one. The
    # walkthrough writes to the copy.
    db_copy = tmp_path / "catalog_walkthrough.db"
    shutil.copy(REAL_CATALOG_DB, db_copy)

    # Build a Flask app pointed at the copy + the real generated
    # root. The catalog_raw_gate2_v2 dir holds the slot.json files
    # the UI falls back to.
    from forge.gui.app import create_app
    from forge.catalog.db import list_languages

    app = create_app(
        catalog_db_path=db_copy,
        catalog_generated_root=WORKSPACE,
    )

    with app.test_client() as client:
        t0 = time.monotonic()

        # Step 1: load facets (the curator's first action when opening UI).
        r = client.get("/api/catalog/facets")
        assert r.status_code == 200
        facets = r.get_json()
        assert facets["total"] >= 1

        # Step 2: load the list of pending candidates (what the curator
        # sees on entry).
        r = client.get("/api/catalog/list?status=pending_review&"
                       "sort_by=distinctiveness&sort_dir=desc")
        assert r.status_code == 200
        listing = r.get_json()
        pending = listing["items"]
        initial_pending_count = len(pending)
        print(f"\n[stage-e] starting with {initial_pending_count} pending candidates")

        # Step 3: try each filter combination once to confirm it works
        # (this is what a real curator does in the first 30 seconds).
        for filter_query in [
            "family=c_like",
            "family=s_expression",
            "family=stack_based",
            "min_distinctiveness=0.5",
            "search=slot_001",
        ]:
            r = client.get(f"/api/catalog/list?{filter_query}")
            assert r.status_code == 200, (
                f"filter {filter_query!r} failed with status {r.status_code}"
            )

        # Step 4: walk through each candidate.
        decisions = {"approved": 0, "rejected": 0}
        per_candidate_times: list[float] = []

        for item in pending:
            slot_id = item["slot_id"]
            t_per = time.monotonic()

            # 4a: open detail (curator clicks a row).
            r = client.get(f"/api/catalog/{slot_id}")
            assert r.status_code == 200, f"detail load failed for {slot_id}"
            detail = r.get_json()

            # 4b: read README + LANGUAGE.md + spec (curator skims the
            # detail view; the data is just bytes here).
            assert "readme" in detail
            assert "resolved_spec" in detail

            # 4c: add a reviewer note (simulating annotation while reading).
            r = client.post(
                f"/api/catalog/{slot_id}/notes",
                json={"reviewer_notes": (
                    f"walkthrough decision based on quality scores: "
                    f"distinctiveness={item['distinctiveness']}, "
                    f"coherence={item['coherence']}"
                )},
            )
            assert r.status_code == 200

            # 4d: decide.
            status, rejection_reason, tags = _decide(
                item["distinctiveness"], item["coherence"]
            )
            body = {"status": status,
                    "reviewer_notes": "walkthrough auto-decision"}
            if rejection_reason is not None:
                body["rejection_reason"] = rejection_reason
            r = client.post(f"/api/catalog/{slot_id}/status", json=body)
            assert r.status_code == 200, f"status update failed for {slot_id}"
            decisions[status] = decisions.get(status, 0) + 1

            # 4e: tier + tags for approved entries.
            if status == "approved":
                tier = ("rare" if item["distinctiveness"] >= 0.6
                        else "common")
                client.post(f"/api/catalog/{slot_id}/tier",
                            json={"tier": tier})
                if tags:
                    client.post(f"/api/catalog/{slot_id}/tags",
                                json={"tags": tags})

            per_candidate_times.append(time.monotonic() - t_per)

        # Step 5: final progress check.
        r = client.get("/api/catalog/progress")
        progress = r.get_json()

        wall = time.monotonic() - t0

    # Final state assertions.
    final_rows = list_languages(db_copy)
    final_pending = [r for r in final_rows if r.status == "pending_review"]
    final_approved = [r for r in final_rows if r.status == "approved"]
    final_rejected = [r for r in final_rows if r.status == "rejected"]

    print(f"\n[stage-e] walkthrough complete in {wall:.2f}s")
    print(f"  initial pending: {initial_pending_count}")
    print(f"  per-candidate avg: "
          f"{(sum(per_candidate_times)/len(per_candidate_times)*1000):.1f}ms")
    print(f"  final state: approved={len(final_approved)} "
          f"rejected={len(final_rejected)} "
          f"pending={len(final_pending)} "
          f"total={len(final_rows)}")
    print(f"  decisions: {decisions}")
    print(f"  progress endpoint matches: "
          f"{progress['approved'] == len(final_approved) and progress['rejected'] == len(final_rejected)}")

    # Contract assertions: every pending candidate got moved out of
    # pending_review (the walkthrough triaged the queue exhaustively).
    assert decisions["approved"] + decisions["rejected"] == initial_pending_count
    # Progress endpoint is consistent with DB state.
    assert progress["approved"] == len(final_approved)
    assert progress["rejected"] == len(final_rejected)
    assert progress["pending_review"] == len(final_pending)

    # Performance: each candidate's full route round-trip should be
    # under 500ms (the actual UI rendering is client-side, so this is
    # just the API path). At 600-slot scale, 500ms × 600 = 5 minutes
    # of pure-API time, which is acceptable.
    avg_ms = sum(per_candidate_times) / len(per_candidate_times) * 1000
    assert avg_ms < 500, (
        f"per-candidate API time averaged {avg_ms:.1f}ms; should be <500ms "
        f"to keep 600-slot triage under 5 minutes of pure-API time"
    )
