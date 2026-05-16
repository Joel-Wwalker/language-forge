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


_KB.add_clause(Compound('apply_check', [Var('Predicate', 0), Var('Input', 1), Var('Output', 2)]), [Compound('call', [Var('Predicate', 0), Var('Input', 1), Var('Output', 2)])])
_KB.add_clause(Compound('reduce_speed', [Var('Current', 0), Var('Safe', 1)]), [Compound("is", [Var('Safe', 1), Compound('-', [Var('Current', 0), Num(10)])])])
print_solutions(solve([Compound('apply_check', [Atom('reduce_speed'), Num(50), Var('Result', 0)]), Compound('write', [Var('Result', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Result', 0)])
print_solutions(solve([Compound('apply_check', [Atom('reduce_speed'), Num(75), Var('R2', 0)]), Compound('write', [Var('R2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R2', 0)])
