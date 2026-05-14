"""Tests for the hand-written mllang reference compiler.

mllang is the fourth syntax-family reference, parallel to:
  - toylang (c_like)
  - lisplang (s_expression)
  - forthlang (stack_based)

The family is `ml_like` (dynamic OCaml-flavored). See `MLLANG_DESIGN.md`
in the workspace root for the surface-language design + compilation
strategy.

These tests pin the Stage B acceptance gate from
ml-family-experiment-instructions.md: 8/8 canonical tests must pass on
the hand-written reference, standalone, before any registration with
the generator pipeline.
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
MLLANG_DIR = WORKSPACE_ROOT / "generated" / "mllang"


def _ensure_generated_on_path():
    p = str(WORKSPACE_ROOT / "generated")
    if p not in sys.path:
        sys.path.insert(0, p)


# ---------------------------------------------------------------------------
# Reference compiler file presence
# ---------------------------------------------------------------------------

def test_mllang_reference_exists():
    """The reference compiler must ship all the files the template-from-
    reference path expects."""
    assert MLLANG_DIR.exists(), "mllang reference compiler is missing"
    for f in ("__init__.py", "parser.py", "codegen.py", "runtime.py",
              "stdlib.py", "compile.py", "resolved_spec.json", "theme.css"):
        assert (MLLANG_DIR / f).exists(), f"mllang/{f} missing"
    assert (MLLANG_DIR / "tests").is_dir()


def test_mllang_canonical_test_files_exist():
    """All 8 canonical tests + their expected outputs must be on disk."""
    canonical = [
        "hello_world", "arithmetic", "variables", "conditionals",
        "loops", "functions", "closures", "strings",
    ]
    for name in canonical:
        src = MLLANG_DIR / "tests" / f"{name}.ml"
        exp = MLLANG_DIR / "tests" / f"{name}.expected_output.txt"
        assert src.exists(), f"missing tests/{name}.ml"
        assert exp.exists(), f"missing tests/{name}.expected_output.txt"


# ---------------------------------------------------------------------------
# 8 canonical tests must all pass on the reference
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("test_name", [
    "hello_world", "arithmetic", "variables", "conditionals",
    "loops", "functions", "closures", "strings",
])
def test_mllang_canonical_test_runs(test_name):
    """Each canonical test compiles + runs + matches expected output.

    The Stage B acceptance gate from
    ml-family-experiment-instructions.md: 8/8 canonical pass on the
    hand-written reference, standalone, before any integration.
    """
    _ensure_generated_on_path()
    from mllang.parser import parse
    from mllang.codegen import generate
    src = (MLLANG_DIR / "tests" / f"{test_name}.ml").read_text(encoding="utf-8")
    expected = (MLLANG_DIR / "tests" / f"{test_name}.expected_output.txt").read_text(encoding="utf-8")
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == expected, (
        f"output mismatch for {test_name}.ml\n"
        f"expected: {expected!r}\n"
        f"actual:   {buf.getvalue()!r}\n"
        f"--- generated python ---\n{py}"
    )


# ---------------------------------------------------------------------------
# Behavioral pins for the things the design doc called out
# ---------------------------------------------------------------------------

def test_mllang_match_on_list_pattern():
    """`match lst with | [] -> 0 | h :: t -> h + sum t` must work.
    Per the design doc, pattern matching is the family's distinctive
    feature; the loops canonical test exercises it directly."""
    _ensure_generated_on_path()
    from mllang.parser import parse
    from mllang.codegen import generate
    src = """
let rec sum lst = match lst with
  | [] -> 0
  | h :: t -> h + sum t
;;
print_int (sum [10; 20; 30]) ;;
print_newline () ;;
"""
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == "60\n"


def test_mllang_adt_constructor():
    """ADT constructors lower to `_MLConstructor(tag, payload)` and
    `match` discriminates by tag. Per design doc Section 3."""
    _ensure_generated_on_path()
    from mllang.parser import parse
    from mllang.codegen import generate
    src = """
type shape = Circle of int | Square of int ;;
let area s = match s with
  | Circle r -> r * r * 3
  | Square w -> w * w
;;
print_int (area (Circle 5)) ;;
print_newline () ;;
print_int (area (Square 4)) ;;
print_newline () ;;
"""
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == "75\n16\n"


def test_mllang_unmatched_value_raises():
    """An unmatched value at a `match` cascade must raise _MLMatchError,
    not silently fall through to None. Per design doc Section 3."""
    _ensure_generated_on_path()
    from mllang.parser import parse
    from mllang.codegen import generate
    from mllang.runtime import _MLMatchError
    src = """
let describe n = match n with
  | 0 -> "zero"
  | 1 -> "one"
;;
print_string (describe 42) ;;
"""
    py = generate(parse(src))
    with pytest.raises(_MLMatchError):
        exec(py, {"__name__": "__main__"})


def test_mllang_closure_capture():
    """Closures capture their lexical environment. The canonical
    closures test exercises this via `make_adder`."""
    _ensure_generated_on_path()
    from mllang.parser import parse
    from mllang.codegen import generate
    src = """
let make_adder n = fun x -> x + n ;;
let add7 = make_adder 7 ;;
print_int (add7 100) ;;
print_newline () ;;
"""
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == "107\n"


def test_mllang_recursive_let_rec():
    """`let rec f n = ... f (n - 1) ...` must produce a Python def that
    can see its own name."""
    _ensure_generated_on_path()
    from mllang.parser import parse
    from mllang.codegen import generate
    src = """
let rec fact n = if n <= 1 then 1 else n * fact (n - 1) ;;
print_int (fact 6) ;;
print_newline () ;;
"""
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == "720\n"


def test_mllang_sequence_in_parens():
    """`(e1; e2; e3)` evaluates all and returns last. Used in canonical
    `loops` for side-effecting count_down."""
    _ensure_generated_on_path()
    from mllang.parser import parse
    from mllang.codegen import generate
    src = """
let result = (print_string "a"; print_string "b"; 42) ;;
print_int result ;;
print_newline () ;;
"""
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == "ab42\n"


def test_mllang_string_concat_with_caret():
    """The `^` operator concatenates strings. Lowered to Python `+`."""
    _ensure_generated_on_path()
    from mllang.parser import parse
    from mllang.codegen import generate
    src = """
print_string ("hello " ^ "world") ;;
print_newline () ;;
"""
    py = generate(parse(src))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(py, {"__name__": "__main__"})
    assert buf.getvalue() == "hello world\n"


def test_mllang_resolved_spec_contract():
    """The resolved_spec.json declares the ml_like family and the right
    surface forms. Stage C will use this to wire up the family in the
    spec builder."""
    import json
    spec = json.loads((MLLANG_DIR / "resolved_spec.json").read_text(encoding="utf-8"))
    assert spec["lang_name"] == "mllang"
    assert spec["options"]["syntax"] == "ml_like"
    assert spec["options"]["typing"] == "dynamic"
    assert spec["options"]["memory"] == "host_gc"
    assert spec["file_extension"] == ".ml"
    assert spec["statement_terminator"] == ";;"
    assert "let" in spec["keywords"]
    assert "match" in spec["keywords"]
    assert "rec" in spec["keywords"]
