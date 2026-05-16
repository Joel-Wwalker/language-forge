# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_004.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_004.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('average', [Var('Sum', 0), Var('Count', 1), Var('Result', 2)]), [Compound("is", [Var('Result', 2), Compound('//', [Var('Sum', 0), Var('Count', 1)])])])
print_solutions(solve([Compound('average', [Num(270), Num(3), Var('Avg', 0)]), Compound('write', [Var('Avg', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Avg', 0)])
