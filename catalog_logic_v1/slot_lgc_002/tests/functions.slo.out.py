# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_002.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_002.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('braking_distance', [Num(0), Num(0)]), [])
_KB.add_clause(Compound('braking_distance', [Var('Speed', 0), Var('Distance', 1)]), [Compound('>', [Var('Speed', 0), Num(0)]), Compound("is", [Var('Distance', 1), Compound('*', [Var('Speed', 0), Num(2)])])])
print_solutions(solve([Compound('braking_distance', [Num(45), Var('D', 0)]), Compound('write', [Var('D', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('D', 0)])
print_solutions(solve([Compound('braking_distance', [Num(60), Var('D2', 0)]), Compound('write', [Var('D2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('D2', 0)])
