# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_007.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_007.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


print_solutions(solve([Compound('=', [Var('Alpha', 0), Atom('int')]), Compound('write', [Var('Alpha', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Alpha', 0)])
print_solutions(solve([Compound('=', [Var('Beta', 0), Atom('bool')]), Compound('write', [Var('Beta', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Beta', 0)])
print_solutions(solve([Compound('=', [Var('Alpha', 0), Atom('int')]), Compound('=', [Var('Gamma', 1), Var('Alpha', 0)]), Compound('write', [Var('Gamma', 1)]), Atom('nl')], {}, _KB), free_vars=[Var('Alpha', 0), Var('Gamma', 1)])
