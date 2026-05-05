"""Coherence pre-validator for option combinations.

Direct response to the design doc's warning: "Otherwise you'll get
languages that feel like they were assembled by a committee that never
met."

Each rule examines a fully-merged option dict (after era + bans + user
choices) and returns a list of `Issue` objects. Issues come in two
severities:

  - "error": the combo is genuinely incoherent or self-defeating; the
    spec_builder raises before the resolver burns LLM tokens.
  - "warning": the combo is allowed but unusual or self-fighting; we
    record it in `design_notes` so the resolver and downstream prompts
    can see it.

Rules are intentionally explicit so they read like documentation. Add
new rules at the bottom; do not silently fold them into the default
overlays.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass
class Issue:
    severity: str       # "error" | "warning"
    code: str           # short stable identifier, e.g. "null_model_no_failure_path"
    message: str
    suggestion: Optional[str] = None


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def _check_null_model_has_failure_path(opts: dict) -> Optional[Issue]:
    """null_model = none requires SOME way to express absence/failure.

    Without null and without Result/Option types, the language has no way
    to encode "lookup failed" or "this value isn't here yet" beyond
    panicking. That's defensible (Erlang's "let it crash") but unusual;
    flag as a warning.
    """
    if opts.get("null_model") == "none":
        eh = opts.get("error_handling")
        if eh not in ("result_type", "exceptions"):
            return Issue(
                severity="warning",
                code="null_model_no_failure_path",
                message=("null_model=none with error_handling=panic_only leaves no "
                         "way to express 'value absent' beyond crashing."),
                suggestion="consider error_handling=result_type or exceptions",
            )
    return None


def _check_immutable_eager_eval(opts: dict) -> Optional[Issue]:
    """Eager evaluation in a fully-immutable language has no observable effect.

    The whole point of eager evaluation is to make side effects visible.
    Immutable + eager fights itself.
    """
    if opts.get("default_mutability") == "immutable" and opts.get("boolean_evaluation") == "eager":
        return Issue(
            severity="warning",
            code="immutable_eager_pointless",
            message=("default_mutability=immutable with boolean_evaluation=eager: "
                     "eager evaluation is observable only via side effects, but "
                     "an immutable language has fewer of those."),
            suggestion="boolean_evaluation=short_circuit pairs better with immutability",
        )
    return None


def _check_no_loops_no_recursion(opts: dict) -> Optional[Issue]:
    """no_loops without functions is a fundamentally incomplete language."""
    bans = set(opts.get("feature_bans") or [])
    if "no_loops" in bans:
        # We don't ban first-class functions today, so recursion is always
        # available. Just warn that loops are off.
        return Issue(
            severity="warning",
            code="no_loops_pure_recursion",
            message=("feature_bans includes no_loops: every iterative test must be "
                     "rewritten with recursion. The canonical 'loops' test sums "
                     "1..10 via a recursive helper instead."),
        )
    return None


def _check_static_python_combo(opts: dict) -> Optional[Issue]:
    """Static + python_like is fine but the resolver needs to pick gradual.

    This isn't an error; it's a heads-up that a downstream stage will make
    a non-obvious decision so the design_notes should mention it.
    """
    if opts.get("typing") == "static" and opts.get("syntax") == "python_like":
        return Issue(
            severity="warning",
            code="static_python_uses_gradual",
            message=("typing=static with syntax=python_like: the resolver picks "
                     "gradual typing with `: type` annotations (Python's idiom)."),
        )
    return None


def _check_eager_short_circuit_op_set(opts: dict) -> Optional[Issue]:
    """boolean_evaluation=eager removes the meaning of `&&`/`||` short-circuit.

    Mostly informational; we still emit `&&`/`||` operators but their
    semantics differ. The runtime has eager helpers.
    """
    if opts.get("boolean_evaluation") == "eager":
        return Issue(
            severity="warning",
            code="eager_logical_ops",
            message=("boolean_evaluation=eager: `&&` / `||` evaluate both sides "
                     "always. Avoid using them in side-effecting expressions."),
        )
    return None


def _check_no_exceptions_must_have_failure(opts: dict) -> Optional[Issue]:
    """no_exceptions without result_type or panic leaves no way to fail."""
    bans = set(opts.get("feature_bans") or [])
    if "no_exceptions" in bans and opts.get("error_handling") == "exceptions":
        return Issue(
            severity="error",
            code="no_exceptions_but_exceptions_chosen",
            message=("feature_bans includes no_exceptions but error_handling is "
                     "set to exceptions. These contradict."),
            suggestion="set error_handling to result_type or panic_only",
        )
    return None


def _check_no_mutation_immutable_consistency(opts: dict) -> Optional[Issue]:
    """no_mutation ban implies default_mutability=immutable.

    The ban already forces this via `apply_bans`, but if the user
    explicitly chose default_mutability=mutable AND added the ban, that's
    a contradiction.
    """
    bans = set(opts.get("feature_bans") or [])
    if "no_mutation" in bans and opts.get("default_mutability") == "mutable":
        return Issue(
            severity="error",
            code="no_mutation_but_mutable_default",
            message=("feature_bans includes no_mutation but default_mutability "
                     "is mutable. These contradict."),
            suggestion="drop the ban or set default_mutability=immutable",
        )
    return None


def _check_s_expression_static_uses_inference(opts: dict) -> Optional[Issue]:
    """static + s_expression -> Typed Racket / Hy-style: separate `(: name type)`
    annotations with inference (the Lisp-typed tradition).

    Heads-up only; the typing_overlay handles it correctly. We surface it
    so design_notes mentions the choice.
    """
    if opts.get("typing") == "static" and opts.get("syntax") == "s_expression":
        return Issue(
            severity="warning",
            code="static_s_expression_typed_racket",
            message=("typing=static with syntax=s_expression: types are declared "
                     "via `(: name type)` forms (Typed Racket / Hy convention) "
                     "with inference enabled."),
        )
    return None


def _check_s_expression_phrasebook_conflict(opts: dict) -> Optional[Issue]:
    """phrasebook + s_expression is a contradiction.

    Phrasebooks replace keyword forms with sentence templates ("set <name>
    to <value>."). S-expression languages have no statement-shaped forms
    to template — every form is a parenthesized list. The two compose
    poorly; warn loudly.
    """
    # We can't see the phrasebook field directly here (it lives on
    # customization, not options), but the option dict gets a synthetic
    # "phrasebook" key when one is set. Best-effort detection.
    if opts.get("syntax") == "s_expression" and opts.get("phrasebook"):
        return Issue(
            severity="warning",
            code="s_expression_with_phrasebook",
            message=("syntax=s_expression with a phrasebook: phrasebooks template "
                     "statement-shaped forms, but Lisp languages have no statements "
                     "(every form is `(op ...)`). The phrasebook will be ignored "
                     "in most positions."),
            suggestion="drop the phrasebook, or pick c_like / python_like instead",
        )
    return None


def _check_stack_based_phrasebook_conflict(opts: dict) -> Optional[Issue]:
    """phrasebook + stack_based is incompatible.

    Phrasebooks template statement-shaped forms ("set <name> to <value>.").
    Stack-based languages don't have statements - they have a stream of
    tokens that manipulate an implicit stack. The phrasebook would be
    ignored almost everywhere. Warn loudly.
    """
    if opts.get("syntax") == "stack_based" and opts.get("phrasebook"):
        return Issue(
            severity="warning",
            code="stack_based_with_phrasebook",
            message=("syntax=stack_based with a phrasebook: phrasebooks template "
                     "statement-shaped forms, but stack-based languages have no "
                     "statements (just a stream of tokens that push/pop the "
                     "data stack). The phrasebook will be ignored."),
            suggestion="drop the phrasebook, or pick c_like / python_like / s_expression",
        )
    return None


def _check_stack_based_no_loops_uses_recursion(opts: dict) -> Optional[Issue]:
    """no_loops + stack_based forces all iteration through recursion.

    Forth typically uses `begin ... until` for iteration. Banning loops
    is more restrictive in Forth than in c_like because Forth has no
    obvious functional alternatives like Lisp's recursion-into-tail-call.
    Doable but unusual.
    """
    bans = set(opts.get("feature_bans") or [])
    if opts.get("syntax") == "stack_based" and "no_loops" in bans:
        return Issue(
            severity="warning",
            code="stack_based_no_loops_unusual",
            message=("syntax=stack_based + feature_bans=no_loops: stack languages "
                     "lean heavily on `begin/until` and `do/loop`. Banning these "
                     "forces every algorithm into recursive colon definitions, "
                     "which is doable but feels alien."),
        )
    return None


def _check_s_expression_braces_indent_mismatch(opts: dict) -> Optional[Issue]:
    """s_expression languages use parens, not braces or indent.

    `comment_style=nestable_block` is fine (`#| ... |#` nests in Scheme).
    But if a user picks options that explicitly imply a c_like / python_like
    surface (via apply_era's preset overrides), we want to flag it.

    For v1 this is informational; we don't refuse the combo because
    apply_era already overlays per-syntax defaults.
    """
    return None  # placeholder for future tightening


def _check_loop_forms_empty(opts: dict) -> Optional[Issue]:
    """Empty loop_forms with no `no_loops` ban is suspicious."""
    lf = opts.get("loop_forms")
    bans = set(opts.get("feature_bans") or [])
    if lf == [] and "no_loops" not in bans:
        return Issue(
            severity="warning",
            code="loop_forms_empty_without_ban",
            message=("loop_forms is empty but the no_loops ban isn't set. "
                     "The language will have no iteration constructs."),
            suggestion="add 'while' to loop_forms or set the no_loops ban",
        )
    return None


_RULES = [
    _check_null_model_has_failure_path,
    _check_immutable_eager_eval,
    _check_no_loops_no_recursion,
    _check_static_python_combo,
    _check_eager_short_circuit_op_set,
    _check_no_exceptions_must_have_failure,
    _check_no_mutation_immutable_consistency,
    _check_s_expression_static_uses_inference,
    _check_s_expression_phrasebook_conflict,
    _check_s_expression_braces_indent_mismatch,
    _check_stack_based_phrasebook_conflict,
    _check_stack_based_no_loops_uses_recursion,
    _check_loop_forms_empty,
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check(opts: dict) -> list[Issue]:
    """Run every rule against `opts`. Returns a list of Issue objects."""
    out: list[Issue] = []
    for rule in _RULES:
        issue = rule(opts)
        if issue is not None:
            out.append(issue)
    return out


def errors(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "error"]


def warnings(issues: Iterable[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "warning"]


class CoherenceError(ValueError):
    """Raised when a hard incoherence is detected in the option combination."""

    def __init__(self, issues: list[Issue]):
        self.issues = issues
        msg_lines = ["coherence check failed:"]
        for i in issues:
            msg_lines.append(f"  - [{i.code}] {i.message}")
            if i.suggestion:
                msg_lines.append(f"    suggestion: {i.suggestion}")
        super().__init__("\n".join(msg_lines))
