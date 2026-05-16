# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_009.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_009.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('comfort', [Var('Temp', 0), Atom('cozy')]), [Compound('>=', [Var('Temp', 0), Num(68)]), Compound('=<', [Var('Temp', 0), Num(72)])])
_KB.add_clause(Compound('comfort', [Var('Temp', 0), Atom('chilly')]), [Compound('<', [Var('Temp', 0), Num(68)])])
_KB.add_clause(Compound('comfort', [Var('Temp', 0), Atom('warm')]), [Compound('>', [Var('Temp', 0), Num(72)])])
print_solutions(solve([Compound('comfort', [Num(70), Var('Level', 0)]), Compound('write', [Var('Level', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Level', 0)])
print_solutions(solve([Compound('comfort', [Num(65), Var('Level', 0)]), Compound('write', [Var('Level', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Level', 0)])
print_solutions(solve([Compound('comfort', [Num(75), Var('Level', 0)]), Compound('write', [Var('Level', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Level', 0)])
