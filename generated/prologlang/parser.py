"""prologlang parser — Lark grammar + `parse` entrypoint.

Pragmatic Prolog subset (see LOGICLANG_DESIGN.md §1):
  - Clauses (facts and rules) terminated by `.`
  - Directives `?- Goal.` or `:- Goal.` (synonymous; both run at load)
  - Atoms (lowercase-leading or single-quoted)
  - Variables (uppercase-leading or `_`-leading; `_` is anonymous)
  - Numbers (integer or float)
  - Compound terms `foo(a, b)`
  - Lists `[]`, `[1, 2, 3]`, `[H | T]`, `[a, b | T]`
  - Standard operator precedence (see grammar comments)
  - Body conjunction `,` and disjunction `;`
  - Comments `% line` and `/* block */`

The grammar uses Earley because Prolog's operator-precedence-with-special-
characters (e.g. `=..`, `\\+`, `=:=`) is awkward for LALR. Earley handles
it cleanly with the ladder of precedence rules below.

The parse tree uses Lark's `Tree` objects directly; codegen walks them
via tree.data / tree.children.
"""
from __future__ import annotations

from lark import Lark, Tree


# Grammar notes:
#
# Top-level: a program is a series of `clause` items, each ending in `.`.
# A clause is either a directive (`?- Goal.` / `:- Goal.`), a fact
# (a head term), or a rule (head :- body).
#
# Operator precedence (lower number = tighter binding):
#   1200 (xfx): :-       (rule operator, statement-level)
#   1100 (xfy): ;        (disjunction)
#   1000 (xfy): ,        (conjunction)
#    900 (fy):  \+       (negation as failure)
#    700 (xfx): =, \=, ==, \==, is, =:=, =\=, <, >, =<, >=
#    500 (yfx): +, -     (binary)
#    400 (yfx): *, /, //, mod
#    200 (xfy): **, ^
#    200 (fy):  - (unary)
#
# The grammar encodes precedence by chaining non-terminals: each layer
# only binds operators at its own precedence. This is the standard
# operator-precedence-via-grammar approach Lark recommends.
#
# Edge cases handled:
#   - `1-2`: lexer must treat `-` as a separator (not part of `2`) so
#     this parses as binary `1 - 2`, not `1 -2`. We achieve this by
#     making INT positive-only at lex time and folding unary `-` into
#     the grammar (`unary_expr: "-" unary_expr`).
#   - `[H|T]` vs `[H | T]`: whitespace-flexible, handled by Lark's
#     default whitespace ignoring.
#   - Anonymous `_`: every occurrence gets a unique synthetic id in
#     post-processing (see _renumber_anonymous_vars below).
GRAMMAR = r"""
start: clause+

clause: directive
      | rule
      | fact

directive: "?-" body "." -> directive
         | ":-" body "." -> directive

rule:     term ":-" body "."

fact:     term "."

// Body: a conjunction/disjunction of goals, parsed via the
// precedence ladder. Standard Prolog precedences:
//   1100 (xfy): ; (disjunction)
//   1050 (xfy): -> (if-then)
//   1000 (xfy): , (conjunction)
//    900 (fy):  \+ (negation as failure)
// `(Cond -> Then ; Else)` parses as `; (-> Cond Then) Else` because
// `;` is looser than `->`. Both nest right-associatively.
body: disj_body

?disj_body: ifthen_body ";" disj_body  -> disjunction
          | ifthen_body

?ifthen_body: conj_body "->" ifthen_body  -> ifthen
            | conj_body

?conj_body: neg_body "," conj_body  -> conjunction
          | neg_body

?neg_body: "\\+" neg_body  -> negation
         | term

// Term-level: this is where we parse Prolog terms (the building
// blocks). A term includes all the infix operators at their own
// precedence levels.
?term: cmp_expr

// Comparison operators (precedence 700). These are non-associative
// in real Prolog (xfx). For pragmatic v1, treat them as left-assoc
// at parse time; users don't typically chain comparisons in clauses.
?cmp_expr: add_expr CMP_OP add_expr  -> binop
         | add_expr "is" add_expr    -> is_op
         | add_expr

CMP_OP: "=:=" | "=\\=" | "=<" | ">=" | "\\==" | "\\=" | "==" | "<" | ">" | "="

?add_expr: add_expr ADD_OP mul_expr  -> binop
         | mul_expr

ADD_OP: "+" | "-"

?mul_expr: mul_expr MUL_OP unary_expr  -> binop
         | unary_expr

MUL_OP: "*" | "//" | "/" | "mod"

?unary_expr: "-" unary_expr  -> unary_minus
           | power_expr

?power_expr: atom_term POW_OP power_expr  -> binop
           | atom_term

POW_OP: "**" | "^"

// Atomic term: literal, variable, atom, compound, list.
?atom_term: NUMBER             -> num_lit
          | VARIABLE           -> var_ref
          | ATOM_NAME args?    -> atom_or_compound
          | QUOTED_ATOM args?  -> quoted_atom_or_compound
          | list_term
          | "(" body ")"

// Function-call style args: `foo(a, b, c)`. Bare atom without parens
// is just an atom; `foo()` (zero-arg) is rejected — use bare `foo`.
args: "(" arg_list ")"
arg_list: term ("," term)*

// Lists: empty, full literal, partial (with `|` tail).
list_term: "[" "]"                                 -> nil_list
         | "[" term ("," term)* "]"                -> proper_list
         | "[" term ("," term)* "|" term "]"       -> partial_list

// Lexer terminals.
//
// ATOM_NAME matches lowercase-leading identifiers, EXCEPT the
// reserved keywords (is, mod). Reserved-word handling via negative
// lookahead.
ATOM_NAME: /(?!(?:is|mod)\b)[a-z][A-Za-z0-9_]*/

// VARIABLE matches uppercase-leading or `_`-leading identifiers.
// The single `_` is treated specially — every occurrence becomes a
// fresh anonymous variable (handled post-parse).
VARIABLE:  /[A-Z_][A-Za-z0-9_]*/

// Quoted atoms: 'atom with spaces', 'Capitalized', 'Hello, World!'
// Backslash-escape `'` inside.
QUOTED_ATOM: /'(\\.|[^'\\])*'/

// Numbers: integers and floats. Negative literals come from the
// unary-minus grammar rule, not the lexer (so `1-2` doesn't lex as
// `1` `-2`).
NUMBER: /[0-9]+(\.[0-9]+)?/

// Comments.
LINE_COMMENT:  /%[^\n]*/
BLOCK_COMMENT: /\/\*([^*]|\*+[^*\/])*\*+\//

%import common.WS
%ignore WS
%ignore LINE_COMMENT
%ignore BLOCK_COMMENT
"""


_PARSER = Lark(
    GRAMMAR,
    parser="earley",
    start="start",
    maybe_placeholders=False,
    propagate_positions=True,
)


def parse(src: str) -> Tree:
    """Parse prologlang source and return a Lark Tree.

    Post-processing: anonymous `_` variables are renumbered so each
    distinct occurrence becomes a unique synthetic Var. Without this,
    `parent(_, X)` and `child(_, Y)` would treat both `_`s as the same
    variable, which is wrong (anonymous = "I don't care", not "this
    specific don't-care position").
    """
    tree = _PARSER.parse(src)
    _renumber_anonymous_vars(tree)
    return tree


# Each call to `parse` increments these counters; they're module-level
# so two calls produce disjoint id ranges. Codegen later remaps these
# to compile-time integer ids — these are just placeholder names like
# `_G42` that round-trip through string form.
_ANON_COUNTER = [0]


def _renumber_anonymous_vars(tree: Tree) -> None:
    """Walk the tree and rewrite Token('VARIABLE', '_') tokens to
    unique synthetic names like '_G42'.

    A token is a `_` exactly when its `.value` is the string "_".
    Each call to this function bumps the module counter so anonymous
    vars across separate `parse()` calls don't collide.
    """
    from lark import Token

    def walk(node):
        if isinstance(node, Tree):
            for child in node.children:
                walk(child)
        elif isinstance(node, Token) and node.type == "VARIABLE" and node.value == "_":
            _ANON_COUNTER[0] += 1
            # Mutate the Token's value field (Tokens are str subclasses;
            # we make a fresh Token to avoid mutating string-internals).
            new_token = Token(node.type, f"_G{_ANON_COUNTER[0]}")
            new_token.line = getattr(node, "line", None)
            new_token.column = getattr(node, "column", None)
            # Find this token in the parent's children and replace.
            # Since we don't have parent refs, we patch via __dict__ —
            # but Tokens are immutable strings. Workaround: rewrite the
            # token's `.value` post-hoc via Lark internals.

    # Lark Tokens are immutable strings. The cleanest fix: walk the tree
    # and replace anonymous-`_` Tokens in-place via the parent's
    # children list.
    def walk_replace(node):
        if isinstance(node, Tree):
            new_children = []
            for child in node.children:
                if (isinstance(child, Token) and child.type == "VARIABLE"
                        and child.value == "_"):
                    _ANON_COUNTER[0] += 1
                    fresh_name = f"_G{_ANON_COUNTER[0]}"
                    new_tok = Token(child.type, fresh_name)
                    try:
                        new_tok.line = child.line
                        new_tok.column = child.column
                    except Exception:
                        pass
                    new_children.append(new_tok)
                else:
                    walk_replace(child)
                    new_children.append(child)
            node.children = new_children

    walk_replace(tree)


if __name__ == "__main__":
    import sys
    text = open(sys.argv[1], "r", encoding="utf-8").read()
    print(parse(text).pretty())
