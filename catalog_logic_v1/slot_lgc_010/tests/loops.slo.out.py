# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_010.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_010.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('summa_ad', [Num(0), Num(0)]), [])
_KB.add_clause(Compound('summa_ad', [Var('N', 0), Var('S', 1)]), [Compound('>', [Var('N', 0), Num(0)]), Compound("is", [Var('N1', 2), Compound('-', [Var('N', 0), Num(1)])]), Compound('summa_ad', [Var('N1', 2), Var('S1', 3)]), Compound("is", [Var('S', 1), Compound('+', [Var('S1', 3), Var('N', 0)])])])
_KB.add_clause(Atom('demonstrate_summam'), [Compound('summa_ad', [Num(10), Var('Resultatum', 0)]), Compound('write', [Var('Resultatum', 0)]), Atom('nl')])
print_solutions(solve([Atom('demonstrate_summam')], {}, _KB), free_vars=[])
