"""Slot planner: load + validate slot files for the batch runner.

Phase 1.1 (production roadmap v2). A "slot" describes one language
generation attempt: the options dict, customization, seed, and rarity
target. Slot files are JSON arrays of slot objects. The Phase 1 v1
file at `slots/v1_phase1.json` is hand-curated for coverage across
the four working syntax families.

This module's job is the load + validate step: read the file, check
every slot has the required shape, run each slot's `options` through
the existing `spec_builder.validate_spec` pipeline so we catch
malformed specs at plan-load time rather than mid-batch, and return a
list of typed `Slot` objects the batch runner can consume.

Phase 4 will replace the hand-curated file with a distribution-aware
planner that generates a slot list from a target distribution spec.
The schema and entry points stay the same; only the slot-source
changes.

Public API:
    Slot                            -- dataclass
    SlotPlanError                   -- raised on validation failure
    make_slot_plan(path) -> [Slot]  -- load + validate
    VALID_RARITIES                  -- {common, rare, epic, mythic, legendary}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional


VALID_RARITIES = ("common", "rare", "epic", "mythic", "legendary")


@dataclass(frozen=True)
class Slot:
    """One generation attempt's full configuration.

    Frozen so accidental mutation by the runner can't corrupt a
    later retry's input. Use `dataclasses.replace(slot, ...)` for
    intentional copies.
    """
    slot_id: str
    options: dict
    customization: dict
    seed: int
    target_rarity: str
    notes: str = ""

    def to_build_spec_kwargs(self) -> dict:
        """Translate slot.customization into the kwargs `build_spec`
        expects. The slot schema groups customization fields together
        for clarity; build_spec takes them as flat keyword arguments."""
        cust = self.customization or {}
        kwargs = {}
        # Map slot field name -> build_spec kwarg name. Slot uses the
        # roadmap-mandated `theme` while build_spec uses `keyword_theme`.
        for slot_key, spec_key in (
            ("persona", "persona"),
            ("era", "era"),
            ("theme", "keyword_theme"),
            ("phrasebook", "phrasebook"),
            ("feature_bans", "feature_bans"),
            ("hostile_constraints", "hostile_constraints"),
            ("natural_language", "natural_language"),
        ):
            if slot_key in cust and cust[slot_key] is not None:
                kwargs[spec_key] = cust[slot_key]
        return kwargs


class SlotPlanError(ValueError):
    """Raised by make_slot_plan when the slot file fails validation.

    The exception message contains every validation error found across
    every slot in the file (not just the first). This lets a curator
    fix all problems in one editing pass rather than a hunt-and-peck
    cycle.
    """
    def __init__(self, path: Path, errors: list[str]):
        self.path = path
        self.errors = errors
        msg = f"slot file {path!s} has {len(errors)} validation error(s):\n  - " + \
              "\n  - ".join(errors)
        super().__init__(msg)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_REQUIRED_TOP_LEVEL = ("slot_id", "options", "customization", "seed", "target_rarity")
_OPTIONAL_TOP_LEVEL = ("notes",)
_REQUIRED_CUST_KEYS = ("persona", "era", "theme", "phrasebook", "feature_bans")


def _validate_slot_shape(raw: dict, idx: int) -> list[str]:
    """Surface-level shape checks: every required field present and of
    the right type. Does NOT call into spec_builder; that's a deeper
    check done by the caller after shape passes."""
    errors: list[str] = []
    where = f"slot[{idx}]"
    if not isinstance(raw, dict):
        return [f"{where}: expected object, got {type(raw).__name__}"]

    # Required fields present.
    for key in _REQUIRED_TOP_LEVEL:
        if key not in raw:
            errors.append(f"{where}: missing required field {key!r}")

    # Type checks.
    if isinstance(raw.get("slot_id"), str):
        if not raw["slot_id"]:
            errors.append(f"{where}: slot_id must be non-empty")
    elif "slot_id" in raw:
        errors.append(f"{where}: slot_id must be string, got "
                      f"{type(raw['slot_id']).__name__}")

    if "options" in raw and not isinstance(raw["options"], dict):
        errors.append(f"{where}: options must be object")
    if "customization" in raw and not isinstance(raw["customization"], dict):
        errors.append(f"{where}: customization must be object")
    if "seed" in raw and not isinstance(raw["seed"], int):
        errors.append(f"{where}: seed must be int")
    if "target_rarity" in raw:
        tr = raw["target_rarity"]
        if tr not in VALID_RARITIES:
            errors.append(f"{where}: target_rarity must be one of "
                          f"{VALID_RARITIES}, got {tr!r}")

    # Customization shape: required keys present (uniform schema —
    # null/[] values fine, but the keys must exist for downstream
    # tooling to read them safely).
    cust = raw.get("customization")
    if isinstance(cust, dict):
        for key in _REQUIRED_CUST_KEYS:
            if key not in cust:
                errors.append(f"{where}.customization: missing key {key!r} "
                              f"(present-but-null is fine; just must exist)")
        # feature_bans must be a list if present and non-null.
        fb = cust.get("feature_bans")
        if fb is not None and not isinstance(fb, list):
            errors.append(f"{where}.customization.feature_bans: expected list, "
                          f"got {type(fb).__name__}")

    # `notes` if present must be a string under 200 chars (roadmap says
    # under 100; we allow some headroom but not unbounded).
    notes = raw.get("notes", "")
    if notes is not None and not isinstance(notes, str):
        errors.append(f"{where}: notes must be string")
    elif isinstance(notes, str) and len(notes) > 200:
        errors.append(f"{where}: notes too long ({len(notes)} chars; max 200)")

    return errors


def _validate_slot_options(raw: dict, idx: int) -> list[str]:
    """Run the slot's options through the actual spec_builder pipeline.

    This catches structural and semantic errors a shape check can't:
    bad enum values, missing required axes, axis-incompatibility issues
    that spec_builder rejects. We do this at plan-load time so the
    batch runner never gets a slot that's guaranteed to crash."""
    errors: list[str] = []
    if not isinstance(raw.get("options"), dict):
        return errors  # already flagged in shape check
    try:
        from forge.orchestrator.spec_builder import build_spec
        # Build a synthetic lang_name to satisfy build_spec; we don't
        # care about the result, only that it doesn't throw.
        cust = raw.get("customization") or {}
        kwargs = {}
        for slot_key, spec_key in (
            ("persona", "persona"),
            ("era", "era"),
            ("theme", "keyword_theme"),
            ("phrasebook", "phrasebook"),
            ("feature_bans", "feature_bans"),
        ):
            if slot_key in cust and cust[slot_key] is not None:
                kwargs[spec_key] = cust[slot_key]
        build_spec(raw["options"], "validation_probe", **kwargs)
    except Exception as e:
        errors.append(f"slot[{idx}].options: build_spec rejected: "
                      f"{type(e).__name__}: {e}")
    return errors


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def make_slot_plan(slot_file_path: str | Path) -> list[Slot]:
    """Load and validate a slot file. Returns a list of Slot objects.

    Validation collects ALL errors before raising — a single pass
    surfaces every problem in the file rather than failing at the
    first issue and forcing iterative re-runs.

    Raises:
        FileNotFoundError: file doesn't exist.
        SlotPlanError: file exists but has validation issues.
        json.JSONDecodeError: file isn't valid JSON.
    """
    path = Path(slot_file_path)
    if not path.exists():
        raise FileNotFoundError(f"slot file not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise SlotPlanError(path, [
            f"slot file must contain a JSON array of slot objects, "
            f"got {type(raw).__name__}"
        ])

    errors: list[str] = []
    seen_ids: dict[str, int] = {}
    for i, slot_raw in enumerate(raw):
        shape_errors = _validate_slot_shape(slot_raw, i)
        errors.extend(shape_errors)
        # Track slot_id duplicates only when we successfully parsed an id.
        if isinstance(slot_raw, dict):
            sid = slot_raw.get("slot_id")
            if isinstance(sid, str) and sid:
                if sid in seen_ids:
                    errors.append(f"slot[{i}]: duplicate slot_id {sid!r} "
                                  f"(also at slot[{seen_ids[sid]}])")
                else:
                    seen_ids[sid] = i
        # Only run the deeper options-validation if shape passed —
        # otherwise we'd error-cascade.
        if not shape_errors:
            errors.extend(_validate_slot_options(slot_raw, i))

    if errors:
        raise SlotPlanError(path, errors)

    return [Slot(**_normalize_slot_raw(r)) for r in raw]


def _normalize_slot_raw(raw: dict) -> dict:
    """Shape a raw dict into Slot constructor kwargs. Strips unknown
    top-level keys (slot files can carry curator metadata that doesn't
    belong in the runtime Slot)."""
    return {
        "slot_id": raw["slot_id"],
        "options": dict(raw["options"]),
        "customization": dict(raw["customization"]),
        "seed": int(raw["seed"]),
        "target_rarity": raw["target_rarity"],
        "notes": raw.get("notes", ""),
    }


# ---------------------------------------------------------------------------
# Convenience: serialize back (used by tests for round-trip checks)
# ---------------------------------------------------------------------------

def slot_to_dict(slot: Slot) -> dict:
    """Serialize a Slot back to the dict form a slot file expects.
    Round-trips through `make_slot_plan` cleanly."""
    return {
        "slot_id": slot.slot_id,
        "options": dict(slot.options),
        "customization": dict(slot.customization),
        "seed": slot.seed,
        "target_rarity": slot.target_rarity,
        "notes": slot.notes,
    }
