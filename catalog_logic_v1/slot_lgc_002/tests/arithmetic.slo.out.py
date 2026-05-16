# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_002.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_002.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


print_solutions(solve([Compound("is", [Var('Sum', 0), Compound('+', [Num(750), Num(250)])]), Compound('write', [Var('Sum', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Sum', 0)])
print_solutions(solve([Compound("is", [Var('Diff', 0), Compound('-', [Num(1200), Num(180)])]), Compound('write', [Var('Diff', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Diff', 0)])
print_solutions(solve([Compound("is", [Var('Product', 0), Compound('*', [Num(8), Num(125)])]), Compound('write', [Var('Product', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Product', 0)])
print_solutions(solve([Compound("is", [Var('Quotient', 0), Compound('/', [Num(2400), Num(6)])]), Compound('write', [Var('Quotient', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Quotient', 0)])
print_solutions(solve([Compound("is", [Var('Remainder', 0), Compound('mod', [Num(47), Num(5)])]), Compound('write', [Var('Remainder', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Remainder', 0)])
