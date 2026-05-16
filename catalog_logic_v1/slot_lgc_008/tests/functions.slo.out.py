# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_008.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_008.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('double', [Var('X', 0), Var('Y', 1)]), [Compound("is", [Var('Y', 1), Compound('*', [Var('X', 0), Num(2)])])])
_KB.add_clause(Compound('square', [Var('X', 0), Var('Y', 1)]), [Compound("is", [Var('Y', 1), Compound('*', [Var('X', 0), Var('X', 0)])])])
print_solutions(solve([Compound('double', [Num(5), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('double', [Num(7), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('square', [Num(4), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('double', [Num(3), Var('A', 0)]), Compound('square', [Var('A', 0), Var('B', 1)]), Compound('write', [Var('B', 1)]), Atom('nl')], {}, _KB), free_vars=[Var('A', 0), Var('B', 1)])
