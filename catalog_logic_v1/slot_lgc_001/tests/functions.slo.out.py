# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_001.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_001.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('double_relation', [Var('X', 0), Var('Y', 1)]), [Compound("is", [Var('Y', 1), Compound('*', [Var('X', 0), Num(2)])])])
_KB.add_clause(Compound('sum_relation', [Var('A', 0), Var('B', 1), Var('C', 2)]), [Compound("is", [Var('C', 2), Compound('+', [Var('A', 0), Var('B', 1)])])])
print_solutions(solve([Compound('double_relation', [Num(21), Var('R1', 0)]), Compound('write', [Var('R1', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R1', 0)])
print_solutions(solve([Compound('sum_relation', [Num(30), Num(12), Var('R2', 0)]), Compound('write', [Var('R2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R2', 0)])
