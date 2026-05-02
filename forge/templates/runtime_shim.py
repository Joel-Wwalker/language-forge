"""Stdlib shim for any generated runtime that's missing helpers.

This file is the deterministic source of truth for the applied stdlib.
The generator inspects each language's `runtime.py` after the LLM has
emitted it, identifies missing `toy_*` helpers, and appends just those
from this file. Applied once; a marker comment makes it idempotent.

The helpers below are language-agnostic. They use only Python builtins
and `sys`, with `_builtins` aliased so they don't recurse into stdlib
re-exports the language defines.

ANY EDITS HERE PROPAGATE TO EVERY FUTURE LANGUAGE on the next forge or
re-render. To backfill existing languages, call
`forge.orchestrator.generator.apply_runtime_shim(lang_dir)`.
"""
# === FORGE_STDLIB_SHIM_BEGIN ===
import sys as _shim_sys
import builtins as _shim_builtins


def toy_input(prompt=""):
    return _shim_builtins.input(prompt)


def toy_list(*items):
    """`list(1, 2, 3)` returns a fresh Python list."""
    return _shim_builtins.list(items)


def toy_get(coll, k, default=None):
    """Read element by index (list, string) or key (dict). Returns default if absent."""
    if isinstance(coll, _shim_builtins.list):
        if isinstance(k, int) and 0 <= k < _shim_builtins.len(coll):
            return coll[k]
        return default
    if isinstance(coll, dict):
        return coll.get(k, default)
    if isinstance(coll, str):
        if isinstance(k, int) and 0 <= k < _shim_builtins.len(coll):
            return coll[k]
        return default
    raise TypeError("get(): unsupported type " + type(coll).__name__)


def toy_set(coll, k, v):
    """Mutate element by index or key. Returns the collection."""
    if isinstance(coll, _shim_builtins.list):
        if not isinstance(k, int):
            raise TypeError("set(): list keys must be integers")
        while _shim_builtins.len(coll) <= k:
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
    """`dict("a", 1, "b", 2)` returns {"a": 1, "b": 2}. dict() returns {}."""
    if _shim_builtins.len(pairs) % 2 != 0:
        raise ValueError("dict() needs an even number of arguments")
    return _shim_builtins.dict(_shim_builtins.zip(pairs[0::2], pairs[1::2]))


def toy_has(coll, k):
    if isinstance(coll, dict):
        return k in coll
    if isinstance(coll, _shim_builtins.list):
        return isinstance(k, int) and 0 <= k < _shim_builtins.len(coll)
    if isinstance(coll, str):
        return k in coll
    return False


def toy_keys(d):
    return _shim_builtins.list(d.keys())


def toy_range(a, b=None):
    if b is None:
        return _shim_builtins.list(_shim_builtins.range(a))
    return _shim_builtins.list(_shim_builtins.range(a, b))


def toy_split(s, sep):
    return s.split(sep)


def toy_join(sep, lst):
    parts = []
    for x in lst:
        if x is True:
            parts.append("true")
        elif x is False:
            parts.append("false")
        elif x is None:
            parts.append("null")
        else:
            parts.append(_shim_builtins.str(x))
    return sep.join(parts)


def toy_upper(s):
    return s.upper()


def toy_lower(s):
    return s.lower()


def toy_replace(s, old, new):
    return s.replace(old, new)


def toy_int(v):
    return _shim_builtins.int(v)


def toy_float(v):
    return _shim_builtins.float(v)


def toy_read_file(path):
    with _shim_builtins.open(path, "r", encoding="utf-8") as _f:
        return _f.read()


def toy_write_file(path, content):
    with _shim_builtins.open(path, "w", encoding="utf-8") as _f:
        _f.write(content)
    return None


def toy_argv():
    return _shim_builtins.list(_shim_sys.argv[1:])


def toy_exit(code=0):
    _shim_sys.exit(_shim_builtins.int(code))
# === FORGE_STDLIB_SHIM_END ===
