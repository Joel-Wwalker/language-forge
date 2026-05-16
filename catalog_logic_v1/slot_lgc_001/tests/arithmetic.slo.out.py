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


_KB.add_clause(Compound('theorem', [Atom('addition'), Var('R', 0)]), [Compound("is", [Var('R', 0), Compound('+', [Num(15), Num(27)])])])
_KB.add_clause(Compound('theorem', [Atom('multiplication'), Var('R', 0)]), [Compound("is", [Var('R', 0), Compound('*', [Num(8), Num(7)])])])
_KB.add_clause(Compound('theorem', [Atom('division'), Var('R', 0)]), [Compound("is", [Var('R', 0), Compound('//', [Num(100), Num(3)])])])
print_solutions(solve([Compound('theorem', [Atom('addition'), Var('A', 0)]), Compound('write', [Var('A', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('A', 0)])
print_solutions(solve([Compound('theorem', [Atom('multiplication'), Var('M', 0)]), Compound('write', [Var('M', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('M', 0)])
print_solutions(solve([Compound('theorem', [Atom('division'), Var('D', 0)]), Compound('write', [Var('D', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('D', 0)])
