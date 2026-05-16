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


_KB.add_clause(Compound('applica_bis', [Var('Praedicatum', 0), Var('X', 1), Var('Z', 2)]), [Compound('call', [Var('Praedicatum', 0), Var('X', 1), Var('Y', 3)]), Compound('call', [Var('Praedicatum', 0), Var('Y', 3), Var('Z', 2)])])
_KB.add_clause(Compound('duplica', [Var('X', 0), Var('Y', 1)]), [Compound("is", [Var('Y', 1), Compound('*', [Var('X', 0), Num(2)])])])
_KB.add_clause(Atom('test_ordinis_superioris'), [Compound('applica_bis', [Atom('duplica'), Num(3), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')])
print_solutions(solve([Atom('test_ordinis_superioris')], {}, _KB), free_vars=[])
