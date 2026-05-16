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


_KB.add_clause(Compound('fibonacci', [Num(0), Num(0)]), [])
_KB.add_clause(Compound('fibonacci', [Num(1), Num(1)]), [])
_KB.add_clause(Compound('fibonacci', [Var('N', 0), Var('F', 1)]), [Compound('>', [Var('N', 0), Num(1)]), Compound("is", [Var('N1', 2), Compound('-', [Var('N', 0), Num(1)])]), Compound("is", [Var('N2', 3), Compound('-', [Var('N', 0), Num(2)])]), Compound('fibonacci', [Var('N1', 2), Var('F1', 4)]), Compound('fibonacci', [Var('N2', 3), Var('F2', 5)]), Compound("is", [Var('F', 1), Compound('+', [Var('F1', 4), Var('F2', 5)])])])
print_solutions(solve([Compound('fibonacci', [Num(8), Var('Result', 0)]), Compound('write', [Var('Result', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Result', 0)])
