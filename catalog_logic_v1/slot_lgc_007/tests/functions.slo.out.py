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


_KB.add_clause(Compound('arity', [Atom('unit'), Num(0)]), [])
_KB.add_clause(Compound('arity', [Atom('int'), Num(0)]), [])
_KB.add_clause(Compound('arity', [Atom('bool'), Num(0)]), [])
_KB.add_clause(Compound('arrow_arity', [Var('A', 0), Var('B', 1), Var('N', 2)]), [Compound('arity', [Var('A', 0), Var('X', 3)]), Compound('arity', [Var('B', 1), Var('Y', 4)]), Compound("is", [Var('N', 2), Compound('+', [Compound('+', [Var('X', 3), Var('Y', 4)]), Num(1)])])])
print_solutions(solve([Compound('arrow_arity', [Atom('int'), Atom('bool'), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('arity', [Atom('int'), Var('N', 0)]), Compound('write', [Var('N', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('N', 0)])
