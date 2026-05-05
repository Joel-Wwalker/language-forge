"""Auto-check pipeline for kata packs.

Runs every reference solution in a curated kata pack against the target
language's actual compiler + runtime. For each test in each kata,
compares actual stdout against expected. Reports per-kata pass/fail
with line-level detail.

Use cases:
  1. **CI gate**: pytest imports `validate_pack()` and fails if any
     reference regresses.
  2. **Ad-hoc verification**: run as a CLI on a freshly-edited pack.
  3. **New-language smoke test**: when adding a new stack_based dialect,
     run the pack against it to find which references need adapting.

Usage:
    python -m forge.orchestrator.validate_kata_pack stack_classics
    python -m forge.orchestrator.validate_kata_pack stack_classics --on forthlang
    python -m forge.orchestrator.validate_kata_pack classics --on toylang -v

Exit code: 0 if all references pass, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class TestResult:
    test_index: int
    call: str
    expected: str
    actual: str
    passed: bool
    elapsed_ms: float


@dataclass
class KataResult:
    kata_id: str
    title: str
    test_results: list[TestResult] = field(default_factory=list)
    compile_error: Optional[str] = None
    elapsed_ms: float = 0.0

    @property
    def passed(self) -> bool:
        if self.compile_error:
            return False
        return all(t.passed for t in self.test_results)

    @property
    def passing_count(self) -> int:
        return sum(1 for t in self.test_results if t.passed)


@dataclass
class PackResult:
    pack_key: str
    lang: str
    katas: list[KataResult] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def all_passed(self) -> bool:
        return all(k.passed for k in self.katas)

    @property
    def passing_kata_count(self) -> int:
        return sum(1 for k in self.katas if k.passed)

    @property
    def total_test_count(self) -> int:
        return sum(len(k.test_results) for k in self.katas)

    @property
    def passing_test_count(self) -> int:
        return sum(k.passing_count for k in self.katas)


# ---------------------------------------------------------------------------
# Default-language picker: which reference compiler does this pack target?
# ---------------------------------------------------------------------------

_DEFAULT_LANG_BY_FAMILY = {
    "c_like":       "toylang",
    "s_expression": "lisplang",
    "stack_based":  "forthlang",
    "python_like":  None,    # no hand-written reference for python_like yet
}


def _default_lang_for_pack(pack: dict) -> Optional[str]:
    return _DEFAULT_LANG_BY_FAMILY.get(pack.get("syntax_family"))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_pack(pack_key: str, lang: Optional[str] = None,
                  *, verbose: bool = False) -> PackResult:
    """Run every reference solution in `pack_key` against `lang`'s compiler.

    If `lang` is None, picks the reference compiler matching the pack's
    `syntax_family` (e.g. forthlang for stack_based). Returns a
    structured PackResult; the caller decides what to do with it.
    """
    from .kata_packs import get_pack
    from .katas import _wrap_with_test_prints, _compile_and_run

    pack = get_pack(pack_key)
    if pack is None:
        raise ValueError(f"no such pack: {pack_key}")

    if lang is None:
        lang = _default_lang_for_pack(pack)
        if lang is None:
            raise ValueError(
                f"pack `{pack_key}` (syntax_family={pack.get('syntax_family')}) "
                f"has no default reference language; pass --on <lang>"
            )

    lang_dir = WORKSPACE_ROOT / "generated" / lang
    if not lang_dir.exists():
        raise FileNotFoundError(f"no such language: {lang_dir}")

    spec_path = lang_dir / "resolved_spec.json"
    if not spec_path.exists():
        raise FileNotFoundError(f"no resolved_spec.json under {lang_dir}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    result = PackResult(pack_key=pack_key, lang=lang)
    t0_pack = time.monotonic()
    _ok, _fail, _arrow = _safe_marks()

    for kata in pack["katas"]:
        kr = KataResult(kata_id=kata["id"], title=kata.get("title", kata["id"]))
        t0 = time.monotonic()
        helpers = kata.get("helpers", "")

        # Compile the reference once per test so each test's stdout is
        # isolated (forthlang has a global stack that accumulates state
        # otherwise; same for any stateful runtime).
        for i, test in enumerate(kata.get("tests", [])):
            t_test = time.monotonic()
            program = _wrap_with_test_prints(
                kata["reference_solution"], [test], spec, helpers=helpers
            )
            res = _compile_and_run(lang_dir, program, spec.get("file_extension", ""))
            elapsed = (time.monotonic() - t_test) * 1000
            if not res["ok"]:
                kr.test_results.append(TestResult(
                    test_index=i,
                    call=test["call"],
                    expected=test["expected"],
                    actual="",
                    passed=False,
                    elapsed_ms=elapsed,
                ))
                kr.compile_error = (
                    f"stage={res['stage']}: " + (res.get("stderr") or "").strip()
                )[:400]
                if verbose:
                    print(f"  {_fail} {kata['id']} test {i}: {res['stage']} - "
                          f"{(res.get('stderr') or '')[:100]}")
                continue
            actual = res["stdout"].rstrip("\n")
            expected = test["expected"].rstrip("\n")
            passed = actual == expected
            kr.test_results.append(TestResult(
                test_index=i,
                call=test["call"],
                expected=expected,
                actual=actual,
                passed=passed,
                elapsed_ms=elapsed,
            ))
            if verbose:
                mark = _ok if passed else _fail
                print(f"  {mark} {kata['id']} test {i}: {test['call']} {_arrow} "
                      f"expected {expected!r}, got {actual!r} ({elapsed:.0f}ms)")

        kr.elapsed_ms = (time.monotonic() - t0) * 1000
        result.katas.append(kr)

    result.elapsed_s = time.monotonic() - t0_pack
    return result


# ---------------------------------------------------------------------------
# Pretty-printers
# ---------------------------------------------------------------------------

def _safe_marks(stream=None) -> tuple[str, str, str]:
    """Pick checkmark / x / arrow characters that the output stream can
    actually encode. Windows `cp1252` consoles can't render ✓/✗/→ so
    we fall back to ASCII `[ok]`/`[X]`/`->`."""
    enc = getattr(stream or sys.stdout, "encoding", "utf-8") or "utf-8"
    try:
        "✓✗→".encode(enc)
        return "✓", "✗", "→"
    except (UnicodeEncodeError, LookupError):
        return "[ok]", "[X] ", "->"


def format_summary(result: PackResult, *, full: bool = False, stream=None) -> str:
    """One-line summary plus per-kata breakdown."""
    ok, fail, arrow = _safe_marks(stream)
    lines = []
    headline = (
        f"pack:{result.pack_key} lang:{result.lang}  "
        f"{result.passing_kata_count}/{len(result.katas)} katas pass  "
        f"{result.passing_test_count}/{result.total_test_count} tests pass  "
        f"({result.elapsed_s:.2f}s)"
    )
    lines.append(headline)
    lines.append("=" * len(headline))
    for kr in result.katas:
        mark = ok if kr.passed else fail
        line = f"  {mark} {kr.kata_id:<22} {kr.passing_count}/{len(kr.test_results)} tests  ({kr.elapsed_ms:.0f}ms)"
        lines.append(line)
        if not kr.passed:
            if kr.compile_error:
                lines.append(f"      compile/run error: {kr.compile_error}")
            for tr in kr.test_results:
                if not tr.passed and not kr.compile_error:
                    lines.append(
                        f"      test {tr.test_index}: {tr.call}\n"
                        f"        expected: {tr.expected!r}\n"
                        f"        actual:   {tr.actual!r}"
                    )
        elif full:
            for tr in kr.test_results:
                lines.append(f"      test {tr.test_index}: {tr.call}  {arrow}  {tr.actual!r}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="forge.orchestrator.validate_kata_pack",
        description="Auto-check every reference solution in a kata pack.",
    )
    parser.add_argument("pack_key", help="Pack to validate (e.g. classics, stack_classics)")
    parser.add_argument("--on", "--lang", dest="lang", default=None,
                        help="Run against this generated language (default: pack's reference)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print each test as it runs")
    parser.add_argument("--full", action="store_true",
                        help="Print all test results, including passing ones")
    parser.add_argument("--json", action="store_true",
                        help="Emit results as machine-readable JSON instead of text")
    args = parser.parse_args(argv)

    try:
        result = validate_pack(args.pack_key, args.lang, verbose=args.verbose)
    except (ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "pack": result.pack_key,
            "lang": result.lang,
            "all_passed": result.all_passed,
            "passing_katas": result.passing_kata_count,
            "total_katas": len(result.katas),
            "passing_tests": result.passing_test_count,
            "total_tests": result.total_test_count,
            "elapsed_s": round(result.elapsed_s, 3),
            "katas": [
                {
                    "id": k.kata_id,
                    "passed": k.passed,
                    "passing_count": k.passing_count,
                    "total": len(k.test_results),
                    "elapsed_ms": round(k.elapsed_ms, 1),
                    "compile_error": k.compile_error,
                    "tests": [
                        {"index": t.test_index, "call": t.call,
                         "expected": t.expected, "actual": t.actual,
                         "passed": t.passed}
                        for t in k.test_results
                    ],
                }
                for k in result.katas
            ],
        }, indent=2))
    else:
        print(format_summary(result, full=args.full))
    return 0 if result.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
