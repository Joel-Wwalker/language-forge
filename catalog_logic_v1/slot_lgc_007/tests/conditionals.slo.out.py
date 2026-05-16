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


_KB.add_clause(Compound('infer_type', [Num(0), Atom('int')]), [])
_KB.add_clause(Compound('infer_type', [Var('N', 0), Atom('int')]), [Compound('>', [Var('N', 0), Num(0)])])
_KB.add_clause(Compound('infer_type', [Atom('true'), Atom('bool')]), [])
_KB.add_clause(Compound('infer_type', [Atom('false'), Atom('bool')]), [])
print_solutions(solve([Compound('infer_type', [Num(42), Var('T', 0)]), Compound('write', [Var('T', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('T', 0)])
print_solutions(solve([Compound('infer_type', [Atom('true'), Var('U', 0)]), Compound('write', [Var('U', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('U', 0)])
print_solutions(solve([Compound('infer_type', [Num(0), Var('V', 0)]), Compound('write', [Var('V', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('V', 0)])
