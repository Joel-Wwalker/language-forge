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


_KB.add_clause(Compound('indulgences', [Var('X', 0), Var('Y', 1), Var('Sum', 2)]), [Compound("is", [Var('Sum', 2), Compound('+', [Var('X', 0), Var('Y', 1)])])])
_KB.add_clause(Compound('penance_days', [Var('Base', 0), Var('Severity', 1), Var('Total', 2)]), [Compound("is", [Var('Total', 2), Compound('*', [Var('Base', 0), Var('Severity', 1)])])])
_KB.add_clause(Compound('verses_per_scribe', [Var('Total', 0), Var('Scribes', 1), Var('Each', 2)]), [Compound("is", [Var('Each', 2), Compound('//', [Var('Total', 0), Var('Scribes', 1)])])])
print_solutions(solve([Compound('indulgences', [Num(40), Num(30), Var('R1', 0)]), Compound('write', [Var('R1', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R1', 0)])
print_solutions(solve([Compound('penance_days', [Num(7), Num(3), Var('R2', 0)]), Compound('write', [Var('R2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R2', 0)])
print_solutions(solve([Compound('verses_per_scribe', [Num(100), Num(4), Var('R3', 0)]), Compound('write', [Var('R3', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R3', 0)])
