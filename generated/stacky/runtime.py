# string-indexing-support: forge-patch (already supports str)
"""forthlang runtime. Provides the data stack + every built-in word.

Forth words consume / produce stack values. We model the stack as a
plain Python list with `.append()` / `.pop()`. Every built-in word is
a top-level function; the codegen emits `def square(): dup(); mul()`
style nested defs for user-defined words and they all manipulate the
same global `_stack`.

Stringification mirrors toylang's: numbers print as ints when whole,
booleans as `true`/`false`, lists as `[1, 2, 3]`. Forth dialects
traditionally print booleans as `-1`/`0` but that's user-hostile;
we use the same readable form as the rest of Forge.
"""
from __future__ import annotations

import builtins as _builtins
import sys as _sys


# ---------------------------------------------------------------------------
# Data stack + variable storage
# ---------------------------------------------------------------------------

_stack: list = []
_vars: dict = {}    # `variable name` declarations: name -> cell value
_consts: dict = {}  # `value constant name` declarations: name -> value


def push(value) -> None:
    _stack.append(value)


def pop():
    if not _stack:
        raise StackUnderflow("stack underflow on `pop`")
    return _stack.pop()


def top():
    if not _stack:
        raise StackUnderflow("stack underflow on `top`")
    return _stack[-1]


class StackUnderflow(RuntimeError):
    """Raised when a word tries to pop more values than the stack holds.
    Mirrors Forth's runtime failure mode but with a readable Python
    traceback the user can debug."""


# ---------------------------------------------------------------------------
# Stringification + truthiness
# ---------------------------------------------------------------------------

def _toy_str(v) -> str:
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
        return "[" + ", ".join(_toy_str(x) for x in v) + "]"
    return str(v)


def truthy(v) -> bool:
    """Forge truthiness. nil/None and false/0 are falsy; everything
    else is truthy. Forth's `0` is falsy by tradition, so we follow."""
    if v is None or v is False:
        return False
    if v == 0:
        return False
    return True


# ---------------------------------------------------------------------------
# Stack manipulation words
# ---------------------------------------------------------------------------

def dup() -> None:
    """( a -- a a )"""
    if not _stack:
        raise StackUnderflow("stack underflow on `dup`")
    _stack.append(_stack[-1])


def drop() -> None:
    """( a -- )"""
    pop()


def swap() -> None:
    """( a b -- b a )"""
    b = pop(); a = pop()
    _stack.append(b); _stack.append(a)


def over() -> None:
    """( a b -- a b a )"""
    if len(_stack) < 2:
        raise StackUnderflow("stack underflow on `over`")
    _stack.append(_stack[-2])


def rot() -> None:
    """( a b c -- b c a )"""
    c = pop(); b = pop(); a = pop()
    _stack.append(b); _stack.append(c); _stack.append(a)


def nip() -> None:
    """( a b -- b )"""
    b = pop(); pop()
    _stack.append(b)


def tuck() -> None:
    """( a b -- b a b )"""
    b = pop(); a = pop()
    _stack.append(b); _stack.append(a); _stack.append(b)


# ---------------------------------------------------------------------------
# Arithmetic + comparison + logical (postfix; pop two, push result)
# ---------------------------------------------------------------------------

def add() -> None:
    b = pop(); a = pop(); _stack.append(a + b)


def sub() -> None:
    b = pop(); a = pop(); _stack.append(a - b)


def mul() -> None:
    b = pop(); a = pop(); _stack.append(a * b)


def div() -> None:
    b = pop(); a = pop()
    # Integer division when both ints (Forth tradition).
    if isinstance(a, int) and isinstance(b, int):
        _stack.append(a // b)
    else:
        _stack.append(a / b)


def mod() -> None:
    b = pop(); a = pop(); _stack.append(a % b)


def eq() -> None:
    b = pop(); a = pop(); _stack.append(a == b)


def ne() -> None:
    b = pop(); a = pop(); _stack.append(a != b)


def lt() -> None:
    b = pop(); a = pop(); _stack.append(a < b)


def gt() -> None:
    b = pop(); a = pop(); _stack.append(a > b)


def le() -> None:
    b = pop(); a = pop(); _stack.append(a <= b)


def ge() -> None:
    b = pop(); a = pop(); _stack.append(a >= b)


def log_and() -> None:
    b = pop(); a = pop(); _stack.append(truthy(a) and truthy(b))


def log_or() -> None:
    b = pop(); a = pop(); _stack.append(truthy(a) or truthy(b))


def log_not() -> None:
    a = pop(); _stack.append(not truthy(a))


# ---------------------------------------------------------------------------
# Variables + constants (memory)
# ---------------------------------------------------------------------------

def declare_variable(name: str) -> None:
    """`variable foo` declares `foo` with initial value 0."""
    _vars[name] = 0


def declare_constant(name: str, value) -> None:
    _consts[name] = value


def pushv(name: str) -> None:
    """Push the variable's address (its name string) for use with @ / !."""
    _stack.append(name)


def fetch() -> None:
    """`@ ( name -- value )`. Pops a variable name, pushes its value."""
    name = pop()
    if not isinstance(name, str) or name not in _vars:
        raise RuntimeError(f"`@`: not a variable: {name!r}")
    _stack.append(_vars[name])


def store() -> None:
    """`! ( value name -- )`. Pops a variable name + value, stores."""
    name = pop()
    value = pop()
    if not isinstance(name, str):
        raise RuntimeError(f"`!`: not a variable address: {name!r}")
    _vars[name] = value


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_top() -> None:
    """`. ( a -- )` Pop and print top of stack with a trailing space.
    Forth tradition prints a trailing space; we follow but the tests
    strip surrounding whitespace from `.expected_output.txt` lines."""
    v = pop()
    _builtins.print(_toy_str(v))


def print_str(s: str) -> None:
    """`." text"` prints the literal text. No trailing newline."""
    _builtins.print(s, end="")


def cr() -> None:
    """`cr` prints a newline."""
    _builtins.print()


# ---------------------------------------------------------------------------
# Aliases the codegen prelude imports
# ---------------------------------------------------------------------------

# These are also defined above as plain functions; the codegen prelude
# imports them by name so user `def` shadowing inside a colon-definition
# works without breaking the runtime's own dispatch.

# === FORGE_STDLIB_SHIM_BEGIN ===
# Auto-applied by Forge: deterministic stdlib helpers the codegen
# PRELUDE imports. Do not edit between BEGIN/END markers; rerun the
# generator to refresh.
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

# === FORGE_STACK_SHIM_BEGIN ===
# Auto-applied by Forge: canonical stack_classics vocabulary.
# These mutate the same `_stack` global the existing runtime uses,
# so values pushed/popped by these helpers interleave correctly
# with language-specific words. Re-run the generator to refresh.

import builtins as _forge_b

def forge_nil():
    _stack.append(None)

def forge_true():
    _stack.append(True)

def forge_false():
    _stack.append(False)

def forge_make_list():
    _stack.append([])

def forge_make_dict():
    _stack.append({})

def forge_make_range():
    n = _stack.pop()
    _stack.append(_forge_b.list(_forge_b.range(n)))

def forge_list_get():
    k = _stack.pop(); coll = _stack.pop()
    if isinstance(coll, _forge_b.dict):
        _stack.append(coll.get(k))
    elif isinstance(coll, (_forge_b.list, _forge_b.str)):
        if isinstance(k, int) and 0 <= k < _forge_b.len(coll):
            _stack.append(coll[k])
        else:
            _stack.append(None)
    else:
        _stack.append(None)

def forge_list_push():
    v = _stack.pop(); lst = _stack.pop()
    lst.append(v)
    _stack.append(lst)

def forge_list_pop():
    lst = _stack.pop()
    _stack.append(lst.pop())

def forge_list_len():
    coll = _stack.pop()
    _stack.append(_forge_b.len(coll))

def forge_dict_set():
    v = _stack.pop(); k = _stack.pop(); d = _stack.pop()
    d[k] = v
    _stack.append(d)

def forge_dict_has():
    k = _stack.pop(); coll = _stack.pop()
    try: _stack.append(k in coll)
    except Exception: _stack.append(False)

# === FORGE_STACK_SHIM_END ===