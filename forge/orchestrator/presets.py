"""Era and bundle presets.

Each preset is a partial `options` dict. When a user picks a preset, the
spec_builder layers it BENEATH the user's explicit choices: the user always
wins. Empty dicts mean "no change."

Honest implementation: each value here corresponds to a real axis our
spec_builder already supports, no fake era flags that have no effect.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Era presets
# ---------------------------------------------------------------------------

ERAS: dict[str, dict] = {
    "1960s": {
        # Algol-era: static-typed, manual memory in real form (we transpile),
        # no closures (still honest: generated parser refuses nested funcs).
        "syntax": "c_like",
        "typing": "static",
        "memory": "host_gc",   # documented as "manual" in design_notes
        "comment_style": "block",
        "string_literals": "double",
        "numeric_literals": "decimal_only",
        "default_mutability": "mutable",
        "error_handling": "panic_only",
        "loop_forms": ["while"],
        "multiple_returns": "none",
        "boolean_evaluation": "eager",
    },
    "1970s": {
        # C-era: c_like, mutable, simple loops, no exceptions.
        "syntax": "c_like",
        "typing": "static",
        "memory": "refcount",   # close to manual; documented honestly
        "comment_style": "block",
        "string_literals": "double",
        "numeric_literals": "c_style",
        "default_mutability": "mutable",
        "error_handling": "panic_only",
        "loop_forms": ["while", "c_for"],
        "multiple_returns": "none",
        "boolean_evaluation": "short_circuit",
    },
    "1980s": {
        # Smalltalk/Lisp/early-OO era: dynamic, GC, exceptions.
        "syntax": "c_like",
        "typing": "dynamic",
        "memory": "host_gc",
        "comment_style": "both",
        "string_literals": "both",
        "numeric_literals": "c_style",
        "default_mutability": "mutable",
        "error_handling": "exceptions",
        "loop_forms": ["while", "c_for", "foreach"],
        "multiple_returns": "tuple",
        "boolean_evaluation": "short_circuit",
    },
    "2000s": {
        # Python/Ruby/JS era: dynamic, GC, batteries.
        "syntax": "python_like",
        "typing": "dynamic",
        "memory": "host_gc",
        "comment_style": "line",
        "string_literals": "both",
        "numeric_literals": "c_style",
        "default_mutability": "mutable",
        "error_handling": "exceptions",
        "loop_forms": ["while", "foreach"],
        "multiple_returns": "tuple",
        "boolean_evaluation": "short_circuit",
    },
    "2020s": {
        # Modern: gradual or static, immutable-leaning, expressive errors.
        "syntax": "python_like",
        "typing": "static",
        "memory": "host_gc",
        "comment_style": "line",
        "string_literals": "triple_quoted",
        "numeric_literals": "extended",
        "default_mutability": "immutable",
        "error_handling": "result_type",
        "loop_forms": ["while", "foreach", "loop_break"],
        "multiple_returns": "tuple",
        "boolean_evaluation": "short_circuit",
    },
}


def list_eras() -> list[dict]:
    return [{"key": k, "blurb": _era_blurb(k)} for k in ERAS]


def _era_blurb(key: str) -> str:
    return {
        "1960s": "Algol vibes: static, terse, block comments, no luxuries.",
        "1970s": "C-era, manual feel, simple loops, no exceptions.",
        "1980s": "Smalltalk/early-OO, dynamic, GC, exceptions, tuples.",
        "2000s": "Python/Ruby/JS, dynamic, indented, batteries included.",
        "2020s": "Modern, immutable by default, Result errors, sum-type-ready.",
    }.get(key, "")


def apply_era(era: str | None, opts: dict) -> dict:
    """Layer an era preset BENEATH the user's explicit options.

    Returns a new dict; does not mutate `opts`.
    """
    if not era or era not in ERAS:
        return dict(opts)
    merged = dict(ERAS[era])
    # User wins on conflicts
    for k, v in opts.items():
        merged[k] = v
    return merged
