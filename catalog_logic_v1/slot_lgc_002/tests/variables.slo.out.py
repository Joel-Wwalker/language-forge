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


print_solutions(solve([Compound('=', [Var('State', 0), Atom('green')]), Compound('write', [Var('State', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('State', 0)])
print_solutions(solve([Compound('=', [Var('Distance', 0), Num(500)]), Compound("is", [Var('SafeMargin', 1), Compound('+', [Var('Distance', 0), Num(250)])]), Compound('write', [Var('SafeMargin', 1)]), Atom('nl')], {}, _KB), free_vars=[Var('Distance', 0), Var('SafeMargin', 1)])
