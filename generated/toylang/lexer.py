"""Toylang lexer.

Toylang is c_like + dynamic + host_gc. We use Lark for both lexing and parsing
in the MVP; this module exposes a thin `tokenize` view over Lark's lexer so the
'lexer' component is a real, addressable artifact (rather than a no-op).
"""
from __future__ import annotations

from lark import Lark
from .parser import GRAMMAR


_LEXER_PARSER = Lark(GRAMMAR, parser="lalr", start="start")


def tokenize(src: str):
    """Yield Lark Tokens for `src`. Useful for debugging and component tests."""
    return list(_LEXER_PARSER.lex(src))


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    for tok in tokenize(text):
        print(f"{tok.type:<20} {tok!r}")
