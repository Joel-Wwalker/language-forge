"""One-shot generator for v2_phase4.json (600 slots, five families).

Distribution per phase4-instructions.md "Alternative" (user's Part 2
read landed on outcome 2: "feels narrow; lean on new families"):

| family       | slots |
| c_like       | 140   |
| s_expression | 110   |
| stack_based  |  90   |
| ml_like      | 130   |
| logic_like   | 130   |
| total        | 600   |

Within each family, the customization gradient is:
  ~15% vanilla
  ~30% single-axis
  ~30% two-axis
  ~20% three-axis
  ~5%  four+ axis (max-customized)

Not checked in (gitignored via .build_*.py pattern would catch this
if added; for now, it falls under the explicit phase4 script
convention). Run once; output is `forge/catalog/slots/v2_phase4.json`.
"""
from __future__ import annotations

import itertools
import json
import random
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))


PERSONAS = ["dijkstra", "mccarthy", "hickey", "stroustrup", "wirth",
            "wadler", "matz", "ousterhout"]
THEMES = ["pirate", "shakespearean", "corporate", "latin", "cozy"]
PHRASEBOOKS = ["english_storybook", "shakespeare", "child_speak", "ritual"]
ERAS = ["1960s", "1970s", "1980s", "2000s", "2020s"]
BANS = ["no_global_state", "no_null"]  # safe bans; not "no_mutation"/"no_exceptions" which conflict with various defaults

# Per-family persona affinity (gives the plan a small dose of
# "persona that fits the family" so we don't end up with 600 random
# pairings).
FAMILY_PERSONAS = {
    "c_like":       ["stroustrup", "wirth", "ousterhout", "matz", "wadler"],
    "s_expression": ["mccarthy", "hickey", "wadler"],
    "stack_based":  ["wirth", "dijkstra", "matz"],
    "ml_like":      ["wadler", "mccarthy", "hickey", "wirth", "ousterhout"],
    "logic_like":   ["mccarthy", "wadler", "dijkstra", "hickey", "wirth"],
}

# Banned combos: for ml_like + logic_like, certain bans conflict with
# family defaults (no_exceptions overlaps with error_handling=panic_only
# being a tautology; no_mutation is implicit). The plan only uses
# `no_global_state` and `no_null` which are coherence-safe across all
# five families.
SAFE_BANS_BY_FAMILY = {
    "c_like":       BANS,
    "s_expression": BANS,
    "stack_based":  ["no_global_state"],  # no_null conflicts with stack-based nil
    "ml_like":      ["no_global_state"],  # no_null already implicit in option types
    "logic_like":   ["no_global_state"],  # logic has no nullable model
}


# Seeded so re-running the script produces the same plan.
random.seed(20260516)
_seed_counter = 9000


def alloc_seed():
    global _seed_counter
    _seed_counter += 1
    return _seed_counter


def family_prefix(family: str) -> str:
    return {
        "c_like": "c",
        "s_expression": "s",
        "stack_based": "t",
        "ml_like": "m",
        "logic_like": "l",
    }[family]


def make_slot(slot_id: str, family: str, customization: dict,
              target_rarity: str, notes: str) -> dict:
    """Build one slot dict matching the planner's expected shape."""
    return {
        "slot_id": slot_id,
        "options": {
            "syntax": family,
            "typing": "dynamic",
            "memory": "host_gc",
        },
        "customization": {
            "persona": customization.get("persona"),
            "era": customization.get("era"),
            "theme": customization.get("theme"),
            "phrasebook": customization.get("phrasebook"),
            "feature_bans": customization.get("feature_bans") or [],
        },
        "seed": alloc_seed(),
        "target_rarity": target_rarity,
        "notes": notes,
    }


# Customization-gradient distribution as fractions; rounded to integers
# per family allocation.
GRADIENT = {
    "vanilla":   0.15,
    "single":    0.30,
    "two_axis":  0.30,
    "three_axis": 0.20,
    "max_axis":  0.05,
}

# Family allocations (alt-distribution: lean on new families).
FAMILY_ALLOC = {
    "c_like":       140,
    "s_expression": 110,
    "stack_based":   90,
    "ml_like":      130,
    "logic_like":   130,
}

RARITY = {
    "vanilla": "common", "single": "common",
    "two_axis": "rare", "three_axis": "epic", "max_axis": "mythic",
}


def gradient_counts(total: int) -> dict[str, int]:
    """Allocate `total` slots across the customization gradient, with
    rounding that preserves the total."""
    raw = {k: total * v for k, v in GRADIENT.items()}
    rounded = {k: int(v) for k, v in raw.items()}
    diff = total - sum(rounded.values())
    # Hand the remainder to the largest-fractional-part bucket(s).
    fractions = sorted(
        raw.items(), key=lambda kv: kv[1] - int(kv[1]), reverse=True,
    )
    i = 0
    while diff != 0 and i < len(fractions) * 3:
        k = fractions[i % len(fractions)][0]
        if diff > 0:
            rounded[k] += 1
            diff -= 1
        else:
            rounded[k] -= 1
            diff += 1
        i += 1
    assert sum(rounded.values()) == total, (
        f"gradient rounding produced {sum(rounded.values())}, expected {total}"
    )
    return rounded


def pick_single(family: str) -> dict:
    axes = ["persona", "era", "theme", "phrasebook"]
    axis = random.choice(axes)
    if axis == "persona":
        return {"persona": random.choice(FAMILY_PERSONAS[family])}
    if axis == "era":
        return {"era": random.choice(ERAS)}
    if axis == "theme":
        return {"theme": random.choice(THEMES)}
    return {"phrasebook": random.choice(PHRASEBOOKS)}


def pick_two_axis(family: str) -> dict:
    axes_options = [
        ("persona", "era"),
        ("persona", "theme"),
        ("persona", "phrasebook"),
        ("era", "theme"),
        ("era", "phrasebook"),
        ("theme", "phrasebook"),
    ]
    a, b = random.choice(axes_options)
    return _pick_for_axes(family, (a, b))


def pick_three_axis(family: str) -> dict:
    # Choose 3 of {persona, era, theme, phrasebook}.
    all_axes = ["persona", "era", "theme", "phrasebook"]
    picked = tuple(random.sample(all_axes, 3))
    return _pick_for_axes(family, picked)


def pick_max_axis(family: str) -> dict:
    # All 4 axes + a feature ban.
    cust = _pick_for_axes(family, ("persona", "era", "theme", "phrasebook"))
    cust["feature_bans"] = [random.choice(SAFE_BANS_BY_FAMILY[family])]
    return cust


def _pick_for_axes(family: str, axes: tuple) -> dict:
    out = {}
    for axis in axes:
        if axis == "persona":
            out["persona"] = random.choice(FAMILY_PERSONAS[family])
        elif axis == "era":
            out["era"] = random.choice(ERAS)
        elif axis == "theme":
            out["theme"] = random.choice(THEMES)
        elif axis == "phrasebook":
            out["phrasebook"] = random.choice(PHRASEBOOKS)
    return out


def build_family_slots(family: str, count: int) -> list[dict]:
    """Build `count` slots for `family`, distributed across the gradient."""
    slots = []
    gradient_alloc = gradient_counts(count)
    prefix = family_prefix(family)
    idx = 1

    for kind in ["vanilla", "single", "two_axis", "three_axis", "max_axis"]:
        n = gradient_alloc[kind]
        for i in range(n):
            slot_id = f"slot_{prefix}_{idx:03d}"
            if kind == "vanilla":
                cust = {}
                notes = f"vanilla {family}"
            elif kind == "single":
                cust = pick_single(family)
                notes = f"single-axis {family}"
            elif kind == "two_axis":
                cust = pick_two_axis(family)
                notes = f"two-axis {family}"
            elif kind == "three_axis":
                cust = pick_three_axis(family)
                notes = f"three-axis {family}"
            else:
                cust = pick_max_axis(family)
                notes = f"max-customized {family}"
            slots.append(make_slot(slot_id, family, cust, RARITY[kind], notes))
            idx += 1
    return slots


def main():
    all_slots = []
    for family, count in FAMILY_ALLOC.items():
        family_slots = build_family_slots(family, count)
        assert len(family_slots) == count, (
            f"{family}: built {len(family_slots)}, expected {count}"
        )
        all_slots.extend(family_slots)

    assert len(all_slots) == 600, f"total {len(all_slots)}, expected 600"

    print(f"Total slots: {len(all_slots)}")
    fams = Counter(s["options"]["syntax"] for s in all_slots)
    print(f"By family: {dict(fams)}")

    def axes_count(s):
        c = s["customization"]
        return sum([
            bool(c.get("persona")),
            bool(c.get("era")),
            bool(c.get("theme")),
            bool(c.get("phrasebook")),
            bool(c.get("feature_bans")),
        ])

    dist = Counter(axes_count(s) for s in all_slots)
    print(f"Customization axes distribution: {dict(sorted(dist.items()))}")

    # Per-family gradient verification.
    print()
    print("Per-family gradient:")
    for fam in FAMILY_ALLOC:
        fam_slots = [s for s in all_slots if s["options"]["syntax"] == fam]
        fam_dist = Counter(axes_count(s) for s in fam_slots)
        print(f"  {fam} ({len(fam_slots)}): {dict(sorted(fam_dist.items()))}")

    out_path = "forge/catalog/slots/v2_phase4.json"
    Path(out_path).write_text(json.dumps(all_slots, indent=2),
                              encoding="utf-8")
    print(f"\nWrote {out_path}")

    # Validate via the real planner.
    from forge.catalog.planner import make_slot_plan
    try:
        plan = make_slot_plan(out_path)
        print(f"Plan loads cleanly: {len(plan)} slots")
    except Exception as e:
        print(f"PLAN VALIDATION FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
