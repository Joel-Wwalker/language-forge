"""Direct tests on the hand-written toylang codegen.

Smaller-grained than the verifier — useful when iterating on codegen behavior
without paying the parse+exec roundtrip per test.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "generated"))


def _compile(src: str) -> str:
    from toylang.parser import parse
    from toylang.codegen import generate
    return generate(parse(src))


def test_emits_nonlocal_for_closure_assignment():
    src = """
    func make() {
        var count = 0;
        func inc() {
            count = count + 1;
            return count;
        }
        return inc;
    }
    """
    out = _compile(src)
    assert "nonlocal count" in out


def test_does_not_emit_nonlocal_for_pure_local_assignment():
    src = """
    func add(a, b) {
        var c = a + b;
        return c;
    }
    """
    out = _compile(src)
    assert "nonlocal" not in out


def test_translates_logical_operators():
    src = "var x = true && false;\n"
    out = _compile(src)
    assert "and" in out and "&&" not in out


def test_translates_bang_to_not():
    src = "var x = !true;\n"
    out = _compile(src)
    assert "not True" in out


def test_truthiness_wrapper_used():
    src = "if (1) { print(\"yes\"); }\n"
    out = _compile(src)
    assert "_toy_truthy" in out
