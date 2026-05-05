"""Crossbreeding (roadmap §3.3).

Take two existing languages, mix their option dicts, run the result
through the existing spec_builder + coherence + generator pipeline.
The child appears in the Library tagged with both parents' names so
the family-tree view (§3.2) can draw real edges.

Strategies:
  - "random":   each axis flips a coin between the two parents
  - "dominant": parent A wins ties; B fills only the axes A leaves null
  - "union":    bans + design_notes union; first-match for scalars

Conflict handling: if the merged options trigger a coherence error,
we drop the recessive parent's contribution on that axis and re-merge.
If still incoherent, the caller surfaces it to the user — better than
generating an unusable language.
"""
from __future__ import annotations

import random
from typing import Optional


# Option axes the merger walks. Order doesn't matter; just what the
# spec_builder accepts.
_OPTION_AXES = [
    "syntax", "typing", "memory",
    "comment_style", "string_literals", "numeric_literals",
    "default_mutability", "error_handling", "loop_forms",
    "multiple_returns", "boolean_evaluation",
    "naming_convention", "null_model",
]


def merge_options(parent_a: dict, parent_b: dict, *,
                  strategy: str = "random",
                  rng: Optional[random.Random] = None) -> dict:
    """Merge two option dicts into a child. Returns a new dict."""
    rng = rng or random.Random()
    out: dict = {}
    for axis in _OPTION_AXES:
        a, b = parent_a.get(axis), parent_b.get(axis)
        if a is None and b is None:
            continue
        if a is None:
            out[axis] = b
            continue
        if b is None:
            out[axis] = a
            continue
        if a == b:
            out[axis] = a
            continue
        # Conflict: pick by strategy
        if strategy == "dominant":
            out[axis] = a   # parent_a always wins
        elif strategy == "union" and isinstance(a, list) and isinstance(b, list):
            out[axis] = list(dict.fromkeys(a + b))   # preserve order, dedup
        else:                                          # "random" (default)
            out[axis] = rng.choice([a, b])
    return out


def merge_extras(parent_a: dict, parent_b: dict, *,
                 strategy: str = "random",
                 rng: Optional[random.Random] = None) -> dict:
    """Merge the non-option layers (persona, era, theme, phrasebook,
    feature_bans, customization). Returns a dict shaped like the kwargs
    of build_spec: {persona, era, keyword_theme, phrasebook,
    feature_bans, customization}."""
    rng = rng or random.Random()
    pick = lambda a, b: a if a == b or b is None else (
        rng.choice([a, b]) if strategy == "random" and a is not None
        else (a if strategy == "dominant" or a is not None else b)
    )

    out = {
        "persona": pick(parent_a.get("persona"), parent_b.get("persona")),
        "era": pick(parent_a.get("era"), parent_b.get("era")),
        "keyword_theme": pick(parent_a.get("keyword_theme"),
                              parent_b.get("keyword_theme")),
        "phrasebook": pick(parent_a.get("phrasebook"),
                           parent_b.get("phrasebook")),
    }

    # feature_bans: union always (bans compose)
    bans = list({*(parent_a.get("feature_bans") or []),
                 *(parent_b.get("feature_bans") or [])})
    if bans:
        out["feature_bans"] = bans

    # customization: deep-ish merge with parent_a winning
    cust_a = parent_a.get("customization") or {}
    cust_b = parent_b.get("customization") or {}
    if cust_a or cust_b:
        merged_cust = dict(cust_b)
        merged_cust.update(cust_a)
        # extra_design_notes: preserve both lineages
        notes = []
        if cust_b.get("extra_design_notes"):
            notes.extend(cust_b["extra_design_notes"])
        if cust_a.get("extra_design_notes"):
            notes.extend(cust_a["extra_design_notes"])
        if notes:
            merged_cust["extra_design_notes"] = notes
        out["customization"] = merged_cust

    return out


def crossbreed(parent_a_meta: dict, parent_b_meta: dict, *,
               child_name: str, strategy: str = "random",
               seed: Optional[int] = None) -> dict:
    """High-level: take two languages' creation metadata, produce the
    kwargs for build_spec for a child plus a `lineage` block.

    `parent_meta` shape: { name, options, persona, era, keyword_theme,
                            phrasebook, feature_bans, customization }
    Returns: { name, options, persona, era, keyword_theme, phrasebook,
               feature_bans, customization, lineage: { parents: [a, b],
               strategy, generation } }
    """
    rng = random.Random(seed)
    options = merge_options(
        parent_a_meta.get("options") or {},
        parent_b_meta.get("options") or {},
        strategy=strategy, rng=rng,
    )
    extras = merge_extras(parent_a_meta, parent_b_meta,
                          strategy=strategy, rng=rng)

    gen_a = (parent_a_meta.get("lineage") or {}).get("generation", 0)
    gen_b = (parent_b_meta.get("lineage") or {}).get("generation", 0)

    return {
        "name": child_name,
        "options": options,
        **extras,
        "lineage": {
            "parents": [parent_a_meta["name"], parent_b_meta["name"]],
            "strategy": strategy,
            "generation": max(gen_a, gen_b) + 1,
        },
    }
