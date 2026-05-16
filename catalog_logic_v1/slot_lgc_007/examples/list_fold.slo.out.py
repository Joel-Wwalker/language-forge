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


_KB.add_clause(Compound('fold_left', [NIL, Var('Acc', 0), Var('Pred', 1), Var('Acc', 0)]), [])
_KB.add_clause(Compound('fold_left', [make_partial_list([Var('H', 0)], Var('T', 1)), Var('Acc', 2), Var('Pred', 3), Var('Result', 4)]), [Compound('call', [Var('Pred', 3), Var('Acc', 2), Var('H', 0), Var('NewAcc', 5)]), Compound('fold_left', [Var('T', 1), Var('NewAcc', 5), Var('Pred', 3), Var('Result', 4)])])
_KB.add_clause(Compound('add_nums', [Var('Acc', 0), Var('X', 1), Var('Sum', 2)]), [Compound("is", [Var('Sum', 2), Compound('+', [Var('Acc', 0), Var('X', 1)])])])
_KB.add_clause(Compound('mult_nums', [Var('Acc', 0), Var('X', 1), Var('Prod', 2)]), [Compound("is", [Var('Prod', 2), Compound('*', [Var('Acc', 0), Var('X', 1)])])])
print_solutions(solve([Compound('fold_left', [make_list([Num(1), Num(2), Num(3), Num(4), Num(5)]), Num(0), Atom('add_nums'), Var('Sum', 0)]), Compound('write', [Atom('Sum: ')]), Compound('write', [Var('Sum', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Sum', 0)])
print_solutions(solve([Compound('fold_left', [make_list([Num(1), Num(2), Num(3), Num(4)]), Num(1), Atom('mult_nums'), Var('Prod', 0)]), Compound('write', [Atom('Product: ')]), Compound('write', [Var('Prod', 0)]), Atom('nl')], {}, _KB), free_vars=[Var('Prod', 0)])
