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


_KB.add_clause(Compound('make_allocator', [Var('Base', 0), Var('Alloc', 1)]), [Compound('=', [Var('Alloc', 1), Compound('quota', [Var('Base', 0)])])])
_KB.add_clause(Compound('apply_quota', [Compound('quota', [Var('Base', 0)]), Var('Request', 1), Var('Total', 2)]), [Compound("is", [Var('Total', 2), Compound('+', [Var('Base', 0), Var('Request', 1)])])])
print_solutions(solve([Compound('make_allocator', [Num(100), Var('Q', 0)]), Compound('apply_quota', [Var('Q', 0), Num(50), Var('T1', 1)]), Compound('write', [Var('T1', 1)]), Atom('nl'), Compound('apply_quota', [Var('Q', 0), Num(75), Var('T2', 2)]), Compound('write', [Var('T2', 2)]), Atom('nl')], {}, _KB), free_vars=[Var('Q', 0), Var('T1', 1), Var('T2', 2)])
