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


_KB.add_clause(Atom('demonstrate_binding'), [Compound('=', [Var('Valor', 0), Num(42)]), Compound("is", [Var('Computatio', 1), Compound('+', [Var('Valor', 0), Num(8)])]), Compound('write', [Var('Valor', 0)]), Atom('nl'), Compound('write', [Var('Computatio', 1)]), Atom('nl')])
print_solutions(solve([Atom('demonstrate_binding')], {}, _KB), free_vars=[])
