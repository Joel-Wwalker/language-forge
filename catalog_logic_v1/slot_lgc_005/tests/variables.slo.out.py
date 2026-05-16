# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_005.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_005.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


print_solutions(solve([Compound('=', [Var('X', 0), Atom('hello')]), Compound('write', [Var('X', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0)])
print_solutions(solve([Compound('=', [Var('X', 0), Num(42)]), Compound('=', [Var('Y', 1), Var('X', 0)]), Compound('write', [Var('Y', 1)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0), Var('Y', 1)])
print_solutions(solve([Compound("is", [Var('X', 0), Compound('+', [Num(3), Num(4)])]), Compound("is", [Var('Y', 1), Compound('*', [Var('X', 0), Num(2)])]), Compound('write', [Var('Y', 1)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0), Var('Y', 1)])
