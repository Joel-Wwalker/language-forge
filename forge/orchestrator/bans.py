"""Feature bans translate user "no_X" choices into option overrides + prompt
instructions.

A ban is a contract: the generated language must NOT support the banned
construct. We enforce this in two layers:

  1. **Spec-level**: the relevant axis is forced to the most-restrictive value
     (e.g. `no_loops` empties `loop_forms`, `no_exceptions` forces
     `error_handling=panic_only`).

  2. **Prompt-level**: a paragraph is added to per-component prompts telling
     the LLM to refuse to generate matching syntax.

The verifier doesn't need awareness, if the language can't parse a banned
construct, the generated tests can't use it either.
"""
from __future__ import annotations


BAN_DEFS: dict[str, dict] = {
    "no_null": {
        "blurb": "No null/None values. Every binding must be initialized to a real value.",
        "option_overrides": {},
        "prompt_note": (
            "The user has banned NULL/None. Reserve `null`/`None` as syntax "
            "errors at the lexer level. The runtime's `toy_truthy` should "
            "treat absence-of-value as impossible (raise instead of return). "
            "Tests must NOT use null/None."
        ),
    },
    "no_exceptions": {
        "blurb": "No try/catch/throw. Errors are a return-value concern.",
        "option_overrides": {"error_handling": "result_type"},
        "prompt_note": (
            "The user has banned exceptions. Do NOT recognize try/catch/throw "
            "in the parser. Use Result types or panic_only style errors. "
            "Tests must not exercise exception handling."
        ),
    },
    "no_mutation": {
        "blurb": "All bindings immutable. No reassignment, ever.",
        "option_overrides": {"default_mutability": "immutable"},
        "prompt_note": (
            "The user has banned mutation. The parser must reject reassignment "
            "(`x = ...` to a previously-bound name). `let mut` is also banned. "
            "Loops that need accumulation must use recursion or fold-style. "
            "Tests must use recursion instead of accumulator-style loops."
        ),
    },
    "no_loops": {
        "blurb": "No iteration constructs. Recursion only.",
        "option_overrides": {"loop_forms": []},
        "prompt_note": (
            "The user has banned all loop forms. The parser must reject "
            "while/for/foreach/etc. The canonical `loops` test MUST be "
            "implemented via recursion (sum 1..10 via a recursive helper)."
        ),
    },
    "no_inheritance": {
        "blurb": "No class inheritance. Composition only.",
        "option_overrides": {},
        "prompt_note": (
            "The user has banned inheritance. If the language has any class/"
            "object syntax, parents/extends/inheritance is forbidden. Document "
            "in design_notes."
        ),
    },
    "no_global_state": {
        "blurb": "No top-level mutable bindings. Everything inside a function.",
        "option_overrides": {},
        "prompt_note": (
            "The user has banned global state. Top-level statements other than "
            "function definitions must be rejected by the parser, EXCEPT a "
            "single `main` entrypoint call. Tests must wrap their code in a "
            "function. Adapt the canonical tests accordingly."
        ),
    },
}


def list_bans() -> list[dict]:
    return [{"key": k, "blurb": v["blurb"]} for k, v in BAN_DEFS.items()]


def apply_bans(bans: list[str], opts: dict) -> dict:
    """Apply each ban's option overrides into `opts`. User-supplied options win."""
    out = dict(opts)
    for ban in bans or []:
        defn = BAN_DEFS.get(ban)
        if not defn:
            continue
        for k, v in defn.get("option_overrides", {}).items():
            # Bans LOSE to user-explicit choices on the same axis
            out.setdefault(k, v)
    return out


def bans_prompt_block(bans: list[str]) -> str:
    """A bullet list of ban instructions to append to per-component prompts."""
    if not bans:
        return ""
    parts = ["\n\n## Banned features (user-supplied: HIGH PRIORITY)\n",
             "The user has explicitly banned the following constructs. The "
             "generated language MUST NOT support them. Honor every ban.\n"]
    for b in bans:
        defn = BAN_DEFS.get(b)
        if defn:
            parts.append(f"- **{b}**: {defn['prompt_note']}")
    return "\n".join(parts)
