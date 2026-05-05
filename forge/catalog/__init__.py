"""Catalog production tooling (Phase 1+).

Modules:
  planner.py   -- load + validate slot files into typed Slot records
  (later)      -- runner.py, batch.py, smoke_test.py, quality.py, storage.py

Slot files describe one generation attempt each. The Phase 1 v1 slot
file at slots/v1_phase1.json is hand-curated for coverage; Phase 4
replaces this with a distribution-aware planner.
"""
