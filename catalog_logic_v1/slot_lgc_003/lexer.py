"""Lexer for slot_lgc_003: wraps Lark's lexer."""
from lark import Lark
from .parser import GRAMMAR

_LEXER = Lark(GRAMMAR, parser="lalr", start="start")

def tokenize(src):
    return list(_LEXER.lex(src))

if __name__ == "__main__":
    import sys
    src = open(sys.argv[1], "r", encoding="utf-8").read()
    for tok in tokenize(src):
        print(f"{tok.type:<20} {tok!r}")
