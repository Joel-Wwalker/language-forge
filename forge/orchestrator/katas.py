"""Kata generation, self-validation, and checking.

A kata is a small programming problem the user solves by writing one
function in their generated language. We:

  1. Ask the LLM to produce a 5-kata pack with reference solutions.
  2. Self-validate: actually run each reference solution through the
     language's compiler and check stdout matches `expected`. Drop any
     kata whose own reference fails.
  3. Persist the surviving katas to `<lang>/katas.json`.

Checking a user's submission uses the same compile+run path: append
`print(<call>)` lines for each test, compare stdout to `expected`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from .llm_client import LLMClient
from .substitution import apply_spec_keyword_substitutions


def substitute_kata_for_target(kata: dict, spec: dict) -> dict:
    """Apply the spec's keyword/comment/literal substitutions to a curated
    kata's source fields. Returns a NEW kata dict; the original is not
    mutated.

    Phase 1.5 bugfix Fix 2 — Bug 3 root cause: smoke test loaded the
    `classics` pack (canonical c_like) and handed it straight to a
    themed-c_like compiler (e.g. pirate phrasebook with `func → yarrn`).
    The themed parser refused to parse `func`, every kata failed, and
    the slot smoked-failed. The fix is to push the canonical kata source
    through the spec's substitution layer at the entry boundary, so by
    the time `_batch_validate` / `_self_validate` see the kata's source,
    it speaks the target's dialect.

    Substitutes (when present on the kata):
      - reference_solution      (file_role='test_source')
      - helpers                 (file_role='test_source')
      - starter_code            (file_role='test_source')
      - tests[].call            (file_role='test_source')
      - tests[].expected        (file_role='expected_output')

    Idempotent: a kata already in target dialect (e.g. LLM-translated)
    is unaffected because canonical tokens won't be present to match.
    Safe to apply unconditionally."""
    out = dict(kata)
    if isinstance(kata.get("reference_solution"), str):
        out["reference_solution"] = apply_spec_keyword_substitutions(
            kata["reference_solution"], spec, file_role="test_source")
    if isinstance(kata.get("helpers"), str) and kata["helpers"]:
        out["helpers"] = apply_spec_keyword_substitutions(
            kata["helpers"], spec, file_role="test_source")
    if isinstance(kata.get("starter_code"), str):
        out["starter_code"] = apply_spec_keyword_substitutions(
            kata["starter_code"], spec, file_role="test_source")
    tests = kata.get("tests")
    if isinstance(tests, list):
        new_tests = []
        for t in tests:
            if not isinstance(t, dict):
                new_tests.append(t)
                continue
            nt = dict(t)
            if isinstance(t.get("call"), str):
                nt["call"] = apply_spec_keyword_substitutions(
                    t["call"], spec, file_role="test_source")
            if isinstance(t.get("expected"), str):
                nt["expected"] = apply_spec_keyword_substitutions(
                    t["expected"], spec, file_role="expected_output")
            new_tests.append(nt)
        out["tests"] = new_tests
    return out


def atomic_write_json(path: Path, data: dict, *, indent: int = 2) -> None:
    """Write a JSON dict atomically: serialize to a temp file in the same
    directory, then `os.replace()` it onto the target. This eliminates
    the partial-write window where a crashed/interrupted writer leaves
    behind half-written JSON that breaks `load_pack()` on the next read.

    `allow_nan=False` rejects NaN/Infinity floats which serialize as
    invalid JSON tokens (`NaN`, `Infinity`) - any caller passing those
    gets a TypeError up front instead of silent corruption.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(data, indent=indent, allow_nan=False, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        # Best-effort cleanup if replace didn't happen.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


# JSON schema fed to the LLM via tool-use to force structured output.
KATA_PACK_SCHEMA = {
    "type": "object",
    "required": ["katas"],
    "properties": {
        "katas": {
            "type": "array",
            "minItems": 1,
            "maxItems": 8,
            "items": {
                "type": "object",
                "required": [
                    "id", "title", "difficulty", "problem",
                    "function_name", "starter_code", "reference_solution", "tests",
                ],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "title": {"type": "string", "maxLength": 80},
                    "difficulty": {"enum": ["easy", "medium", "hard"]},
                    "problem": {"type": "string"},
                    "function_name": {"type": "string"},
                    "starter_code": {"type": "string"},
                    "reference_solution": {"type": "string"},
                    "tests": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 10,
                        "items": {
                            "type": "object",
                            "required": ["call", "expected"],
                            "properties": {
                                "call": {"type": "string"},
                                "expected": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    "additionalProperties": False,
}


def generate_katas(spec: dict, lang_dir: Path, client: LLMClient,
                   on_progress=None, *, fix_attempts: int = 2,
                   time_budget_s: float = 120.0) -> dict:
    """Generate, validate, and persist a kata pack for the language.

    For any kata whose reference fails self-validation, we re-ask the
    model with the actual parser/runtime error as feedback. Up to
    `fix_attempts` retries per kata. Surviving katas get persisted;
    drops are recorded with their final error.

    A wall-clock budget caps total time spent on fix-up loops so the GUI
    sees results in a predictable window (was reported taking 5+ minutes
    on freshly-created languages with broken codegen). Any kata still
    failing past the budget is recorded as dropped instead of grinding
    through more LLM calls.
    """
    from .generator import _load_prompt, _interp
    import time as _time

    deadline = _time.monotonic() + time_budget_s

    def _emit(msg: str):
        if on_progress:
            try: on_progress(msg)
            except Exception: pass

    # Pull a real working sample from this language's canonical tests so the
    # prompt has ground-truth valid syntax to mimic.
    sample = _pick_working_sample(lang_dir, spec)

    _emit("Asking the model for a kata pack")
    prompt = _interp(_load_prompt("katas"), spec)
    if sample:
        prompt += (
            "\n\n## Verified working sample from this language\n\n"
            "This is a real program that compiles and runs in this language. "
            "Use it as ground truth for syntax and statement-terminator "
            "decisions. If your reference solution differs in punctuation or "
            "keyword spelling from this sample, you have a bug.\n\n"
            f"```\n{sample}\n```\n"
        )
    raw = client.call_json(prompt, KATA_PACK_SCHEMA, tag="katas")
    katas = raw.get("katas") or []
    _emit(f"Got {len(katas)} candidate katas, validating each")

    valid = []
    dropped = []
    for kata in katas:
        ok, reason = _self_validate(kata, lang_dir, spec)
        # Fix-up loop: ask the model to correct the reference until it
        # passes or attempts run out.
        attempts_used = 0
        while not ok and attempts_used < fix_attempts:
            if _time.monotonic() >= deadline:
                _emit(f"  skip  {kata.get('id', '?')}: time budget exhausted")
                break
            attempts_used += 1
            _emit(f"  fix   {kata.get('id', '?')} (attempt {attempts_used}): {reason[:80]}")
            new_ref = _try_fix_reference(kata, reason, spec, sample, client)
            if not new_ref:
                break
            kata["reference_solution"] = new_ref
            ok, reason = _self_validate(kata, lang_dir, spec)
        if ok:
            valid.append(kata)
            _emit(f"  ok    {kata.get('id', '?')}" +
                  (f" (after {attempts_used} fix)" if attempts_used else ""))
        else:
            dropped.append({"id": kata.get("id"), "reason": reason,
                            "fix_attempts": attempts_used})
            _emit(f"  drop  {kata.get('id', '?')}: {reason[:120]}")

    pack = {
        "lang": spec["lang_name"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "katas": valid,
        "dropped": dropped,
    }
    out_path = lang_dir / "katas.json"
    atomic_write_json(out_path, pack)
    if not valid:
        # All candidates failed; still save the pack (with empty katas + the
        # full drop list) so the GUI can render the diagnostic. The exception
        # carries `pack` so the API can return it as part of the error body.
        err = AllKatasDroppedError(
            f"All {len(katas)} candidate katas failed self-validation. "
            f"First drop: {dropped[0]['reason'] if dropped else 'unknown'}"
        )
        err.pack = pack
        raise err
    return pack


class AllKatasDroppedError(RuntimeError):
    """Raised when no kata survives self-validation. `.pack` carries the
    drop list so the GUI can render the diagnostic instead of nothing."""
    pack: dict | None = None


# ---------------------------------------------------------------------------
# Helpers: ground-truth sample + targeted fix-up retry
# ---------------------------------------------------------------------------

def _pick_working_sample(lang_dir: Path, spec: dict) -> Optional[str]:
    """Find a canonical test or example we know parses, to give the model
    a real working program to mimic."""
    ext = spec.get("file_extension", ".toy")
    # Prefer a small, focused test like loops or functions; fall back to anything.
    for name in ("functions", "loops", "variables", "conditionals", "hello_world",
                 "fibonacci", "fizzbuzz"):
        for sub in ("tests", "examples"):
            p = lang_dir / sub / f"{name}{ext}"
            if p.exists():
                src = p.read_text(encoding="utf-8")
                # Cap at ~40 lines to keep tokens reasonable.
                lines = src.splitlines()
                if len(lines) > 40:
                    src = "\n".join(lines[:40]) + "\n# ...\n"
                return src
    return None


_FIX_PROMPT = """\
The reference solution for this kata does not pass its own self-check
when run through the language's actual compiler.

## Kata
```json
{kata_json}
```

## Error from the compiler/runtime
```
{error}
```

## Verified working sample for reference (real code in this language)
```
{sample}
```

## Your job

Rewrite ONLY the `reference_solution` field so that, when run, it produces the
exact `expected` output for every test in the kata. Do not change `tests`,
`function_name`, `starter_code`, or any other field. Match the language's
syntax exactly: study the verified sample above for the punctuation and
keyword forms.

Return a JSON object with a single field `reference_solution` whose value is
the corrected code as a string.
"""

_FIX_SCHEMA = {
    "type": "object",
    "required": ["reference_solution"],
    "properties": {"reference_solution": {"type": "string"}},
    "additionalProperties": False,
}


def _try_fix_reference(kata: dict, error: str, spec: dict,
                       sample: Optional[str], client) -> Optional[str]:
    """Ask the model to rewrite ONLY the kata's reference_solution.
    Returns the new reference text, or None on failure."""
    try:
        prompt = _FIX_PROMPT.format(
            kata_json=json.dumps(kata, indent=2),
            error=error[:1500],
            sample=(sample or "(no sample available)")[:2500],
        )
        result = client.call_json(prompt, _FIX_SCHEMA,
                                  tag=f"kata-fix-{kata.get('id', 'unknown')}")
        new_ref = result.get("reference_solution") if isinstance(result, dict) else None
        return new_ref if isinstance(new_ref, str) and new_ref.strip() else None
    except Exception:
        return None


def _self_validate(kata: dict, lang_dir: Path, spec: dict) -> tuple[bool, str]:
    """Run the reference solution against each test. True if all pass."""
    try:
        ref = kata["reference_solution"]
        tests = kata["tests"]
    except KeyError as e:
        return False, f"missing field: {e}"
    if not tests:
        return False, "no tests"

    # Compile + run a single program with the reference + all `print(<call>)` lines.
    helpers = kata.get("helpers", "")
    program = _wrap_with_test_prints(ref, tests, spec, helpers=helpers)
    res = _compile_and_run(lang_dir, program, spec["file_extension"])
    if not res["ok"]:
        return False, f"reference failed to {res['stage']}: {res.get('stderr', '')[:200]}"

    actual_lines = res["stdout"].splitlines()
    if len(actual_lines) != len(tests):
        return False, (
            f"expected {len(tests)} output lines, got {len(actual_lines)}: "
            f"{actual_lines[:3]}..."
        )
    for i, (line, test) in enumerate(zip(actual_lines, tests)):
        if line.rstrip() != test["expected"].rstrip():
            return False, (
                f"test #{i} ({test['call']}): expected {test['expected']!r}, "
                f"got {line!r}"
            )
    return True, "ok"


_BATCH_SENTINEL = "==KATA_BOUNDARY_"


def _batch_validate(katas: list[dict], lang_dir: Path, spec: dict
                    ) -> Optional[list[tuple[dict, bool, str]]]:
    """Validate a whole pack in ONE compile+run.

    On Windows, each `_self_validate` call costs ~600ms (two Python
    subprocess starts: compile.py + .out.py). For a 12-kata pack that's
    ~7s sequential or ~2s parallel. Concatenating all references + all
    test-print lines into a single program brings it to ~300ms — the
    Python startup + Lark grammar load each happen once.

    Output is partitioned by sentinel lines ("==KATA_BOUNDARY_<i>==")
    so we can attribute each test line to its kata.

    Returns:
      - list of (kata, ok, reason) on a CLEAN run (every kata's tests
        produced their expected outputs).
      - None if any kata's tests don't match — caller should fall back
        to per-kata validation to identify which references are broken.
        We bail out wholesale because one bad reference can poison every
        kata's output ordering downstream.
    """
    if not katas:
        return []
    syntax = (spec.get("options") or {}).get("syntax")
    is_lisp = syntax == "s_expression"
    terminator = ";" if spec.get("statement_terminator") == ";" else ""

    def _emit_print(expr_str: str) -> str:
        """Emit a single `print(expr)` line in the target's syntax. For
        s_expression we use prefix form `(print expr)`; expr is assumed
        already in target syntax."""
        if is_lisp:
            # Calls in already-target form start with `(`. Calls in c_like
            # form (older curated packs) we wrap as best-effort prefix.
            if expr_str.startswith("("):
                return f"(print {expr_str})"
            return f'(print "{expr_str}")'   # treat as a literal label
        return f"print({expr_str}){terminator}"

    parts: list[str] = []
    for i, kata in enumerate(katas):
        helpers = kata.get("helpers", "")
        if helpers and helpers.strip():
            parts.append(helpers.rstrip())
        parts.append(kata.get("reference_solution", "").rstrip())
        # Sentinel print: `print("__BATCH__0==")` in c-style; `(print "__BATCH__0==")` in lisp.
        parts.append(_emit_print(f'"{_BATCH_SENTINEL}{i}=="'))
        for t in kata.get("tests", []):
            call = t["call"].strip().rstrip(";").rstrip()
            parts.append(_emit_print(call))
    program = "\n".join(parts) + "\n"

    res = _compile_and_run(lang_dir, program, spec["file_extension"])
    if not res["ok"]:
        return None  # batch couldn't even run — fall back to per-kata

    # Partition stdout by sentinels.
    sections: dict[int, list[str]] = {}
    current: int | None = None
    for line in res["stdout"].splitlines():
        m_start = line.find(_BATCH_SENTINEL)
        if m_start != -1:
            tail = line[m_start + len(_BATCH_SENTINEL):]
            try:
                idx_str = tail.split("==", 1)[0]
                current = int(idx_str)
                sections[current] = []
                continue
            except ValueError:
                pass
        if current is not None:
            sections[current].append(line)

    # Compare each kata's section to its expected outputs. ANY mismatch
    # triggers fallback so we can pinpoint which kata to drop.
    for i, kata in enumerate(katas):
        section = sections.get(i, [])
        expected = [t["expected"] for t in kata.get("tests", [])]
        if len(section) != len(expected):
            return None
        for actual, exp in zip(section, expected):
            if actual.rstrip() != exp.rstrip():
                return None

    return [(k, True, "ok") for k in katas]


def preflight_check(user_code: str, spec: dict) -> Optional[dict]:
    """Cheap syntax sanity check that catches the common copy/paste corruption
    cases BEFORE we wrap with helpers and compile. When detected, returns a
    helpful error dict the caller can surface verbatim. Returns None if the
    code looks plausible.

    Catches:
      - Empty / whitespace-only submissions.
      - s_expression code that doesn't start with `(` (e.g. user pasted
        `efn max_depth ...` instead of `(defn max_depth ...`).
      - Unbalanced parens (counted with respect to string literals + line
        comments). Most browser copy/paste corruption shows up here.

    The point: produce a HUMAN error message instead of dumping a Lark
    UnexpectedCharacters traceback that scrolls off the screen.
    """
    syntax = (spec.get("options") or {}).get("syntax")
    code = (user_code or "").strip()
    if not code:
        return {"passed": False, "stage": "preflight",
                "stderr": "Your code is empty. Type a solution before submitting."}

    if syntax != "s_expression":
        return None  # only s-expression has the cheap balance check today

    # Strip line comments + string literals before counting parens, so
    # the count reflects actual code structure.
    cleaned_lines = []
    for line in code.splitlines():
        # Strip ; line comments (but not inside strings)
        out = []
        in_string = False
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == '"' and (i == 0 or line[i-1] != '\\'):
                in_string = not in_string
                out.append(ch)
            elif ch == ';' and not in_string:
                break  # rest of line is a comment
            else:
                out.append(ch)
            i += 1
        cleaned_lines.append("".join(out))
    cleaned = "\n".join(cleaned_lines)

    # Count parens, ignoring those inside string literals.
    opens = 0
    closes = 0
    in_string = False
    for i, ch in enumerate(cleaned):
        if ch == '"' and (i == 0 or cleaned[i-1] != '\\'):
            in_string = not in_string
        elif not in_string:
            if ch == '(':
                opens += 1
            elif ch == ')':
                closes += 1

    # Doesn't start with `(`? Almost certainly a copy/paste error where
    # the leading paren got dropped (the most common real-world failure
    # mode for "I pasted the solution and got a compile error").
    first_nonws = code.lstrip()
    if not first_nonws.startswith("("):
        # Look at what the first 30 chars of the user's code look like
        # so the error message can quote it back to them.
        preview = first_nonws[:40].splitlines()[0]
        return {
            "passed": False,
            "stage": "preflight",
            "stderr": (
                "Your code doesn't start with `(`. Every s_expression form is "
                "a parenthesized list `(operator operand ...)`, so a valid "
                "function definition begins with `(defn ...` or `(def ...`.\n\n"
                f"What you submitted starts with: `{preview}`\n\n"
                "If you copy-pasted from the Solution tab and the leading `(` "
                "didn't make it across (a common browser quirk), use the "
                "**↓ Load into editor** button on the Solution tab instead. "
                "It writes the literal reference text directly into the editor "
                "byte-for-byte."
            ),
        }

    # Unbalanced parens? Diagnose by which side has more.
    if opens != closes:
        diff = opens - closes
        if diff > 0:
            msg = (
                f"You have {opens} `(` but only {closes} `)`. "
                f"Missing {diff} closing paren{'s' if diff > 1 else ''}."
            )
        else:
            extra = -diff
            msg = (
                f"You have {opens} `(` but {closes} `)`. "
                f"There are {extra} extra closing paren{'s' if extra > 1 else ''}."
            )
        return {
            "passed": False,
            "stage": "preflight",
            "stderr": (
                f"Parens are unbalanced. {msg}\n\n"
                "Tip: every `(` needs a matching `)`. If you copy-pasted from "
                "the Solution tab, double-check the start AND end of your code "
                "didn't get truncated. The **↓ Load into editor** button on "
                "the Solution tab avoids this entirely."
            ),
        }

    return None


def check_solution(spec: dict, lang_dir: Path, kata: dict, user_code: str) -> dict:
    """Run user_code against each kata test. Returns first-failure-only per the
    doc's "Don't reveal all hidden tests at once" guidance."""
    # Cheap pre-flight: catch common copy/paste corruption before wrapping
    # + compiling. If the code is malformed in an obvious way, return a
    # helpful error instead of a Lark traceback.
    pre = preflight_check(user_code, spec)
    if pre is not None:
        return pre
    tests = kata["tests"]
    # Stub-rescued katas have no tests because the reference couldn't be
    # translated. We still attempt to compile the user's submission so they
    # get syntax feedback; we just can't grade their output against hidden
    # tests. Return a "compiled, no autograder" result.
    helpers = kata.get("helpers", "")
    if not tests or kata.get("stub_rescued"):
        program = _wrap_with_test_prints(user_code, [], spec, helpers=helpers)
        res = _compile_and_run(lang_dir, program, spec["file_extension"])
        if not res["ok"]:
            return {
                "passed": False,
                "stage": res["stage"],
                "stderr": res.get("stderr", ""),
                "test_index": None,
            }
        return {
            "passed": False,
            "stage": "no_tests",
            "stderr": ("Auto-check is unavailable for this kata in this "
                       "language. Your code compiled and ran without error, "
                       "but we don't have hidden tests to grade against."),
            "test_index": None,
            "passing_count": 0,
            "total": 0,
        }
    program = _wrap_with_test_prints(user_code, tests, spec, helpers=helpers)
    res = _compile_and_run(lang_dir, program, spec["file_extension"])
    if not res["ok"]:
        # Include a program excerpt so users can see what was actually
        # compiled (helpers + their code + test prints). Many "compile
        # error" reports turn out to be helpers introducing a conflict
        # or the test prints exposing an arity bug.
        program_lines = program.splitlines()
        excerpt = "\n".join(program_lines[:80])
        if len(program_lines) > 80:
            excerpt += f"\n... ({len(program_lines) - 80} more lines)"
        return {
            "passed": False,
            "stage": res["stage"],
            "stderr": res.get("stderr", ""),
            "test_index": None,
            "program_excerpt": excerpt,
        }

    actual_lines = res["stdout"].splitlines()
    for i, test in enumerate(tests):
        actual = actual_lines[i].rstrip() if i < len(actual_lines) else ""
        if actual != test["expected"].rstrip():
            return {
                "passed": False,
                "stage": "compare",
                "test_index": i,
                "call": test["call"],
                "expected": test["expected"],
                "actual": actual,
                "passing_count": i,
                "total": len(tests),
            }
    return {"passed": True, "test_index": None, "passing_count": len(tests),
            "total": len(tests)}


def load_pack(lang_dir: Path) -> Optional[dict]:
    p = lang_dir / "katas.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap_with_test_prints(user_code: str, tests: list[dict], spec: dict,
                           helpers: str = "") -> str:
    """Build a single program: helpers (if any), user code, then a print
    line per test.

    The `helpers` block (e.g. linked-list / tree node constructors) is
    always prepended so test calls like `ll_to_list(reverse_ll(to_ll(...)))`
    work even when the user only wrote `reverse_ll`. Without this, every
    LL/tree kata used to crash with "name 'll_to_list' is not defined" on
    user submissions.

    Honors statement_terminator (`;` for c_like, newline for python_like,
    `)` for s_expression - the closing paren on the test-call form).

    Test calls may already be in the target language's syntax (e.g. after
    transpile_kata) or in c_like (when called directly from a curated pack
    against a c_like target). For s_expression we detect both shapes:
      - already-translated: `(reverse (list 1 2 3))` -> `(print (reverse (list 1 2 3)))`
      - c_like form:        `reverse(list(1, 2, 3))` -> transpile, then wrap
    """
    syntax = (spec.get("options") or {}).get("syntax")
    lines = []
    if helpers and helpers.strip():
        lines.append(helpers.rstrip())
        lines.append("")
    lines.append(user_code.rstrip())
    lines.append("")

    if syntax == "s_expression":
        from .mechanical_translator import transpile
        for test in tests:
            call = test["call"].strip().rstrip(";").rstrip()
            # If the call is already in s-expression form (parenthesized
            # prefix call), wrap it directly. Otherwise translate from c_like.
            if call.startswith("("):
                lines.append(f"(print {call})")
            else:
                translated = transpile(f"print({call});\n", spec)
                if translated:
                    lines.append(translated.rstrip())
                else:
                    # Defensive fallback: try to coerce `name(a, b)` into
                    # `(name a b)` lexically. Doesn't handle nested calls.
                    lines.append(f"(print ({call.replace(',', ' ').replace('(', ' ').replace(')', '')}))")
        return "\n".join(lines) + "\n"

    if syntax == "ml_like":
        # mllang: function calls are juxtaposition (`f x y`), and the
        # generic `print_any` runtime helper prints any value + newline
        # (mirrors c_like's `print(...)` semantics). Kata `call` strings
        # in CLASSICS_ML_LIKE are already in mllang syntax (e.g.
        # `fib 10`, not `fib(10)`); we wrap each with `print_any (...) ;;`.
        for test in tests:
            call = test["call"].strip().rstrip(";").rstrip()
            # Strip trailing `;;` if the kata author included it.
            if call.endswith(";;"):
                call = call[:-2].rstrip()
            lines.append(f"print_any ({call}) ;;")
        return "\n".join(lines) + "\n"

    if syntax == "stack_based":
        # Forth: push args, call the word, then `.` to print the result.
        # Test calls may already be in postfix form (`5 factorial`) or
        # in c_like form (`factorial(5)`); detect the latter and translate.
        from .mechanical_translator import transpile
        for test in tests:
            call = test["call"].strip().rstrip(";").rstrip()
            if "(" in call and ")" in call:
                # c_like form: translate to postfix.
                translated = transpile(f"{call};\n", spec)
                if translated:
                    # Strip the trailing ` drop` that emit_expr_stmt adds
                    # (we want to PRINT the value, not drop it).
                    expr = translated.rstrip()
                    if expr.endswith(" drop"):
                        expr = expr[:-len(" drop")]
                    lines.append(f"{expr} .")
                else:
                    lines.append(f"\\ couldn't translate test call: {call}")
            else:
                # Already postfix; just print after.
                lines.append(f"{call} .")
        return "\n".join(lines) + "\n"

    terminator = ";" if spec.get("statement_terminator") == ";" else ""
    for test in tests:
        call = test["call"].strip().rstrip(";").rstrip()
        lines.append(f"print({call}){terminator}")
    return "\n".join(lines) + "\n"


def _compile_and_run(lang_dir: Path, source: str, ext: str, timeout: float = 12.0) -> dict:
    """Compile + run a source string through the language's pipeline.
    Returns {ok, stage, stdout, stderr}.

    Tempfile cleanup is best-effort but ATOMIC across all error paths
    (timeout, KeyboardInterrupt, generic exception). On Windows the
    `.out.py` may be briefly locked by the just-exited Python; we retry
    the unlink up to 3 times with a small backoff to absorb that.
    """
    lang_dir = lang_dir.resolve()
    compile_py = lang_dir / "compile.py"
    if not compile_py.exists():
        return {"ok": False, "stage": "no_compile_py", "stdout": "", "stderr": "compile.py missing"}

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=ext + ".__kata__", delete=False, encoding="utf-8") as f:
        f.write(source)
        src_path = Path(f.name)
    out_py = src_path.with_suffix(src_path.suffix + ".out.py")
    try:
        env = {**os.environ, "PYTHONPATH": str(lang_dir.parent)}
        cp = subprocess.run(
            [sys.executable, str(compile_py), str(src_path)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(lang_dir), env=env,
        )
        if cp.returncode != 0:
            return {"ok": False, "stage": "compile",
                    "stdout": cp.stdout, "stderr": cp.stderr}
        rp = subprocess.run(
            [sys.executable, str(out_py)],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(lang_dir), env=env,
        )
        return {
            "ok": rp.returncode == 0,
            "stage": "run" if rp.returncode != 0 else "ok",
            "stdout": rp.stdout, "stderr": rp.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stage": "timeout", "stdout": "", "stderr": "timed out"}
    finally:
        # Robust cleanup: catch OSError (Windows file locks), retry
        # briefly, then give up rather than leaking on the failure path.
        # Catch ALL exceptions including KeyboardInterrupt during cleanup.
        for path in (src_path, out_py):
            for attempt in range(3):
                try:
                    path.unlink(missing_ok=True)
                    break
                except OSError:
                    import time as _t
                    _t.sleep(0.05 * (attempt + 1))
                except Exception:
                    break
