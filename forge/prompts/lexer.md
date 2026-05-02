# Lexer prompt

Generate `lexer.py` for the target language.

## Resolved spec

```json
{{SPEC}}
```

## Requirements

- Expose `tokenize(src: str) -> list` returning Lark `Token` objects.
- Internally, build a Lark `Lark(GRAMMAR, parser="lalr", start="start")` and call `.lex(src)`.
- The grammar string itself lives in `parser.py`; import it with `from .parser import GRAMMAR`.
- Add a `if __name__ == "__main__":` debug entrypoint that takes a filename argv and prints `<TYPE> <value>` lines.

## Output format

Return ONLY a single fenced ```python code block with the full file contents. No prose. No partial code.

## Skeleton

```python
"""Lexer for <lang_name>: wraps Lark's lexer."""
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
```
