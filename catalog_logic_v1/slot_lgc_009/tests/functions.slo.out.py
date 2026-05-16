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


_KB.add_clause(Compound('scale_cups', [Var('Base', 0), Var('Factor', 1), Var('Result', 2)]), [Compound("is", [Var('Result', 2), Compound('*', [Var('Base', 0), Var('Factor', 1)])])])
_KB.add_clause(Compound('total_servings', [Var('Batch1', 0), Var('Batch2', 1), Var('Total', 2)]), [Compound("is", [Var('Total', 2), Compound('+', [Var('Batch1', 0), Var('Batch2', 1)])])])
print_solutions(solve([Compound('scale_cups', [Num(3), Num(2), Var('Doubled', 0)]), Compound('write', [Var('Doubled', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Doubled', 0)])
print_solutions(solve([Compound('scale_cups', [Num(4), Num(3), Var('Tripled', 0)]), Compound('write', [Var('Tripled', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Tripled', 0)])
print_solutions(solve([Compound('total_servings', [Num(12), Num(8), Var('All', 0)]), Compound('write', [Var('All', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('All', 0)])
