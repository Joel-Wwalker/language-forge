"""Smoke test: a minimal "did this generation produce a runnable
language?" check. Phase 1.3 (production roadmap v2).

This is NOT the Phase 2 quality filter. It's the cheap, fast check
the batch runner calls on every successful slot to flag obvious
duds before the curator sees them. Three checks:

  1. Canonical tests pass. Read from `generation_summary.json` if
     present (already populated by `generate_all` when
     verify_after_generation=True), otherwise re-run `verify()`.
  2. Kata pack `_batch_validate` runs cleanly. Skipped for
     syntax families with no curated pack (python_like,
     s_expression). Skipping is not a failure — it's a known
     pipeline limitation.
  3. REPL deliverables present + executable. `repl.html` exists,
     contains the Pyodide marker. `compile.py` runs against the
     hello_world canonical test without crashing.

Public API:
    SmokeResult                              -- dataclass
    smoke_test(language_dir, *, force_reverify=False) -> SmokeResult

Design choice: smoke_test is pure observation. It doesn't modify
state.json; the caller (runner) does. This keeps the function
unit-testable in isolation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Optional


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


# Map syntax_family -> curated pack key. Families not in this map
# don't get a kata smoke check (they need LLM translation, which is
# too expensive for the smoke path). Phase 4 may add native packs
# for python_like / s_expression.
_PACK_FOR_SYNTAX: dict[str, str] = {
    "c_like":      "classics",
    "stack_based": "stack_classics",
}

# The canonical "hello_world" test is what we run for the REPL-launch
# check. Every generated language ships this test.
_CANONICAL_HELLO = "hello_world"


@dataclass
class SmokeResult:
    """Outcome of one smoke run.

    `passed` is True iff every check that COULD run did and succeeded.
    Skipped checks (e.g. kata when no pack exists for the syntax
    family) don't count against pass."""
    passed: bool
    canonical: dict          # {passed, total, pass_rate, source}
    kata: Optional[dict]     # {passed, total, pass_rate, pack_key} or None
    repl: dict               # {launches, repl_html_ok, compile_exit_code}
    failures: list[str] = field(default_factory=list)
    skips: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


# ---------------------------------------------------------------------------
# Check 1: canonical tests
# ---------------------------------------------------------------------------

def _check_canonical(lang_dir: Path, *, force_reverify: bool) -> tuple[dict, list[str]]:
    """Returns ({passed, total, pass_rate, source}, [failure messages]).

    Reads from generation_summary.json by default; re-runs `verify()`
    if force_reverify or summary missing. Failure messages are added
    when the canonical pass rate is below 1.0."""
    summary_path = lang_dir / "generation_summary.json"
    failures: list[str] = []

    if not force_reverify and summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            ct = summary.get("canonical_tests")
            if ct and isinstance(ct, dict) and "total" in ct:
                source = "summary"
                # Trust the summary if the run actually verified.
                if ct.get("total", 0) > 0:
                    if ct["passed"] != ct["total"]:
                        failures.append(
                            f"canonical: {ct['passed']}/{ct['total']} passed"
                        )
                    return {
                        "passed": int(ct["passed"]),
                        "total": int(ct["total"]),
                        "pass_rate": float(ct.get("pass_rate", 0.0)),
                        "source": source,
                    }, failures
        except Exception:
            # Corrupt summary — re-verify.
            pass

    # Fallback: run verify() ourselves. This adds ~600ms per c_like
    # language but is the source of truth.
    try:
        from forge.orchestrator.verifier import verify
        report = verify(lang_dir)
        passed = sum(1 for t in report.tests if t.status == "pass")
        total = len(report.tests)
        if total == 0:
            failures.append("canonical: no tests found")
        elif passed != total:
            failed_names = [t.name for t in report.tests if t.status != "pass"]
            failures.append(
                f"canonical: {passed}/{total} (failed: {', '.join(failed_names[:3])})"
            )
        return {
            "passed": passed, "total": total,
            "pass_rate": (passed / total) if total else 0.0,
            "source": "verify",
        }, failures
    except Exception as e:
        failures.append(f"canonical: verifier crashed: {type(e).__name__}: {e}")
        return {"passed": 0, "total": 0, "pass_rate": 0.0,
                "source": f"error:{type(e).__name__}"}, failures


# ---------------------------------------------------------------------------
# Check 2: kata pack
# ---------------------------------------------------------------------------

def _check_kata_pack(lang_dir: Path, spec: dict
                     ) -> tuple[Optional[dict], list[str], list[str]]:
    """Returns ({passed, total, pass_rate, pack_key}, [failures], [skips]).

    First entry is None if the syntax family has no curated pack
    available for direct validation. That counts as a SKIP (recorded
    in the skips list), not a failure.
    """
    syntax = (spec.get("options") or {}).get("syntax")
    pack_key = _PACK_FOR_SYNTAX.get(syntax)
    if pack_key is None:
        return None, [], [
            f"kata: no curated pack for syntax_family={syntax!r} (Phase 1 "
            f"limitation; needs LLM translation which smoke skips)"
        ]

    try:
        from forge.orchestrator.kata_packs import get_pack
        from forge.orchestrator.katas import (
            _batch_validate, _self_validate, substitute_kata_for_target,
        )
    except Exception as e:
        return None, [f"kata: import failed: {type(e).__name__}: {e}"], []

    pack = get_pack(pack_key)
    if pack is None:
        return None, [f"kata: pack {pack_key!r} not registered"], []

    katas = pack.get("katas") or []
    if not katas:
        return {"passed": 0, "total": 0, "pass_rate": 0.0,
                "pack_key": pack_key}, ["kata: pack is empty"], []

    # Phase 1.5 bugfix Fix 2 — Bug 3 root cause: a curated pack is in
    # canonical c_like (`func`, `if`, `return`, `true`/`false`/`null`).
    # A themed c_like target (pirate phrasebook with `func → yarrn` etc.)
    # can't parse this — its grammar expects the themed spellings. We
    # apply the spec's substitutions at this entry boundary so every
    # kata's source matches the target's actual dialect by the time it
    # reaches `_batch_validate` / `_self_validate`.
    katas = [substitute_kata_for_target(k, spec) for k in katas]

    # Try the fast batched path first.
    try:
        results = _batch_validate(katas, lang_dir, spec)
    except Exception as e:
        return None, [
            f"kata: _batch_validate crashed: {type(e).__name__}: {e}"
        ], []

    if results is None:
        # `_batch_validate` returns None when the batched output
        # ordering got poisoned by some kata's stdout. Per the
        # function's docstring, the right move is per-kata fallback —
        # NOT to declare the pack broken. The load-pack endpoint
        # follows the same fallback, so smoke matches its behavior.
        try:
            results = [(k, *_self_validate(k, lang_dir, spec)) for k in katas]
        except Exception as e:
            return None, [
                f"kata: per-kata fallback crashed: {type(e).__name__}: {e}"
            ], []

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    failures: list[str] = []
    if total > 0 and passed != total:
        failed_ids = [k.get("id", "?") for k, ok, _ in results if not ok][:3]
        failures.append(
            f"kata: {passed}/{total} passed in pack {pack_key!r} "
            f"(failed: {', '.join(failed_ids)})"
        )
    return ({"passed": passed, "total": total,
             "pass_rate": (passed / total) if total else 0.0,
             "pack_key": pack_key}, failures, [])


# ---------------------------------------------------------------------------
# Check 3: REPL deliverables + compile.py launches
# ---------------------------------------------------------------------------

def _check_repl(lang_dir: Path, spec: dict) -> tuple[dict, list[str]]:
    """Returns ({repl_html_ok, compile_exit_code, launches}, [failures]).

    Two sub-checks:
      (a) repl.html exists, is non-empty, and contains the Pyodide
          loader URL. The browser REPL is a key deliverable; if it's
          missing or stub, the language ships broken even if the
          tests pass.
      (b) `python compile.py <hello_world test>` exits 0 inside a
          short timeout. Confirms compile.py is wired up correctly.
          We use the canonical hello_world fixture because every
          generated language ships it.
    """
    failures: list[str] = []
    result = {
        "repl_html_ok": False,
        "compile_exit_code": None,
        "launches": False,
    }

    # (a) repl.html
    repl_path = lang_dir / "repl.html"
    if not repl_path.exists():
        failures.append("repl: repl.html missing")
    else:
        text = repl_path.read_text(encoding="utf-8", errors="replace")
        if len(text) < 1000:
            failures.append(f"repl: repl.html too small ({len(text)} bytes)")
        elif "pyodide" not in text.lower():
            failures.append("repl: repl.html missing Pyodide marker")
        else:
            result["repl_html_ok"] = True

    # (b) compile.py against hello_world
    compile_py = lang_dir / "compile.py"
    if not compile_py.exists():
        failures.append("repl: compile.py missing")
        return result, failures

    ext = spec.get("file_extension") or ""
    if not ext:
        failures.append("repl: spec missing file_extension")
        return result, failures
    hello = lang_dir / "tests" / f"{_CANONICAL_HELLO}{ext}"
    if not hello.exists():
        # Fallback: glob for any *.<ext> file under tests/.
        candidates = list((lang_dir / "tests").glob(f"*{ext}"))
        if not candidates:
            failures.append(
                f"repl: no test file matching *{ext} for compile-launch check"
            )
            return result, failures
        hello = candidates[0]

    env = dict(os.environ)
    env["PYTHONPATH"] = (
        str(WORKSPACE_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    )
    try:
        cp = subprocess.run(
            [sys.executable, str(compile_py), str(hello)],
            capture_output=True, text=True, timeout=15,
            cwd=str(lang_dir), env=env, encoding="utf-8", errors="replace",
        )
        result["compile_exit_code"] = cp.returncode
        if cp.returncode != 0:
            stderr_tail = (cp.stderr or "").strip().splitlines()[-3:]
            failures.append(
                f"repl: compile.py exit {cp.returncode} on {hello.name}: "
                + " | ".join(stderr_tail)[:200]
            )
        else:
            result["launches"] = True
    except subprocess.TimeoutExpired:
        failures.append("repl: compile.py timed out (>15s) on hello_world")
    except Exception as e:
        failures.append(
            f"repl: compile.py invocation crashed: {type(e).__name__}: {e}"
        )

    return result, failures


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def smoke_test(language_dir: str | os.PathLike, *,
               force_reverify: bool = False) -> SmokeResult:
    """Run the three smoke checks. Returns a `SmokeResult`.

    `passed` is True iff:
      - canonical tests pass (or, if no tests, that's a fail);
      - kata pack passes OR was skipped because no pack exists for
        the syntax family;
      - REPL deliverables present + compile.py launches successfully.

    A skipped kata check does NOT fail smoke — it just shows up in
    `result.skips`. Phase 2's quality filter will decide what to do
    with skip-reason failures.
    """
    t0 = time.monotonic()
    lang_dir = Path(language_dir)
    failures: list[str] = []
    skips: list[str] = []

    # Read spec once; every check needs it.
    spec_path = lang_dir / "resolved_spec.json"
    if not spec_path.exists():
        # Hard failure: a generation that didn't produce a spec is
        # not a real language. We can't even pick the right pack.
        return SmokeResult(
            passed=False,
            canonical={"passed": 0, "total": 0, "pass_rate": 0.0,
                       "source": "missing_spec"},
            kata=None,
            repl={"repl_html_ok": False, "compile_exit_code": None,
                  "launches": False},
            failures=[f"smoke: resolved_spec.json missing in {lang_dir}"],
            skips=[],
            duration_seconds=round(time.monotonic() - t0, 3),
        )
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception as e:
        return SmokeResult(
            passed=False,
            canonical={"passed": 0, "total": 0, "pass_rate": 0.0,
                       "source": "bad_spec"},
            kata=None,
            repl={"repl_html_ok": False, "compile_exit_code": None,
                  "launches": False},
            failures=[f"smoke: resolved_spec.json malformed: "
                     f"{type(e).__name__}: {e}"],
            skips=[],
            duration_seconds=round(time.monotonic() - t0, 3),
        )

    # Run the three checks. Each returns (result_dict_or_None, failures, [skips]).
    canonical, canon_fails = _check_canonical(lang_dir, force_reverify=force_reverify)
    failures.extend(canon_fails)

    kata, kata_fails, kata_skips = _check_kata_pack(lang_dir, spec)
    failures.extend(kata_fails)
    skips.extend(kata_skips)

    repl, repl_fails = _check_repl(lang_dir, spec)
    failures.extend(repl_fails)

    return SmokeResult(
        passed=not failures,
        canonical=canonical,
        kata=kata,
        repl=repl,
        failures=failures,
        skips=skips,
        duration_seconds=round(time.monotonic() - t0, 3),
    )
