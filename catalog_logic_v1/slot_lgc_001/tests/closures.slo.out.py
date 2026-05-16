# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_001.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_001.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('compose', [Var('P', 0), Var('X', 1), Var('R', 2)]), [Compound('call', [Var('P', 0), Var('X', 1), Var('T', 3)]), Compound('call', [Var('P', 0), Var('T', 3), Var('R', 2)])])
_KB.add_clause(Compound('successor', [Var('X', 0), Var('R', 1)]), [Compound("is", [Var('R', 1), Compound('+', [Var('X', 0), Num(1)])])])
print_solutions(solve([Compound('compose', [Atom('successor'), Num(10), Var('Result', 0)]), Compound('write', [Var('Result', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Result', 0)])
