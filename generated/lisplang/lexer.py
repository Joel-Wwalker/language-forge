"""lisplang lexer view. The Lark grammar in parser.py handles tokenization;
this module exposes a `tokenize` API for debugging + component-level tests."""
from __future__ import annotations

from lark import Lark
from .parser import GRAMMAR


_LEXER_PARSER = Lark(GRAMMAR, parser="earley", start="start")


def tokenize(src: str):
    return list(_LEXER_PARSER.lex(src))


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    for tok in tokenize(text):
        print(f"{tok.type:<20} {tok!r}")
