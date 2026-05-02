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
                   on_progress=None, *, fix_attempts: int = 2) -> dict:
    """Generate, validate, and persist a kata pack for the language.

    For any kata whose reference fails self-validation, we re-ask the
    model with the actual parser/runtime error as feedback. Up to
    `fix_attempts` retries per kata. Surviving katas get persisted;
    drops are recorded with their final error.
    """
    from .generator import _load_prompt, _interp

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
    out_path.write_text(json.dumps(pack, indent=2), encoding="utf-8")
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
    terminator = ";" if spec.get("statement_terminator") == ";" else ""

    parts: list[str] = []
    for i, kata in enumerate(katas):
        helpers = kata.get("helpers", "")
        if helpers and helpers.strip():
            parts.append(helpers.rstrip())
        parts.append(kata.get("reference_solution", "").rstrip())
        parts.append(f'print("{_BATCH_SENTINEL}{i}=="){terminator}')
        for t in kata.get("tests", []):
            call = t["call"].strip().rstrip(";").rstrip()
            parts.append(f"print({call}){terminator}")
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


def check_solution(spec: dict, lang_dir: Path, kata: dict, user_code: str) -> dict:
    """Run user_code against each kata test. Returns first-failure-only per the
    doc's "Don't reveal all hidden tests at once" guidance."""
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
        return {
            "passed": False,
            "stage": res["stage"],
            "stderr": res.get("stderr", ""),
            "test_index": None,
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

    Honors statement_terminator (`;` for c_like, newline for python_like).
    """
    terminator = ";" if spec.get("statement_terminator") == ";" else ""
    lines = []
    if helpers and helpers.strip():
        lines.append(helpers.rstrip())
        lines.append("")
    lines.append(user_code.rstrip())
    lines.append("")
    for test in tests:
        call = test["call"].strip().rstrip(";").rstrip()
        lines.append(f"print({call}){terminator}")
    return "\n".join(lines) + "\n"


def _compile_and_run(lang_dir: Path, source: str, ext: str, timeout: float = 12.0) -> dict:
    """Compile + run a source string through the language's pipeline.
    Returns {ok, stage, stdout, stderr}."""
    lang_dir = lang_dir.resolve()
    compile_py = lang_dir / "compile.py"
    if not compile_py.exists():
        return {"ok": False, "stage": "no_compile_py", "stdout": "", "stderr": "compile.py missing"}

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=ext + ".__kata__", delete=False, encoding="utf-8") as f:
        f.write(source)
        src_path = Path(f.name)
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
        out_py = src_path.with_suffix(src_path.suffix + ".out.py")
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
        try: src_path.unlink()
        except OSError: pass
        out_py = src_path.with_suffix(src_path.suffix + ".out.py")
        try: out_py.unlink()
        except OSError: pass
