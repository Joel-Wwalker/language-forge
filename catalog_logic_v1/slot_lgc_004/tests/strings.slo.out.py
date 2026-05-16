# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_004.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_004.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


print_solutions(solve([Compound('write', [Atom('Hello, World!')]), Atom('nl')], {}, _KB), free_vars=[])
print_solutions(solve([Compound('write', [Atom('a string with spaces')]), Atom('nl')], {}, _KB), free_vars=[])
print_solutions(solve([Compound('=', [Var('X', 0), Atom('a quoted atom')]), Compound('write', [Var('X', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0)])
