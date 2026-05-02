"""Tests for the applied stdlib (lists, dicts, strings, file I/O, etc.).

These confirm:
  1. spec_builder ships the expanded function list as a default
  2. the toylang reference runtime implements every function correctly
  3. the toylang stdlib re-exports them all under bare names
  4. an end-to-end toylang program that uses the new stdlib actually runs
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from forge.orchestrator.spec_builder import build_spec


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


# ---------------------------------------------------------------------------
# Spec defaults
# ---------------------------------------------------------------------------

def test_default_stdlib_has_collection_and_io_functions():
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "demo")
    names = {f["name"] for f in spec["stdlib"]["functions"]}

    # Collections
    assert {"list", "len", "get", "set", "push", "pop", "dict", "has", "keys", "range"}.issubset(names)
    # Strings
    assert {"split", "join", "upper", "lower", "replace"}.issubset(names)
    # Numbers
    assert {"int", "float"}.issubset(names)
    # File / process
    assert {"read_file", "write_file", "argv", "exit"}.issubset(names)
    # Output / input
    assert {"print", "input"}.issubset(names)


def test_every_stdlib_function_has_signature_and_description():
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}, "demo")
    for f in spec["stdlib"]["functions"]:
        assert f["name"]
        assert f["description"]
        assert "signature" in f


# ---------------------------------------------------------------------------
# toylang runtime: each helper behaves as documented
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def runtime():
    """Import the toylang runtime once for the module."""
    import importlib, sys as _sys
    sys_path_added = str(WORKSPACE / "generated")
    if sys_path_added not in _sys.path:
        _sys.path.insert(0, sys_path_added)
    return importlib.import_module("toylang.runtime")


def test_toy_list_builds_a_python_list(runtime):
    assert runtime.toy_list(1, 2, 3) == [1, 2, 3]
    assert runtime.toy_list() == []


def test_toy_get_returns_default_for_missing(runtime):
    assert runtime.toy_get([10, 20], 0) == 10
    assert runtime.toy_get([10, 20], 5) is None
    assert runtime.toy_get([10, 20], 5, "default") == "default"
    assert runtime.toy_get({"a": 1}, "a") == 1
    assert runtime.toy_get({"a": 1}, "missing") is None


def test_toy_set_mutates_and_returns_collection(runtime):
    lst = [0, 0, 0]
    out = runtime.toy_set(lst, 1, 99)
    assert lst == [0, 99, 0]
    assert out is lst   # same list object


def test_toy_push_pop_round_trip(runtime):
    lst = []
    runtime.toy_push(lst, 1)
    runtime.toy_push(lst, 2)
    assert lst == [1, 2]
    assert runtime.toy_pop(lst) == 2
    assert lst == [1]


def test_toy_dict_from_pairs(runtime):
    d = runtime.toy_dict("a", 1, "b", 2)
    assert d == {"a": 1, "b": 2}


def test_toy_dict_rejects_odd_args(runtime):
    with pytest.raises(ValueError):
        runtime.toy_dict("a", 1, "b")


def test_toy_has(runtime):
    assert runtime.toy_has({"a": 1}, "a")
    assert not runtime.toy_has({"a": 1}, "b")
    assert runtime.toy_has([10, 20], 0)
    assert not runtime.toy_has([10, 20], 5)


def test_toy_keys_returns_list_in_insertion_order(runtime):
    d = runtime.toy_dict("first", 1, "second", 2, "third", 3)
    assert runtime.toy_keys(d) == ["first", "second", "third"]


def test_toy_range(runtime):
    assert runtime.toy_range(5) == [0, 1, 2, 3, 4]
    assert runtime.toy_range(2, 6) == [2, 3, 4, 5]


def test_toy_split_join(runtime):
    parts = runtime.toy_split("a,b,c,d", ",")
    assert parts == ["a", "b", "c", "d"]
    assert runtime.toy_join("-", parts) == "a-b-c-d"


def test_toy_string_case(runtime):
    assert runtime.toy_upper("hello") == "HELLO"
    assert runtime.toy_lower("HELLO") == "hello"
    assert runtime.toy_replace("foo bar foo", "foo", "baz") == "baz bar baz"


def test_toy_int_float(runtime):
    assert runtime.toy_int("42") == 42
    assert runtime.toy_float("3.14") == 3.14


def test_toy_read_write_file_round_trip(runtime, tmp_path):
    p = tmp_path / "x.txt"
    runtime.toy_write_file(str(p), "hello\nworld\n")
    assert runtime.toy_read_file(str(p)) == "hello\nworld\n"


# ---------------------------------------------------------------------------
# Stdlib re-exports
# ---------------------------------------------------------------------------

def test_toylang_stdlib_re_exports_all():
    """The stdlib module should expose every documented function under the bare name."""
    import importlib, sys as _sys
    if str(WORKSPACE / "generated") not in _sys.path:
        _sys.path.insert(0, str(WORKSPACE / "generated"))
    stdlib = importlib.import_module("toylang.stdlib")
    expected = {"print", "input", "list", "len", "get", "set", "push", "pop",
                "dict", "has", "keys", "range", "str", "split", "join",
                "upper", "lower", "replace", "int", "float",
                "read_file", "write_file", "argv", "exit"}
    actual = set(stdlib.__all__)
    assert expected.issubset(actual), f"missing exports: {expected - actual}"


# ---------------------------------------------------------------------------
# End-to-end: a toylang program that uses the new stdlib runs cleanly.
# ---------------------------------------------------------------------------

def test_toylang_stdlib_program_runs(tmp_path):
    """Compile and run tests/stdlib.toy through subprocess. Compares to expected output."""
    src = TOYLANG_DIR / "tests" / "stdlib.toy"
    expected = TOYLANG_DIR / "tests" / "stdlib.expected_output.txt"
    assert src.exists(), "stdlib showcase test missing"
    assert expected.exists(), "expected_output for stdlib test missing"

    # Compile
    proc = subprocess.run(
        [sys.executable, str(TOYLANG_DIR / "compile.py"), str(src)],
        capture_output=True, text=True, timeout=20,
        cwd=str(TOYLANG_DIR),
        env={**__import__("os").environ,
             "PYTHONPATH": str(WORKSPACE / "generated")},
    )
    assert proc.returncode == 0, f"compile failed: {proc.stderr}"

    out_py = src.with_suffix(src.suffix + ".out.py")
    run = subprocess.run(
        [sys.executable, str(out_py)],
        capture_output=True, text=True, timeout=20,
        cwd=str(TOYLANG_DIR),
        env={**__import__("os").environ,
             "PYTHONPATH": str(WORKSPACE / "generated")},
    )
    assert run.returncode == 0, f"run failed: {run.stderr}"
    assert run.stdout.rstrip() == expected.read_text(encoding="utf-8").rstrip()
