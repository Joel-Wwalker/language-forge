# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_010.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_010.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Atom('compute_examples'), [Compound("is", [Var('R1', 0), Compound('+', [Num(7), Compound('*', [Num(3), Num(2)])])]), Compound('write', [Var('R1', 0)]), Atom('nl'), Compound("is", [Var('R2', 1), Compound('//', [Num(20), Num(3)])]), Compound('write', [Var('R2', 1)]), Atom('nl'), Compound("is", [Var('R3', 2), Compound('mod', [Num(17), Num(5)])]), Compound('write', [Var('R3', 2)]), Atom('nl')])
print_solutions(solve([Atom('compute_examples')], {}, _KB), free_vars=[])
