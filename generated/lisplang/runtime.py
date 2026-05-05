# string-indexing-support: forge-patch (already supports str)
"""lisplang runtime. Same shape as toylang's runtime (the codegen
prelude imports `toy_*` names) so we don't fork stringification or
truthiness rules. Lisp-flavored: `nil` for None, `true`/`false` for
booleans (both the Lisp tradition AND what toylang's _toy_str produces).
"""
from __future__ import annotations

import builtins as _builtins
import os as _os
import sys as _sys


# ---------------------------------------------------------------------------
# Stringification + truthiness (Lisp-flavored: nil / true / false)
# ---------------------------------------------------------------------------

def _toy_str(v):
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "nil"
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return repr(v)
    if isinstance(v, list):
        return "(" + " ".join(_toy_str(x) for x in v) + ")"
    if isinstance(v, dict):
        parts = [f"{_toy_str(k)} {_toy_str(val)}" for k, val in v.items()]
        return "{" + " ".join(parts) + "}"
    return str(v)


def toy_print(*args):
    """print(...) in lisplang. Joins with spaces, terminates with newline.

    Lisp-flavored: prints `nil` for None, `true`/`false` for booleans,
    and lists in s-expression form: `(1 2 3)` not `[1, 2, 3]`.
    """
    _builtins.print(" ".join(_toy_str(a) for a in args))


def toy_str(v):
    return _toy_str(v)


def toy_truthy(v):
    """lisplang truthiness. nil and false are falsy; everything else
    (including 0 and empty string) is truthy. Mirrors Clojure semantics."""
    return v is not None and v is not False


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------

def toy_list(*items):
    return _builtins.list(items)


def toy_len(coll):
    return _builtins.len(coll)


def toy_get(coll, k, default=None):
    if isinstance(coll, _builtins.list):
        if isinstance(k, int) and 0 <= k < _builtins.len(coll):
            return coll[k]
        return default
    if isinstance(coll, dict):
        return coll.get(k, default)
    if isinstance(coll, str):
        if isinstance(k, int) and 0 <= k < _builtins.len(coll):
            return coll[k]
        return default
    raise TypeError(f"get(): unsupported type {type(coll).__name__}")


def toy_set(coll, k, v):
    if isinstance(coll, _builtins.list):
        if not isinstance(k, int):
            raise TypeError("set(): list keys must be integers")
        while _builtins.len(coll) <= k:
            coll.append(None)
        coll[k] = v
    elif isinstance(coll, dict):
        coll[k] = v
    else:
        raise TypeError("set(): need list or dict")
    return coll


def toy_push(lst, x):
    lst.append(x)
    return lst


def toy_pop(lst):
    return lst.pop()


def toy_dict(*pairs):
    if _builtins.len(pairs) % 2 != 0:
        raise ValueError("dict() needs an even number of arguments")
    return _builtins.dict(_builtins.zip(pairs[0::2], pairs[1::2]))


def toy_has(coll, k):
    if isinstance(coll, dict):
        return k in coll
    if isinstance(coll, _builtins.list):
        return isinstance(k, int) and 0 <= k < _builtins.len(coll)
    if isinstance(coll, str):
        return k in coll
    return False


def toy_keys(d):
    return _builtins.list(d.keys())


def toy_range(a, b=None):
    if b is None:
        return _builtins.list(_builtins.range(a))
    return _builtins.list(_builtins.range(a, b))


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------

def toy_split(s, sep):
    return s.split(sep)


def toy_join(sep, lst):
    return sep.join(_toy_str(x) for x in lst)


def toy_upper(s):
    return s.upper()


def toy_lower(s):
    return s.lower()


def toy_replace(s, old, new):
    return s.replace(old, new)


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def toy_int(v):
    return _builtins.int(v)


def toy_float(v):
    return _builtins.float(v)


# ---------------------------------------------------------------------------
# Files and processes
# ---------------------------------------------------------------------------

def toy_read_file(path):
    with _builtins.open(path, "r", encoding="utf-8") as f:
        return f.read()


def toy_write_file(path, content):
    with _builtins.open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return None


def toy_input(prompt=""):
    return _builtins.input(prompt)


def toy_argv():
    return _builtins.list(_sys.argv[1:])


def toy_exit(code=0):
    _sys.exit(_builtins.int(code))
