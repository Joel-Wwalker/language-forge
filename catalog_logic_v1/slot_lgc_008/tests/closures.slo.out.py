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


_KB.add_clause(Compound('add', [Var('N', 0), Var('X', 1), Var('Y', 2)]), [Compound("is", [Var('Y', 2), Compound('+', [Var('X', 1), Var('N', 0)])])])
print_solutions(solve([Compound('call', [Compound('add', [Num(5)]), Num(3), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('call', [Compound('add', [Num(10)]), Num(3), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('call', [Compound('add', [Num(5)]), Num(100), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('call', [Compound('add', [Num(5)]), Num(0), Var('A', 0)]), Compound('call', [Compound('add', [Num(10)]), Var('A', 0), Var('R', 1)]), Compound('write', [Var('R', 1)]), Atom('nl')], {}, _KB), free_vars=[Var('A', 0), Var('R', 1)])
