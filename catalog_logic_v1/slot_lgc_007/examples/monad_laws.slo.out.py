# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_007.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_007.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('unit', [Var('X', 0), Var('X', 0)]), [])
_KB.add_clause(Compound('bind', [Var('M', 0), Var('F', 1), Var('Result', 2)]), [Compound('call', [Var('F', 1), Var('M', 0), Var('Result', 2)])])
_KB.add_clause(Compound('add_ten', [Var('X', 0), Var('Y', 1)]), [Compound("is", [Var('Y', 1), Compound('+', [Var('X', 0), Num(10)])])])
_KB.add_clause(Compound('test_identity', [Var('X', 0)]), [Compound('unit', [Var('X', 0), Var('M', 1)]), Compound('bind', [Var('M', 1), Atom('add_ten'), Var('R1', 2)]), Compound('add_ten', [Var('X', 0), Var('R2', 3)]), Compound('=:=', [Var('R1', 2), Var('R2', 3)]), Compound('write', [Atom('Identity verified for ')]), Compound('write', [Var('X', 0)]), Atom('nl')])
print_solutions(solve([Compound('test_identity', [Num(5)])], {}, _KB), free_vars=[])
print_solutions(solve([Compound('test_identity', [Num(10)])], {}, _KB), free_vars=[])
print_solutions(solve([Compound('test_identity', [Num(0)])], {}, _KB), free_vars=[])
