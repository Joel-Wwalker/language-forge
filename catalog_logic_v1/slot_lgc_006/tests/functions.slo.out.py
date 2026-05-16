# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_006.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_006.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('double_penance', [Var('Days', 0), Var('Result', 1)]), [Compound("is", [Var('Result', 1), Compound('*', [Var('Days', 0), Num(2)])])])
_KB.add_clause(Compound('factorial_verses', [Num(0), Num(1)]), [])
_KB.add_clause(Compound('factorial_verses', [Var('N', 0), Var('F', 1)]), [Compound('>', [Var('N', 0), Num(0)]), Compound("is", [Var('N1', 2), Compound('-', [Var('N', 0), Num(1)])]), Compound('factorial_verses', [Var('N1', 2), Var('F1', 3)]), Compound("is", [Var('F', 1), Compound('*', [Var('N', 0), Var('F1', 3)])])])
print_solutions(solve([Compound('double_penance', [Num(7), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('factorial_verses', [Num(5), Var('F', 0)]), Compound('write', [Var('F', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('F', 0)])
