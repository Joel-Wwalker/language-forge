"""forthlang lexer view. Forth tokenization is context-sensitive
(see parser._tokenize). This module exposes a thin `tokenize` API
for tooling + debugging."""
from __future__ import annotations

from .parser import _tokenize


def tokenize(src: str) -> list:
    """Yield (kind, value, line) tokens. Kinds: NUM, FLOAT, STRPUSH,
    STRPRINT, NAME, COLON, SEMI, IF, ELSE, THEN, BEGIN, UNTIL, AGAIN,
    WHILE, REPEAT, DO, LOOP, VARIABLE, CONSTANT."""
    return _tokenize(src)


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    for tok in tokenize(text):
        print(f"{tok[0]:<10} {tok[1]!r}  (line {tok[2]})")
