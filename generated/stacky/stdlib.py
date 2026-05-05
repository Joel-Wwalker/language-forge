"""forthlang stdlib re-exports. The codegen prelude imports from
runtime directly; this file is convenience for tests/tooling that
want to inspect the canonical word list."""
from .runtime import (
    push, pop, top,
    dup, drop, swap, over, rot, nip, tuck,
    add, sub, mul, div, mod,
    eq, ne, lt, gt, le, ge,
    log_and, log_or, log_not,
    print_top, print_str, cr,
    declare_variable, declare_constant, pushv, fetch, store,
    truthy,
)

# Forth-canonical word names → runtime functions. Useful for kata
# checkers and the case-analysis fallback to discover what's available.
STDLIB_WORDS = {
    "dup": dup, "drop": drop, "swap": swap, "over": over,
    "rot": rot, "nip": nip, "tuck": tuck,
    "+": add, "-": sub, "*": mul, "/": div, "mod": mod,
    "=": eq, "<>": ne, "<": lt, ">": gt, "<=": le, ">=": ge,
    "and": log_and, "or": log_or, "not": log_not,
    ".": print_top, "cr": cr,
    "@": fetch, "!": store,
}

__all__ = ["STDLIB_WORDS"]
