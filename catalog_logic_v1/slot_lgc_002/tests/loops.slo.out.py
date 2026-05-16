# --- prologlang generated python ---
import sys
sys.setrecursionlimit(10000)

from slot_lgc_002.runtime import (
    Var, Atom, Num, Compound,
    KnowledgeBase, solve, walk,
    NIL, make_list, make_partial_list,
    print_solutions, write_term, write_nl,
)
from slot_lgc_002.stdlib import register_builtins

_KB = KnowledgeBase()
register_builtins(_KB)


_KB.add_clause(Compound('verify_section', [Num(0)]), [Compound('write', [Num(0)]), Atom('nl')])
_KB.add_clause(Compound('verify_section', [Var('N', 0)]), [Compound('>', [Var('N', 0), Num(0)]), Compound('write', [Var('N', 0)]), Atom('nl'), Compound("is", [Var('N1', 1), Compound('-', [Var('N', 0), Num(1)])]), Compound('verify_section', [Var('N1', 1)])])
print_solutions(solve([Compound('verify_section', [Num(5)])], {}, _KB), free_vars=[])
