"""mllang runtime — helpers imported by transpiled Python source.

The mllang->Python codegen emits a `from mllang.runtime import (...)`
prelude. This module provides the names the prelude pulls in.

Conventions:
  - `_ml_*` prefixed names are internal (used by codegen for cons,
    constructor wrapping, match-error). They start with underscore so
    they don't clash with mllang user names (which are lowercase-leading
    by grammar).
  - `print_int` / `print_string` / etc. are OCaml-style names —
    callable from mllang source directly.
  - String + list helpers expose mllang-friendly names (snake_case;
    `string_upper` not `String.upper` since mllang has no module syntax
    in v1).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Match-error sentinel
# ---------------------------------------------------------------------------

class _MLMatchError(Exception):
    """Raised when a `match` cascade finds no matching arm.

    The codegen emits a `raise _MLMatchError(_v)` at the end of every
    match cascade so unmatched values are loud runtime errors rather
    than silent `None` returns.
    """
    def __init__(self, value):
        super().__init__(f"match failed on {value!r}")
        self.value = value


# ---------------------------------------------------------------------------
# Algebraic-data-type constructor tagged value
# ---------------------------------------------------------------------------

class _MLConstructor:
    """Tagged value produced by ADT constructors.

    A constructor application like `Circle 5` produces an instance with
    `.tag == "Circle"` and `.payload == 5`. Multi-arg constructors store
    their payload as a tuple: `Rectangle (3, 4)` -> `.payload == (3, 4)`.
    Nullary constructors store `.payload == None`.

    Equality is structural so pattern matching `| Circle r -> r * r` can
    test on both tag and (later) payload. `__repr__` is informative so
    match-error messages name the offending constructor.
    """
    __slots__ = ("tag", "payload")

    def __init__(self, tag, payload):
        self.tag = tag
        self.payload = payload

    def __eq__(self, other):
        return (
            isinstance(other, _MLConstructor)
            and self.tag == other.tag
            and self.payload == other.payload
        )

    def __hash__(self):
        return hash((self.tag, self.payload))

    def __repr__(self):
        if self.payload is None:
            return self.tag
        return f"{self.tag} {self.payload!r}"


# ---------------------------------------------------------------------------
# List cons (immutable prepend; returns a fresh Python list)
# ---------------------------------------------------------------------------

def _ml_cons(head, tail):
    """`h :: t` lowers to `_ml_cons(h, t)`.

    Returns a fresh list so the original `tail` isn't aliased. mllang
    is immutable-leaning; a fresh list keeps semantics clean.
    """
    return [head] + list(tail)


# ---------------------------------------------------------------------------
# Print primitives (OCaml-style, type-distinguished at source level)
# ---------------------------------------------------------------------------
#
# These all wrap Python's `print` but with `end=""` so the user controls
# newline placement via `print_newline ()` — same idiom as real OCaml.

def print_int(n):
    print(n, end="")


def print_string(s):
    print(s, end="")


def print_float(f):
    print(f, end="")


def print_newline(unit_arg=None):
    """`print_newline ()` — takes unit (None at runtime). The unit arg
    is accepted to match the OCaml signature `unit -> unit`."""
    print()


def print_endline(s):
    """`print_endline "msg"` — print + newline in one call. OCaml's
    convenience function; useful in canonical tests + themed bodies."""
    print(s)


def print_any(v):
    """Print any value as Python `str(v)` + newline. Generic printer
    used by the kata-pack test wrapper for results whose type isn't
    known statically (mllang is dynamic; kata tests can return ints,
    lists, booleans, etc.).

    Mirrors c_like's `print(v)` semantics so kata `expected` strings
    can be the same across families."""
    print(v)


# ---------------------------------------------------------------------------
# String primitives
# ---------------------------------------------------------------------------

def string_length(s):
    return len(s)


def string_upper(s):
    return s.upper()


def string_lower(s):
    return s.lower()


def string_concat(a, b):
    """`a ^ b` — string concatenation. Also available as the `^`
    operator at the source level (codegen lowers `^` to `+`); this
    function lets mllang user code call it by name when needed."""
    return a + b


# ---------------------------------------------------------------------------
# List primitives (head/tail/length/empty + the ones below in stdlib)
# ---------------------------------------------------------------------------

def list_length(lst):
    return len(lst)


def list_head(lst):
    """Raises on empty list — `match` on `[]` should catch that case
    in idiomatic mllang code."""
    return lst[0]


def list_tail(lst):
    return lst[1:]


def list_is_empty(lst):
    return len(lst) == 0


# ---------------------------------------------------------------------------
# Integer conversion (mllang `int_of_string`-style)
# ---------------------------------------------------------------------------

def string_of_int(n):
    return str(n)


def int_of_string(s):
    return int(s)
