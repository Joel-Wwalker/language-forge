"""Keyword themes, gimmicky but cheap and composable.

Each theme is a dict mapping canonical keyword names to their themed spelling.
The spec_builder folds these into `keyword_overrides` so they go through the
same validated pipeline as user-supplied keyword overrides.

Honest implementation: the generated parser actually accepts only the themed
keywords. Tests are written in those keywords. No `func`-shaped parsing
that pretends to be `arrr`.
"""
from __future__ import annotations


THEMES: dict[str, dict[str, str]] = {
    "pirate": {
        "var": "loot",
        "func": "yarrn",
        "return": "deliver",
        "if": "ifnay",
        "else": "elseways",
        "while": "keelhaul",
        "true": "aye",
        "false": "nay",
        "null": "ghost",
    },
    "shakespearean": {
        "var": "thy",
        "func": "summon",
        "return": "yieldeth",
        "if": "perchance",
        "else": "otherwise",
        "while": "whilst",
        "true": "verily",
        "false": "naught",
        "null": "nothing",
    },
    "corporate": {
        "var": "asset",
        "func": "deliverable",
        "return": "deliver",
        "if": "if_aligned",
        "else": "otherwise",
        "while": "loop",
        "true": "approved",
        "false": "rejected",
        "null": "pending",
    },
    "latin": {
        "var": "sit",
        "func": "munus",
        "return": "redde",
        "if": "si",
        "else": "aliter",
        "while": "dum",
        "true": "verum",
        "false": "falsum",
        "null": "nihil",
    },
    "cozy": {
        "var": "thing",
        "func": "recipe",
        "return": "share",
        "if": "when",
        "else": "otherwise",
        "while": "keep",
        "true": "yes",
        "false": "no",
        "null": "empty",
    },
}


def list_themes() -> list[dict]:
    return [{"key": k, "preview": _preview(k)} for k in THEMES]


def _preview(key: str) -> str:
    t = THEMES[key]
    return f"{t['func']} hi() {{ {t['return']} {t['true']}; }}"


def get_theme(key: str | None) -> dict[str, str]:
    if not key:
        return {}
    return dict(THEMES.get(key, {}))
