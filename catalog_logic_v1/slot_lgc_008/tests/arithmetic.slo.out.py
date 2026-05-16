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


print_solutions(solve([Compound("is", [Var('X', 0), Compound('+', [Num(2), Num(3)])]), Compound('write', [Var('X', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0)])
print_solutions(solve([Compound("is", [Var('X', 0), Compound('-', [Num(10), Num(4)])]), Compound('write', [Var('X', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0)])
print_solutions(solve([Compound("is", [Var('X', 0), Compound('*', [Num(6), Num(7)])]), Compound('write', [Var('X', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0)])
print_solutions(solve([Compound("is", [Var('X', 0), Compound('//', [Num(20), Num(3)])]), Compound('write', [Var('X', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0)])
print_solutions(solve([Compound("is", [Var('X', 0), Compound('mod', [Num(20), Num(3)])]), Compound('write', [Var('X', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('X', 0)])
