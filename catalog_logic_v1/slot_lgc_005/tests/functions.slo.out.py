# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_005.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_005.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('lines_spoken', [Num(0), Num(0)]), [])
_KB.add_clause(Compound('lines_spoken', [Var('Scenes', 0), Var('Total', 1)]), [Compound('>', [Var('Scenes', 0), Num(0)]), Compound("is", [Var('Scenes1', 2), Compound('-', [Var('Scenes', 0), Num(1)])]), Compound('lines_spoken', [Var('Scenes1', 2), Var('Subtotal', 3)]), Compound("is", [Var('Total', 1), Compound('+', [Var('Subtotal', 3), Num(15)])])])
print_solutions(solve([Compound('lines_spoken', [Num(5), Var('Result', 0)]), Compound('write', [Var('Result', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Result', 0)])
