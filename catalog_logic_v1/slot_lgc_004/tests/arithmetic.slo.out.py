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


print_solutions(solve([Compound('=', [Var('Total', 0), Num(1000)]), Compound('=', [Var('Jobs', 1), Num(8)]), Compound("is", [Var('Per_Job', 2), Compound('//', [Var('Total', 0), Var('Jobs', 1)])]), Compound("is", [Var('Remainder', 3), Compound('mod', [Var('Total', 0), Var('Jobs', 1)])]), Compound('write', [Var('Per_Job', 2)]), Atom('nl'), Compound('write', [Var('Remainder', 3)]), Atom('nl')], {}, _KB), free_vars=[Var('Total', 0), Var('Jobs', 1), Var('Per_Job', 2), Var('Remainder', 3)])
