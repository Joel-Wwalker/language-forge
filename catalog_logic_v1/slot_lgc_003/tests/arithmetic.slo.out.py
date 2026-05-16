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


print_solutions(solve([Compound("is", [Var('Sum', 0), Compound('+', [Num(7), Num(13)])]), Compound('write', [Var('Sum', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Sum', 0)])
print_solutions(solve([Compound("is", [Var('Difference', 0), Compound('-', [Num(20), Num(8)])]), Compound('write', [Var('Difference', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Difference', 0)])
print_solutions(solve([Compound("is", [Var('Product', 0), Compound('*', [Num(3), Num(4)])]), Compound('write', [Var('Product', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Product', 0)])
print_solutions(solve([Compound("is", [Var('Quotient', 0), Compound('//', [Num(21), Num(3)])]), Compound('write', [Var('Quotient', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Quotient', 0)])
print_solutions(solve([Compound("is", [Var('Remainder', 0), Compound('mod', [Num(17), Num(5)])]), Compound('write', [Var('Remainder', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Remainder', 0)])
