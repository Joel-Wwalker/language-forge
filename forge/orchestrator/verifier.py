"""Verification harness, the project's backbone.

Steps for each generated language directory:

  1. Load test pairs from `<lang_dir>/tests/`. Each test has:
        - `<name>.<ext>`                  (source in the new language)
        - `<name>.expected_output.txt`    (expected stdout)
  2. Confirm all canonical tests are present.
  3. For each test:
        a. `python <lang_dir>/compile.py <source>`        → produces .out.py
        b. `python <source>.out.py`                       → run, capture stdout
        c. compare stdout to expected (rstrip).
  4. Return a structured `VerificationReport`.

On failure, attribute the failing component (best-guess) so the repair loop
knows which file to ask the LLM to rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import os
import subprocess
import sys
from typing import Optional


CANONICAL_TESTS = [
    "hello_world",
    "arithmetic",
    "variables",
    "conditionals",
    "loops",
    "functions",
    "closures",
    "strings",
]


@dataclass
class TestResult:
    name: str
    status: str                          # "pass" | "fail" | "missing"
    failing_component: Optional[str] = None
    stage: Optional[str] = None          # "compile" | "run" | "compare"
    expected: Optional[str] = None
    actual: Optional[str] = None
    stderr: Optional[str] = None
    returncode: Optional[int] = None


@dataclass
class VerificationReport:
    lang_dir: str
    file_extension: str
    all_passed: bool
    tests: list[TestResult] = field(default_factory=list)
    missing_canonical: list[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "lang_dir": self.lang_dir,
            "file_extension": self.file_extension,
            "all_passed": self.all_passed,
            "missing_canonical": list(self.missing_canonical),
            "tests": [asdict(t) for t in self.tests],
        }

    def summary(self) -> str:
        lines = [f"Verification report for {self.lang_dir}:"]
        for t in self.tests:
            mark = {"pass": "OK", "fail": "FAIL", "missing": "MISS"}.get(t.status, "?")
            extra = ""
            if t.status == "fail":
                extra = f"  ({t.stage} -> {t.failing_component})"
            lines.append(f"  [{mark:4s}] {t.name}{extra}")
        if self.missing_canonical:
            lines.append(f"Missing canonical tests: {', '.join(self.missing_canonical)}")
        lines.append(f"Result: {'PASS' if self.all_passed else 'FAIL'}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Spec discovery
# ---------------------------------------------------------------------------

def _load_spec(lang_dir: Path) -> dict:
    """Load the resolved spec, falling back to the example spec for toylang."""
    candidates = [
        lang_dir / "resolved_spec.json",
        lang_dir / "language_spec.json",
    ]
    for c in candidates:
        if c.exists():
            return json.loads(c.read_text(encoding="utf-8"))
    # Toylang fallback: the hand-written reference compiler uses the example.
    fallback = Path(__file__).resolve().parents[2] / "schemas" / "example_toylang_spec.json"
    if lang_dir.name == "toylang" and fallback.exists():
        return json.loads(fallback.read_text(encoding="utf-8"))
    return {"file_extension": ".toy"}  # last-ditch default


# ---------------------------------------------------------------------------
# Per-test execution
# ---------------------------------------------------------------------------

def _attribute_failure(stderr: str, stage: str) -> str:
    """Best-effort attribution of a failure to a component.

    The most reliable signal is which generated file appears in the
    Python traceback. We check those FIRST. Falling back to error-name
    keywords catches cases where the trace is truncated.
    """
    s = (stderr or "").lower()
    if stage == "compile":
        # Look at the traceback's File: paths first. The component that
        # actually raised is the one to repair.
        if "typechecker.py" in s:
            return "typechecker"
        if "lexer.py" in s and ("unexpected" in s or "tokeniz" in s):
            return "lexer"
        if "parser.py" in s and ("lark" in s or "unexpected" in s):
            return "parser"
        if "codegen.py" in s:
            return "codegen"
        # Keyword fallbacks for tracebacks that don't point at our files.
        if "unexpected" in s or "lark" in s or "parse" in s:
            return "parser"
        if "tokeniz" in s:
            return "lexer"
        if "typecheckerror" in s or "type check" in s or "type error" in s:
            return "typechecker"
        return "codegen"
    if stage == "run":
        if "typeerror" in s and "unsupported" in s:
            return "codegen"
        if "nameerror" in s or "unboundlocal" in s:
            return "codegen"
        if "syntaxerror" in s:
            return "codegen"
        return "runtime"
    if stage == "compare":
        return "codegen"
    return "unknown"


def _run_one_test(lang_dir: Path, name: str, ext: str) -> TestResult:
    tests_dir = lang_dir / "tests"
    src = tests_dir / f"{name}{ext}"
    expected_path = tests_dir / f"{name}.expected_output.txt"

    if not src.exists() or not expected_path.exists():
        return TestResult(name=name, status="missing")

    expected = expected_path.read_text(encoding="utf-8").rstrip()

    # Step 1: transpile
    compile_py = lang_dir / "compile.py"
    out_py = src.with_suffix(src.suffix + ".out.py")
    # Clean stale output
    if out_py.exists():
        try:
            out_py.unlink()
        except OSError:
            pass

    env = os.environ.copy()
    # Ensure the parent of the language package is importable.
    parent_of_pkg = str(lang_dir.parent)
    env["PYTHONPATH"] = parent_of_pkg + os.pathsep + env.get("PYTHONPATH", "")

    try:
        compile_proc = subprocess.run(
            [sys.executable, str(compile_py), str(src)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(lang_dir),
        )
    except subprocess.TimeoutExpired as e:
        return TestResult(name=name, status="fail", stage="compile",
                          failing_component="parser",
                          stderr=f"compile timed out: {e}")

    if compile_proc.returncode != 0:
        return TestResult(
            name=name, status="fail", stage="compile",
            failing_component=_attribute_failure(compile_proc.stderr, "compile"),
            stderr=compile_proc.stderr,
            returncode=compile_proc.returncode,
        )

    if not out_py.exists():
        return TestResult(
            name=name, status="fail", stage="compile",
            failing_component="codegen",
            stderr=f"compile.py did not produce {out_py}",
            returncode=compile_proc.returncode,
        )

    # Step 2: run
    try:
        run_proc = subprocess.run(
            [sys.executable, str(out_py)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(lang_dir),
        )
    except subprocess.TimeoutExpired as e:
        return TestResult(name=name, status="fail", stage="run",
                          failing_component="runtime",
                          stderr=f"runtime timed out: {e}")

    if run_proc.returncode != 0:
        return TestResult(
            name=name, status="fail", stage="run",
            failing_component=_attribute_failure(run_proc.stderr, "run"),
            stderr=run_proc.stderr,
            actual=run_proc.stdout,
            expected=expected,
            returncode=run_proc.returncode,
        )

    actual = run_proc.stdout.rstrip()
    if actual == expected:
        return TestResult(name=name, status="pass")
    return TestResult(
        name=name, status="fail", stage="compare",
        failing_component=_attribute_failure("", "compare"),
        expected=expected, actual=actual,
        stderr=run_proc.stderr,
    )


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------

def verify(lang_dir: str | Path) -> VerificationReport:
    lang_dir = Path(lang_dir).resolve()
    spec = _load_spec(lang_dir)
    ext = spec.get("file_extension", ".toy")

    report = VerificationReport(lang_dir=str(lang_dir), file_extension=ext, all_passed=False)

    # User-supplied additional tests are also required.
    additional_names = []
    cust = spec.get("customization") or {}
    for t in cust.get("additional_tests") or []:
        name = t.get("name")
        if name and isinstance(name, str):
            additional_names.append(name)
    required = list(CANONICAL_TESTS) + [n for n in additional_names if n not in CANONICAL_TESTS]

    # Confirm required tests exist.
    tests_dir = lang_dir / "tests"
    for name in required:
        src = tests_dir / f"{name}{ext}"
        out = tests_dir / f"{name}.expected_output.txt"
        if not src.exists() or not out.exists():
            report.missing_canonical.append(name)

    # Run every required test (even if missing: produces a 'missing' entry).
    for name in required:
        report.tests.append(_run_one_test(lang_dir, name, ext))

    report.all_passed = (
        not report.missing_canonical
        and all(t.status == "pass" for t in report.tests)
    )
    return report


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python -m forge.orchestrator.verifier <lang_dir>")
        sys.exit(2)
    rep = verify(sys.argv[1])
    print(rep.summary())
    sys.exit(0 if rep.all_passed else 1)
