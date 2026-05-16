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


_KB.add_clause(Compound('sum_integers', [Num(0), Num(0)]), [])
_KB.add_clause(Compound('sum_integers', [Var('N', 0), Var('Total', 1)]), [Compound('>', [Var('N', 0), Num(0)]), Compound("is", [Var('N1', 2), Compound('-', [Var('N', 0), Num(1)])]), Compound('sum_integers', [Var('N1', 2), Var('Subtotal', 3)]), Compound("is", [Var('Total', 1), Compound('+', [Var('Subtotal', 3), Var('N', 0)])])])
print_solutions(solve([Compound('sum_integers', [Num(10), Var('Result', 0)]), Compound('write', [Var('Result', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Result', 0)])
