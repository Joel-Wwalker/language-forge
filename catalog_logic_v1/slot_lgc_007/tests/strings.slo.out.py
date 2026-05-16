# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_007.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_007.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


print_solutions(solve([Compound('write', [Atom('forall a. a -> a')]), Atom('nl')], {}, _KB), free_vars=[])
print_solutions(solve([Compound('write', [Compound('upper', [Atom('monad')])]), Atom('nl')], {}, _KB), free_vars=[])
print_solutions(solve([Compound('write', [Compound('lower', [Atom('FUNCTOR')])]), Atom('nl')], {}, _KB), free_vars=[])
print_solutions(solve([Compound('write', [Compound('replace', [Atom('alpha -> beta'), Atom('->'), Atom('=>')])]), Atom('nl')], {}, _KB), free_vars=[])
