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


_KB.add_clause(Compound('apply_rule', [Var('Rule', 0), Var('Argument', 1), Var('Result', 2)]), [Compound('call', [Var('Rule', 0), Var('Argument', 1), Var('Result', 2)])])
_KB.add_clause(Compound('venial_calc', [Var('Days', 0), Var('Penance', 1)]), [Compound("is", [Var('Penance', 1), Compound('*', [Var('Days', 0), Num(2)])])])
_KB.add_clause(Compound('mortal_calc', [Var('Days', 0), Var('Penance', 1)]), [Compound("is", [Var('Penance', 1), Compound('*', [Var('Days', 0), Num(10)])])])
print_solutions(solve([Compound('apply_rule', [Atom('venial_calc'), Num(3), Var('R1', 0)]), Compound('write', [Var('R1', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R1', 0)])
print_solutions(solve([Compound('apply_rule', [Atom('mortal_calc'), Num(3), Var('R2', 0)]), Compound('write', [Var('R2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R2', 0)])
