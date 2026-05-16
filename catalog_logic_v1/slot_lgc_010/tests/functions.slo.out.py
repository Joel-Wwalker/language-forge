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


_KB.add_clause(Compound('factorialis', [Num(0), Num(1)]), [])
_KB.add_clause(Compound('factorialis', [Var('N', 0), Var('F', 1)]), [Compound('>', [Var('N', 0), Num(0)]), Compound("is", [Var('N1', 2), Compound('-', [Var('N', 0), Num(1)])]), Compound('factorialis', [Var('N1', 2), Var('F1', 3)]), Compound("is", [Var('F', 1), Compound('*', [Var('N', 0), Var('F1', 3)])])])
_KB.add_clause(Atom('test_factorialis'), [Compound('factorialis', [Num(6), Var('Res', 0)]), Compound('write', [Var('Res', 0)]), Atom('nl')])
print_solutions(solve([Atom('test_factorialis')], {}, _KB), free_vars=[])
