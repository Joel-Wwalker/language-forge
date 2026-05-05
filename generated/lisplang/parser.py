"""lisplang parser. Lark grammar + `parse` entrypoint.

s_expression syntax: every form is `(operator operand operand ...)`.
The grammar has no precedence layer because there is no infix syntax.
Operators (`+`, `<`, `and`, `not`, ...) are matched as `NAME` tokens
that the codegen pattern-matches on the head of `call` nodes.

Special forms are explicit grammar rules (`var_decl`, `func_def`,
`if_stmt`, `while_stmt`, `return_stmt`, `let_stmt`, `do_stmt`,
`when_stmt`, `set_stmt`, `fn_expr`) so codegen can dispatch by
node.data without sniffing keyword strings inside generic `call`
nodes. This makes the codegen far simpler and more robust.
"""
from __future__ import annotations

from lark import Lark, Tree


GRAMMAR = r"""
start: form*

?form: var_decl
     | func_def
     | if_stmt
     | while_stmt
     | when_stmt
     | let_stmt
     | do_stmt
     | set_stmt
     | return_stmt
     | expr_stmt

var_decl:    "(" "def"     NAME expr ")"
func_def:    "(" "defn"    NAME "(" params ")" form+ ")"
params:      (NAME)*
// if_stmt arms are FORMS, not just expressions, so `(return X)`,
// `(set! ...)`, nested `(while ...)` etc. are valid arms. The mechanical
// translator from c_like emits `(if cond (return X) nil)` for c_like
// `if (cond) { return X; }` patterns; that requires `return_stmt` as
// a valid arm.
if_stmt:     "(" "if"      expr form form ")"
while_stmt:  "(" "while"   expr form+ ")"
when_stmt:   "(" "when"    expr form+ ")"
let_stmt:    "(" "let"     "(" binding+ ")" form+ ")"
binding:     "(" NAME expr ")"
do_stmt:     "(" "do"      form+ ")"
set_stmt:    "(" "set!"    NAME expr ")"
return_stmt: "(" "return"  expr? ")"
expr_stmt:   expr

?expr: int_lit
     | float_lit
     | string_lit
     | true_lit
     | false_lit
     | null_lit
     | name_ref
     | fn_expr
     | if_expr
     | do_expr
     | when_expr
     | let_expr
     | call

// Special forms in expression position. Distinct from their statement
// counterparts so codegen can emit Python expression syntax (ternary,
// tuple-subscript, etc.) instead of statement blocks.
fn_expr:   "(" "fn"   "(" params ")" form+ ")"
if_expr:   "(" "if"   expr expr expr ")"
do_expr:   "(" "do"   form+ ")"
when_expr: "(" "when" expr form+ ")"
let_expr:  "(" "let"  "(" binding+ ")" form+ ")"

call:    "(" call_head args ")"
call_head: NAME | OP_NAME
args:    (expr)*

int_lit:    INT
float_lit:  FLOAT
string_lit: STRING
true_lit:   TRUE
false_lit:  FALSE
null_lit:   NULL
name_ref:   NAME

TRUE.2:  "true"
FALSE.2: "false"
NULL.2:  "nil"

INT:    /-?[0-9]+/
FLOAT:  /-?[0-9]+\.[0-9]+/

OP_NAME: /[+\-*\/=<>!%]+/

NAME: /[a-zA-Z_][a-zA-Z0-9_!?\-]*/

%import common.ESCAPED_STRING -> STRING
%import common.WS
%ignore WS

LINE_COMMENT: ";" /[^\n]*/
%ignore LINE_COMMENT

// Block comments: #| ... |#  (no nesting; LL(1)-friendly)
BLOCK_COMMENT: "#|" /(.|\n)*?/ "|#"
%ignore BLOCK_COMMENT
"""


# Note on parser choice: `earley` is more permissive than `lalr` and
# accepts the ambiguity-prone pattern of `(if cond t e)` matching both
# `if_stmt` and `if_expr`. Earley is slower in theory; in practice for
# Lisp source it's plenty fast (microseconds for typical programs).
# NOTE: Lark's `cache=True` is LALR-only. Lisplang uses earley because
# of the if_stmt vs if_expr ambiguity (same form, different parse goals
# depending on position). Earley grammars compile fast enough that the
# cache miss is negligible for typical Lisp source.
_PARSER = Lark(GRAMMAR, parser="earley", start="start",
               propagate_positions=True, ambiguity="resolve")


def parse(src: str) -> Tree:
    """Parse lisplang source and return a Lark Tree."""
    return _PARSER.parse(src)


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    print(parse(text).pretty())
