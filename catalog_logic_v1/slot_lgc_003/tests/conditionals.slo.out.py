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


_KB.add_clause(Compound('classify', [Var('X', 0), Atom('positive')]), [Compound('>', [Var('X', 0), Num(0)])])
_KB.add_clause(Compound('classify', [Var('X', 0), Atom('zero')]), [Compound('=:=', [Var('X', 0), Num(0)])])
_KB.add_clause(Compound('classify', [Var('X', 0), Atom('negative')]), [Compound('<', [Var('X', 0), Num(0)])])
print_solutions(solve([Compound('classify', [Num(42), Var('C1', 0)]), Compound('write', [Var('C1', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('C1', 0)])
print_solutions(solve([Compound('classify', [Num(0), Var('C2', 0)]), Compound('write', [Var('C2', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('C2', 0)])
print_solutions(solve([Compound('classify', [Num(-7), Var('C3', 0)]), Compound('write', [Var('C3', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('C3', 0)])
