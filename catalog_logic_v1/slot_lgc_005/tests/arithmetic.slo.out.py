# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_005.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_005.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


print_solutions(solve([Compound("is", [Var('Act_one', 0), Compound('+', [Num(45), Num(30)])]), Compound('write', [Var('Act_one', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Act_one', 0)])
print_solutions(solve([Compound("is", [Var('Intermission', 0), Compound('-', [Num(90), Num(75)])]), Compound('write', [Var('Intermission', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Intermission', 0)])
print_solutions(solve([Compound("is", [Var('Speeches', 0), Compound('*', [Num(3), Num(4)])]), Compound('write', [Var('Speeches', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Speeches', 0)])
print_solutions(solve([Compound("is", [Var('Scenes', 0), Compound('/', [Num(21), Num(3)])]), Compound('write', [Var('Scenes', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Scenes', 0)])
print_solutions(solve([Compound("is", [Var('Remaining', 0), Compound('mod', [Num(17), Num(5)])]), Compound('write', [Var('Remaining', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Remaining', 0)])
