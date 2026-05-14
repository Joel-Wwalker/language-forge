"""One-shot generator for v2_phase4_preflight.json (100 slots).

Not checked in. Run once; output is the slot plan JSON.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

PERSONAS = ["dijkstra", "mccarthy", "hickey", "stroustrup", "wirth", "wadler", "matz", "ousterhout"]
THEMES = ["pirate", "shakespearean", "corporate", "latin", "cozy"]
PHRASEBOOKS = ["english_storybook", "shakespeare", "child_speak", "ritual"]
ERAS = ["1960s", "1970s", "1980s", "2000s", "2020s"]

_seed_counter = 7000


def alloc_seed():
    global _seed_counter
    _seed_counter += 1
    return _seed_counter


def slot(slot_id, syntax, target_rarity, *, persona=None, era=None,
         theme=None, phrasebook=None, feature_bans=None, notes=""):
    return {
        "slot_id": slot_id,
        "options": {"syntax": syntax, "typing": "dynamic", "memory": "host_gc"},
        "customization": {
            "persona": persona,
            "era": era,
            "theme": theme,
            "phrasebook": phrasebook,
            "feature_bans": feature_bans or [],
        },
        "seed": alloc_seed(),
        "target_rarity": target_rarity,
        "notes": notes,
    }


slots = []

# c_like - 50 slots
for i in range(15):
    slots.append(slot(f"slot_c_{i+1:03d}", "c_like", "common",
                      notes="vanilla c_like"))
for i in range(3):
    slots.append(slot(f"slot_c_{16+i:03d}", "c_like", "common",
                      persona=PERSONAS[i], notes="single-axis persona"))
for i in range(3):
    slots.append(slot(f"slot_c_{19+i:03d}", "c_like", "common",
                      era=ERAS[i], notes="single-axis era"))
for i in range(3):
    slots.append(slot(f"slot_c_{22+i:03d}", "c_like", "common",
                      theme=THEMES[i], notes="single-axis theme"))
for i in range(3):
    slots.append(slot(f"slot_c_{25+i:03d}", "c_like", "common",
                      phrasebook=PHRASEBOOKS[i], notes="single-axis phrasebook"))

two_axis = [
    {"persona": "stroustrup", "era": "1980s"},
    {"persona": "wirth", "era": "1970s"},
    {"persona": "matz", "era": "2000s"},
    {"persona": "hickey", "theme": "cozy"},
    {"persona": "dijkstra", "theme": "latin"},
    {"persona": "ousterhout", "theme": "corporate"},
    {"era": "1980s", "theme": "pirate"},
    {"era": "1960s", "theme": "shakespearean"},
    {"era": "2020s", "theme": "corporate"},
    {"theme": "pirate", "phrasebook": "shakespeare"},
    {"theme": "cozy", "phrasebook": "child_speak"},
    {"era": "2000s", "phrasebook": "ritual"},
]
for i, kw in enumerate(two_axis):
    slots.append(slot(f"slot_c_{28+i:03d}", "c_like", "rare",
                      notes="two-axis", **kw))

three_axis = [
    {"persona": "stroustrup", "era": "1980s", "theme": "corporate"},
    {"persona": "mccarthy", "era": "1960s", "phrasebook": "ritual"},
    {"persona": "wadler", "era": "2020s", "theme": "latin"},
    {"persona": "hickey", "era": "2000s", "theme": "cozy"},
    {"persona": "wirth", "era": "1970s", "theme": "pirate"},
    {"era": "1980s", "theme": "shakespearean", "phrasebook": "shakespeare"},
    {"persona": "matz", "era": "2020s", "phrasebook": "english_storybook"},
    {"persona": "dijkstra", "theme": "latin", "phrasebook": "ritual"},
]
for i, kw in enumerate(three_axis):
    slots.append(slot(f"slot_c_{40+i:03d}", "c_like", "epic",
                      notes="three-axis", **kw))

max_cust_c = [
    {"persona": "stroustrup", "era": "1980s", "theme": "corporate",
     "phrasebook": "ritual", "feature_bans": ["no_global_state"]},
    {"persona": "wadler", "era": "2000s", "theme": "shakespearean",
     "phrasebook": "shakespeare", "feature_bans": ["no_global_state"]},
    {"persona": "mccarthy", "era": "1960s", "theme": "cozy",
     "phrasebook": "english_storybook", "feature_bans": ["no_null"]},
]
for i, kw in enumerate(max_cust_c):
    slots.append(slot(f"slot_c_{48+i:03d}", "c_like", "mythic",
                      notes="max-custom", **kw))

# s_expression - 25
for i in range(7):
    slots.append(slot(f"slot_s_{i+1:03d}", "s_expression", "common",
                      notes="vanilla s_expression"))
single_s = [
    {"persona": "mccarthy"}, {"persona": "hickey"},
    {"era": "1960s"}, {"era": "1980s"},
    {"theme": "pirate"}, {"theme": "cozy"},
    {"phrasebook": "ritual"},
]
for i, kw in enumerate(single_s):
    slots.append(slot(f"slot_s_{8+i:03d}", "s_expression", "common",
                      notes="single-axis", **kw))

two_s = [
    {"persona": "mccarthy", "era": "1960s"},
    {"persona": "hickey", "theme": "cozy"},
    {"era": "2000s", "theme": "latin"},
    {"theme": "pirate", "phrasebook": "shakespeare"},
    {"persona": "wadler", "era": "2020s"},
    {"persona": "dijkstra", "theme": "latin"},
]
for i, kw in enumerate(two_s):
    slots.append(slot(f"slot_s_{15+i:03d}", "s_expression", "rare",
                      notes="two-axis", **kw))

three_s = [
    {"persona": "mccarthy", "era": "1960s", "theme": "latin"},
    {"persona": "hickey", "era": "2020s", "theme": "cozy"},
    {"persona": "wadler", "theme": "shakespearean", "phrasebook": "shakespeare"},
    {"era": "1980s", "theme": "corporate", "phrasebook": "ritual"},
]
for i, kw in enumerate(three_s):
    slots.append(slot(f"slot_s_{21+i:03d}", "s_expression", "epic",
                      notes="three-axis", **kw))

slots.append(slot("slot_s_025", "s_expression", "mythic",
                  persona="mccarthy", era="1960s", theme="latin",
                  phrasebook="ritual", feature_bans=["no_global_state"],
                  notes="max-custom"))

# stack_based - 25
for i in range(7):
    slots.append(slot(f"slot_t_{i+1:03d}", "stack_based", "common",
                      notes="vanilla stack_based"))
single_t = [
    {"persona": "wirth"}, {"persona": "dijkstra"},
    {"era": "1970s"}, {"era": "1980s"},
    {"theme": "pirate"}, {"theme": "corporate"},
    {"phrasebook": "shakespeare"},
]
for i, kw in enumerate(single_t):
    slots.append(slot(f"slot_t_{8+i:03d}", "stack_based", "common",
                      notes="single-axis", **kw))

two_t = [
    {"persona": "wirth", "era": "1970s"},
    {"persona": "dijkstra", "theme": "latin"},
    {"era": "1980s", "theme": "pirate"},
    {"theme": "cozy", "phrasebook": "english_storybook"},
    {"persona": "ousterhout", "era": "2000s"},
    {"persona": "stroustrup", "theme": "corporate"},
]
for i, kw in enumerate(two_t):
    slots.append(slot(f"slot_t_{15+i:03d}", "stack_based", "rare",
                      notes="two-axis", **kw))

three_t = [
    {"persona": "wirth", "era": "1970s", "theme": "latin"},
    {"persona": "dijkstra", "era": "1960s", "phrasebook": "ritual"},
    {"era": "1980s", "theme": "pirate", "phrasebook": "shakespeare"},
    {"persona": "matz", "theme": "corporate", "phrasebook": "child_speak"},
]
for i, kw in enumerate(three_t):
    slots.append(slot(f"slot_t_{21+i:03d}", "stack_based", "epic",
                      notes="three-axis", **kw))

slots.append(slot("slot_t_025", "stack_based", "mythic",
                  persona="wirth", era="1970s", theme="pirate",
                  phrasebook="english_storybook",
                  feature_bans=["no_exceptions"], notes="max-custom"))


print(f"Total slots: {len(slots)}")
from collections import Counter
fams = Counter(s["options"]["syntax"] for s in slots)
print(f"By family: {dict(fams)}")
cust_dist = Counter(
    sum(1 for k, v in s["customization"].items()
        if k != "feature_bans" and v) +
    (1 if s["customization"]["feature_bans"] else 0)
    for s in slots
)
print(f"Customization-axis count distribution: {dict(sorted(cust_dist.items()))}")

out_path = "forge/catalog/slots/v2_phase4_preflight.json"
Path(out_path).write_text(json.dumps(slots, indent=2), encoding="utf-8")
print(f"Wrote {out_path}")

# Validate by trying to load it via the real planner.
from forge.catalog.planner import make_slot_plan
try:
    plan = make_slot_plan(out_path)
    print(f"Plan loads cleanly: {len(plan)} slots")
except Exception as e:
    print(f"Plan validation FAILED: {e}")
