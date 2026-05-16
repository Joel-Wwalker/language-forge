# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_009.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_009.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('scale', [Var('Base', 0), Var('Factor', 1), Var('Result', 2)]), [Compound("is", [Var('Result', 2), Compound('*', [Var('Base', 0), Var('Factor', 1)])])])
_KB.add_clause(Compound('apply_scaling', [Var('Pred', 0), Var('Cups', 1), Var('Multiplier', 2), Var('Scaled', 3)]), [Compound('call', [Var('Pred', 0), Var('Cups', 1), Var('Multiplier', 2), Var('Scaled', 3)])])
print_solutions(solve([Compound('apply_scaling', [Atom('scale'), Num(4), Num(3), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('apply_scaling', [Atom('scale'), Num(5), Num(2), Var('R2', 0)]), Compound('write', [Var('R2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R2', 0)])
