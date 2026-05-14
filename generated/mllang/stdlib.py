"""mllang stdlib — functional helpers + runtime re-exports.

The codegen's prelude imports from BOTH runtime.py and stdlib.py; this
file lives next to runtime.py and exposes the higher-level functional
helpers that build on the runtime primitives. Matches the toylang /
lisplang / forthlang convention where `stdlib.py` is a thin functional
layer over `runtime.py`'s primitives.

These names are callable from mllang source directly: `list_map (fun x
-> x + 1) [1; 2; 3]` works because the codegen prelude pulls them in.
"""
from __future__ import annotations

from .runtime import (
    _ml_cons,
    print_int,
    print_string,
    print_float,
    print_newline,
    print_endline,
    string_length,
    string_upper,
    string_lower,
    string_concat,
    list_length,
    list_head,
    list_tail,
    list_is_empty,
    string_of_int,
    int_of_string,
)


# ---------------------------------------------------------------------------
# Functional list helpers (the OCaml List.* idiom, named with underscores
# since mllang v1 has no module syntax)
# ---------------------------------------------------------------------------

def list_map(f, lst):
    """`List.map` in OCaml."""
    return [f(x) for x in lst]


def list_filter(pred, lst):
    """`List.filter` in OCaml."""
    return [x for x in lst if pred(x)]


def list_fold_left(f, acc, lst):
    """`List.fold_left` in OCaml. `f` takes (accumulator, element)
    and returns the new accumulator. Iterates left-to-right.
    """
    for x in lst:
        acc = f(acc, x)
    return acc


def list_fold_right(f, lst, acc):
    """`List.fold_right` in OCaml. Note OCaml's argument order:
    `(elem, acc) -> acc`, list, initial. Iterates right-to-left."""
    for x in reversed(lst):
        acc = f(x, acc)
    return acc


def list_reverse(lst):
    return list(reversed(lst))


def list_range(start, stop):
    """`list_range 0 5` returns `[0; 1; 2; 3; 4]`. Half-open interval,
    Python convention."""
    return list(range(start, stop))


def list_concat(a, b):
    """`a @ b` in OCaml — list concatenation."""
    return list(a) + list(b)
