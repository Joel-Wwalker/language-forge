# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_003.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_003.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


print_solutions(solve([Compound('=', [Var('X', 0), Num(42)]), Compound('write', [Var('X', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0)])
print_solutions(solve([Compound('=', [Var('Y', 0), Num(100)]), Compound("is", [Var('Z', 1), Compound('+', [Var('Y', 0), Num(58)])]), Compound('write', [Var('Z', 1)]), Atom('nl')], {}, _KB), free_vars=[Var('Y', 0), Var('Z', 1)])
print_solutions(solve([Compound('=', [make_partial_list([Var('First', 0)], Var('Rest', 1)), make_list([Num(1), Num(2), Num(3), Num(4)])]), Compound('write', [Var('First', 0)]), Atom('nl'), Compound('write', [Var('Rest', 1)]), Atom('nl')], {}, _KB), free_vars=[Var('First', 0), Var('Rest', 1)])
