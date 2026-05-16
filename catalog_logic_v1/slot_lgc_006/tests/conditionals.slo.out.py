# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_006.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_006.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('classify', [Var('N', 0), Atom('negative')]), [Compound('<', [Var('N', 0), Num(0)])])
_KB.add_clause(Compound('classify', [Num(0), Atom('zero')]), [])
_KB.add_clause(Compound('classify', [Var('N', 0), Atom('positive')]), [Compound('>', [Var('N', 0), Num(0)])])
print_solutions(solve([Compound('classify', [Num(-3), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('classify', [Num(0), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
print_solutions(solve([Compound('classify', [Num(5), Var('R', 0)]), Compound('write', [Var('R', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('R', 0)])
