"""Toylang parser (Lark grammar + `parse` entrypoint)."""
from __future__ import annotations

from lark import Lark, Tree


# Toylang grammar: c_like syntax, dynamic typing.
# Statements end with ';'. Blocks use braces. Comments: //...
#
# Lark resolves keyword/identifier collisions automatically: anonymous string
# literals in rules outrank regex-based terminals like NAME. Booleans/null are
# given an explicit priority so they cannot be misread as identifiers.
GRAMMAR = r"""
start: stmt*

?stmt: var_decl
     | func_def
     | if_stmt
     | while_stmt
     | return_stmt
     | block
     | expr_stmt

var_decl:    "var" NAME "=" expr ";"
func_def:    "func" NAME "(" params? ")" block
params:      NAME ("," NAME)*
if_stmt:     "if" "(" expr ")" block else_clause?
else_clause: "else" (if_stmt | block)
while_stmt:  "while" "(" expr ")" block
return_stmt: "return" expr? ";"
block:       "{" stmt* "}"
expr_stmt:   expr ";"

?expr:       assign
assign:      NAME "=" assign      -> assign_op
           | logical_or            -> passthru

logical_or:  logical_and (OR_OP logical_and)*
OR_OP:       "||"
logical_and: equality (AND_OP equality)*
AND_OP:      "&&"
equality:    comparison (EQ_OP comparison)*
EQ_OP:       "==" | "!="
comparison:  term (CMP_OP term)*
CMP_OP:      "<=" | ">=" | "<" | ">"
term:        factor (TERM_OP factor)*
TERM_OP:     "+" | "-"
factor:      unary (FACTOR_OP unary)*
FACTOR_OP:   "*" | "/" | "%"
unary:       UNARY_OP unary
           | call
UNARY_OP:    "!" | "-"
call:        primary trailer*
trailer:     "(" args? ")"
args:        expr ("," expr)*

primary:     INT       -> int_lit
           | FLOAT     -> float_lit
           | STRING    -> string_lit
           | TRUE      -> true_lit
           | FALSE     -> false_lit
           | NULL      -> null_lit
           | NAME      -> name_ref
           | "(" expr ")" -> paren

TRUE.2:  "true"
FALSE.2: "false"
NULL.2:  "null"

%import common.CNAME -> NAME
%import common.INT
%import common.FLOAT
%import common.ESCAPED_STRING -> STRING
%import common.WS
%ignore WS

LINE_COMMENT: "//" /[^\n]*/
BLOCK_COMMENT: "/*" /(.|\n)*?/ "*/"
%ignore LINE_COMMENT
%ignore BLOCK_COMMENT
"""


_PARSER = Lark(GRAMMAR, parser="lalr", start="start", propagate_positions=True)


def parse(src: str) -> Tree:
    """Parse toylang source and return a Lark Tree."""
    return _PARSER.parse(src)


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    print(parse(text).pretty())
