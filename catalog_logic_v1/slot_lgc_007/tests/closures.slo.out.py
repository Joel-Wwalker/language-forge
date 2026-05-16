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


_KB.add_clause(Compound('apply_twice', [Var('Pred', 0), Var('X', 1), Var('Z', 2)]), [Compound('call', [Var('Pred', 0), Var('X', 1), Var('Y', 3)]), Compound('call', [Var('Pred', 0), Var('Y', 3), Var('Z', 2)])])
_KB.add_clause(Compound('succ', [Var('N', 0), Var('M', 1)]), [Compound("is", [Var('M', 1), Compound('+', [Var('N', 0), Num(1)])])])
print_solutions(solve([Compound('apply_twice', [Atom('succ'), Num(5), Var('Result', 0)]), Compound('write', [Var('Result', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Result', 0)])
