# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_007.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_007.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('add', [Var('X', 0), Var('Y', 1), Var('Sum', 2)]), [Compound("is", [Var('Sum', 2), Compound('+', [Var('X', 0), Var('Y', 1)])])])
_KB.add_clause(Compound('add_five', [Var('Y', 0), Var('Sum', 1)]), [Compound('add', [Num(5), Var('Y', 0), Var('Sum', 1)])])
_KB.add_clause(Compound('add_ten', [Var('Y', 0), Var('Sum', 1)]), [Compound('add', [Num(10), Var('Y', 0), Var('Sum', 1)])])
print_solutions(solve([Compound('add', [Num(3), Num(7), Var('R1', 0)]), Compound('write', [Atom('3 + 7 = ')]), Compound('write', [Var('R1', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R1', 0)])
print_solutions(solve([Compound('add_five', [Num(12), Var('R2', 0)]), Compound('write', [Atom('5 + 12 = ')]), Compound('write', [Var('R2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R2', 0)])
print_solutions(solve([Compound('add_ten', [Num(8), Var('R3', 0)]), Compound('write', [Atom('10 + 8 = ')]), Compound('write', [Var('R3', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R3', 0)])
