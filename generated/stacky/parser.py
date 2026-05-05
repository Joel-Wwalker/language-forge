"""forthlang parser.

Forth tokenization is context-sensitive in three places:
  - `." text"` is print-this-string. The `."` is a single token; the
    text runs until the next `"`.
  - `s" text"` pushes a string literal onto the stack. Same shape.
  - `( ... )` is a paren comment. Spans tokens until the closing `)`.

Lark's lexer doesn't handle these naturally, so we tokenize by hand.
The parser then builds a small structural AST: a flat list of items
where colon-definitions, if/else/then, begin/until, and do/loop are
represented as nested dicts. Codegen walks the AST top-down.

We intentionally use plain dicts (not Lark Tree) because:
  1. Forth's "AST" is mostly linear; nesting only happens at colon
     definitions and control structures.
  2. Plain dicts are easy to inspect in tests + tooling.
  3. The verifier/mechanical_translator don't introspect parser output.
"""
from __future__ import annotations

import re
from typing import Any


class ParseError(Exception):
    pass


def _tokenize(src: str) -> list[tuple[str, Any, int]]:
    """Yield (kind, value, line) tokens.

    Kinds: NUM, FLOAT, STRPUSH, STRPRINT, NAME, COLON, SEMI, IF, ELSE,
           THEN, BEGIN, UNTIL, AGAIN, WHILE, REPEAT, DO, LOOP,
           VARIABLE, CONSTANT.
    """
    tokens = []
    i = 0
    line = 1
    n = len(src)
    while i < n:
        ch = src[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch.isspace():
            i += 1
            continue
        # Line comment: \ <text> until newline. Forth requires whitespace
        # AFTER the backslash; lone `\` at EOL is also valid.
        if ch == "\\" and (i + 1 >= n or src[i + 1].isspace()):
            j = src.find("\n", i)
            if j == -1:
                break
            i = j
            continue
        # Paren comment: `( ... )` (must be a separate token, i.e. surrounded
        # by whitespace on both sides). Inside the parens we span any chars
        # until the matching `)`. This doubles as Forth stack-effect notation.
        if ch == "(" and (i + 1 < n and src[i + 1].isspace()):
            j = src.find(")", i)
            if j == -1:
                raise ParseError(f"line {line}: unterminated `(` comment")
            line += src[i:j].count("\n")
            i = j + 1
            continue
        # `." string"` print-string. Keyword is `."` followed by ONE space
        # delimiter then text until matching `"`. The delimiter space is
        # NOT part of the string per Forth tradition.
        if ch == "." and i + 1 < n and src[i + 1] == '"':
            # Skip the optional single space after `."` (Forth delimiter).
            start = i + 2
            if start < n and src[start] == " ":
                start += 1
            j = src.find('"', start)
            if j == -1:
                raise ParseError(f"line {line}: unterminated `.\"` literal")
            text = src[start:j]
            line += text.count("\n")
            tokens.append(("STRPRINT", text, line))
            i = j + 1
            continue
        # `s" string"` push-string. Same delimiter rule as `." `.
        if ch == "s" and i + 1 < n and src[i + 1] == '"':
            start = i + 2
            if start < n and src[start] == " ":
                start += 1
            j = src.find('"', start)
            if j == -1:
                raise ParseError(f"line {line}: unterminated `s\"` literal")
            text = src[start:j]
            line += text.count("\n")
            tokens.append(("STRPUSH", text, line))
            i = j + 1
            continue
        # Otherwise: read up to next whitespace as a single token.
        j = i
        while j < n and not src[j].isspace():
            j += 1
        word = src[i:j]
        i = j
        # Classify
        kind = _classify(word)
        if kind == "NUM":
            tokens.append(("NUM", int(word), line))
        elif kind == "FLOAT":
            tokens.append(("FLOAT", float(word), line))
        elif kind in {"COLON", "SEMI", "IF", "ELSE", "THEN",
                      "BEGIN", "UNTIL", "AGAIN", "WHILE", "REPEAT",
                      "DO", "LOOP", "VARIABLE", "CONSTANT"}:
            tokens.append((kind, word, line))
        else:
            tokens.append(("NAME", word, line))
    return tokens


_NUM_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")

_KEYWORDS = {
    ":": "COLON", ";": "SEMI",
    "if": "IF", "else": "ELSE", "then": "THEN",
    "begin": "BEGIN", "until": "UNTIL", "again": "AGAIN",
    "while": "WHILE", "repeat": "REPEAT",
    "do": "DO", "loop": "LOOP",
    "variable": "VARIABLE", "constant": "CONSTANT",
}


def _classify(word: str) -> str:
    if word in _KEYWORDS:
        return _KEYWORDS[word]
    if _NUM_RE.match(word):
        return "NUM"
    if _FLOAT_RE.match(word):
        return "FLOAT"
    return "NAME"


def parse(src: str) -> list[dict]:
    """Parse forthlang source into a flat list of forms.

    Forms have a `kind` field plus type-specific extras. Codegen
    dispatches by kind.

    Example AST (program: `: square dup * ; 7 square .`):
      [
        {"kind": "colon_def", "name": "square", "body": [
            {"kind": "name", "value": "dup"},
            {"kind": "name", "value": "*"},
        ]},
        {"kind": "num", "value": 7},
        {"kind": "name", "value": "square"},
        {"kind": "name", "value": "."},
      ]
    """
    tokens = _tokenize(src)
    pos = [0]   # mutable index for the recursive parser

    def peek() -> tuple[str, Any, int] | None:
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def consume() -> tuple[str, Any, int]:
        t = tokens[pos[0]]
        pos[0] += 1
        return t

    def parse_seq(end_kinds: set[str]) -> tuple[list[dict], str]:
        """Parse forms until we hit one of `end_kinds`. Returns (body, terminator_kind)."""
        body: list[dict] = []
        while pos[0] < len(tokens):
            t = peek()
            if t is None:
                break
            if t[0] in end_kinds:
                consume()
                return body, t[0]
            body.append(parse_form())
        return body, ""

    def parse_form() -> dict:
        kind, value, line = consume()
        if kind == "COLON":
            t = peek()
            if t is None or t[0] != "NAME":
                raise ParseError(f"line {line}: `:` must be followed by a name")
            consume()
            name = t[1]
            inner_body, term = parse_seq({"SEMI"})
            if term != "SEMI":
                raise ParseError(f"line {line}: `: {name}` not terminated by `;`")
            return {"kind": "colon_def", "name": name, "body": inner_body, "line": line}
        if kind == "IF":
            then_body, term = parse_seq({"ELSE", "THEN"})
            else_body: list[dict] = []
            if term == "ELSE":
                else_body, term = parse_seq({"THEN"})
            if term != "THEN":
                raise ParseError(f"line {line}: `if` not terminated by `then`")
            return {"kind": "if", "then_body": then_body, "else_body": else_body, "line": line}
        if kind == "BEGIN":
            inner, term = parse_seq({"UNTIL", "AGAIN", "REPEAT"})
            if term == "UNTIL":
                return {"kind": "begin_until", "body": inner, "line": line}
            if term == "AGAIN":
                return {"kind": "begin_again", "body": inner, "line": line}
            raise ParseError(f"line {line}: `begin` must be closed by `until`/`again`")
        if kind == "DO":
            inner, term = parse_seq({"LOOP"})
            if term != "LOOP":
                raise ParseError(f"line {line}: `do` not terminated by `loop`")
            return {"kind": "do_loop", "body": inner, "line": line}
        if kind == "VARIABLE":
            t = peek()
            if t is None or t[0] != "NAME":
                raise ParseError(f"line {line}: `variable` must be followed by a name")
            consume()
            return {"kind": "variable_decl", "name": t[1], "line": line}
        if kind == "CONSTANT":
            t = peek()
            if t is None or t[0] != "NAME":
                raise ParseError(f"line {line}: `constant` must be followed by a name")
            consume()
            return {"kind": "constant_decl", "name": t[1], "line": line}
        if kind == "NUM":
            return {"kind": "num", "value": value, "line": line}
        if kind == "FLOAT":
            return {"kind": "float", "value": value, "line": line}
        if kind == "STRPUSH":
            return {"kind": "strpush", "value": value, "line": line}
        if kind == "STRPRINT":
            return {"kind": "strprint", "value": value, "line": line}
        if kind == "NAME":
            return {"kind": "name", "value": value, "line": line}
        # Stray closer like `;`, `then`, `loop` outside a structure.
        raise ParseError(f"line {line}: unexpected `{value}`")

    program: list[dict] = []
    while pos[0] < len(tokens):
        program.append(parse_form())
    return program


# Lark-shaped GRAMMAR string for documentation / parser-prompt parity.
# This is INFORMATIONAL ONLY - the actual parser is hand-rolled above
# because Forth's `."`/`s"`/`(` lexing is context-sensitive and Lark's
# lexer would fight us on it. The string serves as a reference for
# anyone reading or extending the dialect.
GRAMMAR = r"""
// forthlang grammar (informational; the actual parser is hand-rolled).
//
// start: form*
// form:  colon_def | if_form | begin_form | do_form
//      | variable_decl | constant_decl
//      | NUM | FLOAT | STRPUSH | STRPRINT | NAME
// colon_def:    ":" NAME form* ";"
// if_form:      "if" form* ("else" form*)? "then"
// begin_form:   "begin" form* ("until" | "again")
// do_form:      "do" form* "loop"
// variable_decl: "variable" NAME
// constant_decl: "constant" NAME
//
// Comments: "(" ... ")"  and  "\\" /[^\n]*/
// String literals:
//   STRPRINT: /\.\"\s[^"]*\"/    (e.g. ." Hello, World!")
//   STRPUSH:  /s\"\s[^"]*\"/     (e.g. s" raw")
"""


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    import json
    print(json.dumps(parse(text), indent=2))
