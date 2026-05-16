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


_KB.add_clause(Compound('apply_binary', [Var('Operation', 0), Var('X', 1), Var('Y', 2), Var('Result', 3)]), [Compound('call', [Var('Operation', 0), Var('X', 1), Var('Y', 2), Var('Result', 3)])])
_KB.add_clause(Compound('add_values', [Var('A', 0), Var('B', 1), Var('C', 2)]), [Compound("is", [Var('C', 2), Compound('+', [Var('A', 0), Var('B', 1)])])])
_KB.add_clause(Compound('multiply_values', [Var('A', 0), Var('B', 1), Var('C', 2)]), [Compound("is", [Var('C', 2), Compound('*', [Var('A', 0), Var('B', 1)])])])
print_solutions(solve([Compound('apply_binary', [Atom('add_values'), Num(10), Num(5), Var('R1', 0)]), Compound('write', [Var('R1', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R1', 0)])
print_solutions(solve([Compound('apply_binary', [Atom('multiply_values'), Num(6), Num(7), Var('R2', 0)]), Compound('write', [Var('R2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R2', 0)])
