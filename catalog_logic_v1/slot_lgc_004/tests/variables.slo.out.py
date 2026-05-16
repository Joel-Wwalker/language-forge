# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_004.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_004.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


print_solutions(solve([Compound('=', [Var('User_Id', 0), Num(1974)]), Compound('=', [Var('Port', 1), Num(23)]), Compound('=', [Var('Minutes', 2), Num(45)]), Compound('write', [Var('User_Id', 0)]), Atom('nl'), Compound('write', [Var('Port', 1)]), Atom('nl'), Compound('write', [Var('Minutes', 2)]), Atom('nl')], {}, _KB), free_vars=[Var('User_Id', 0), Var('Port', 1), Var('Minutes', 2)])
