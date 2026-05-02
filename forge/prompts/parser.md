# Parser prompt

Generate `parser.py` for the target language. **This is the highest-failure stage**, read the examples carefully and copy their patterns.

## Resolved spec

```json
{{SPEC}}
```

## Requirements

- Expose a module-level string `GRAMMAR` containing a Lark grammar.
- Use `parser="lalr"`. Use `propagate_positions=True`.
- Expose `parse(src: str) -> Tree`.
- The grammar's `start` rule produces a sequence of statements.
- Statements MUST include: variable declaration, function definition, if/else, while loop, return, expression statement, block.
- Expression layer MUST include (in precedence order, low to high): assignment, logical or, logical and, equality, comparison, additive, multiplicative, unary, call, primary.
- Primary MUST include: integer, float, string, true, false, null, name reference, parenthesized expression. Use Lark `-> alias` rules so codegen can dispatch on rule name.
- Use `%import common.CNAME -> NAME`, `%import common.INT`, `%import common.FLOAT`, `%import common.ESCAPED_STRING -> STRING`.
- Add a `if __name__ == "__main__":` debug entrypoint that pretty-prints the parse tree.

## Extended option behaviors (read the spec's `options` block)

- `comment_style`: `line` only, `block` only, `both` (default), or `nestable_block` (Rust-style nesting).
- `string_literals`: `single`, `double` (default), `both`, `triple_quoted` (adds `"""..."""`), or `raw_and_normal` (adds `r"..."`).
- `numeric_literals`: `decimal_only` (default), `c_style` (also `0x`, `0o`, `0b`), or `extended` (adds digit separators `1_000_000`).
- `default_mutability = immutable`: accept `let mut x = ...` AND `let x = ...`. Treat `mut` as a reserved keyword.
- `error_handling = exceptions`: accept `try { ... } catch (NAME) { ... }` blocks and `throw expr;`. Reserve `try`, `catch`, `throw`.
- `loop_forms` may add `c_for` (`for (init; cond; step) block`), `foreach` (`for NAME in expr block`), `repeat_until` (`do block while expr;`), `loop_break` (`loop block` with `break expr`). Add only the forms listed in `options.loop_forms`.
- `multiple_returns = tuple`: accept `return a, b;` and `var (x, y) = f();` (or python_like equivalents).

## Natural-language phrasebook (HIGHEST PRIORITY when present)

If `spec.customization.natural_language` is set, use those sentence
templates as the LITERAL strings in the grammar rules. Each template is
a string containing `<placeholder>` slots; substitute the slots with the
appropriate non-terminal references and keep all other text verbatim.

Slot meanings (FIXED):
- `<name>` is `NAME`
- `<value>`, `<expr>`, `<cond>` are `expr`
- `<body>` is `block` (or a sequence of statements as the spec dictates)
- `<else>` is an else clause (which is itself a `block`)
- `<params>` is `params`
- `<args>` is `args`

Example: if `var_decl = "set <name> to <value>."`, emit:
```
var_decl: "set" NAME "to" expr "."
```

Example: if `if_stmt = "if <cond> then <body> otherwise <else>."`, emit:
```
if_stmt: "if" expr "then" block "otherwise" block "."
```

If a template ends with `.`, that period is the statement terminator
(replaces the spec's `;`). If it ends with `end`, that's the terminator.
The grammar rule names (`var_decl`, `func_def`, `if_stmt`, etc.) STAY
THE SAME so codegen can dispatch on them. Only the literal strings
change.

If the phrasebook supplies `true_word` / `false_word` / `null_word`,
use those as the boolean and null literal terminals (replacing the
spec's `boolean_keywords.true`, etc.).

If the phrasebook supplies `and_word` / `or_word` / `not_word`,
use those as the operator strings in the logical rules instead of
`&&`/`||`/`!` or `and`/`or`/`not`.

Multi-word phrases like `"and also"` are valid Lark literal strings;
just write them as quoted strings in the grammar.

Unspecified entries fall back to the spec's defaults from the syntax
family.

## Operator naming convention (codegen relies on these rule names)

Use exactly these rule names: `var_decl`, `func_def`, `params`, `if_stmt`, `else_clause`, `while_stmt`, `return_stmt`, `block`, `expr_stmt`, `assign_op` (alias of assign with rhs), `logical_or`, `logical_and`, `equality`, `comparison`, `term`, `factor`, `unary`, `call`, `trailer`, `args`. Use these primary aliases: `int_lit`, `float_lit`, `string_lit`, `true_lit`, `false_lit`, `null_lit`, `name_ref`, `paren`.

## Output format

Return ONLY a single fenced ```python code block with the full file contents. No prose.

## Example 1, c_like grammar fragment (this is the canonical shape; adapt to the spec)

```
GRAMMAR = r"""
start: stmt*

?stmt: var_decl | func_def | if_stmt | while_stmt | return_stmt | block | expr_stmt

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
unary:       UNARY_OP unary | call
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
%ignore LINE_COMMENT
"""
```

## Example 2, python_like grammar (indent-based, FULL working example)

For `python_like` syntax, use Lark's `Indenter` postlex. Copy this structure and adapt the keywords to match the spec (e.g. `def` vs `func`, `let` vs `var`).

```python
from lark import Lark, Tree
from lark.indenter import Indenter


class _PyIndenter(Indenter):
    NL_type = "_NL"
    OPEN_PAREN_types = ["LPAR"]
    CLOSE_PAREN_types = ["RPAR"]
    INDENT_type = "_INDENT"
    DEDENT_type = "_DEDENT"
    tab_len = 8


GRAMMAR = r"""
start: (_NL | stmt)*

?stmt: var_decl | func_def | if_stmt | while_stmt | return_stmt | expr_stmt

var_decl:    "let" NAME "=" expr _NL
func_def:    "def" NAME "(" params? ")" ":" _NL _INDENT stmt+ _DEDENT
params:      NAME ("," NAME)*
if_stmt:     "if" expr ":" _NL _INDENT stmt+ _DEDENT elif_clause* else_clause?
elif_clause: "elif" expr ":" _NL _INDENT stmt+ _DEDENT
else_clause: "else" ":" _NL _INDENT stmt+ _DEDENT
while_stmt:  "while" expr ":" _NL _INDENT stmt+ _DEDENT
return_stmt: "return" expr? _NL
expr_stmt:   expr _NL

?expr:       assign
assign:      NAME "=" assign      -> assign_op
           | logical_or            -> passthru

logical_or:  logical_and (OR_OP logical_and)*
OR_OP:       "or"
logical_and: equality (AND_OP equality)*
AND_OP:      "and"
equality:    comparison (EQ_OP comparison)*
EQ_OP:       "==" | "!="
comparison:  term (CMP_OP term)*
CMP_OP:      "<=" | ">=" | "<" | ">"
term:        factor (TERM_OP factor)*
TERM_OP:     "+" | "-"
factor:      unary (FACTOR_OP unary)*
FACTOR_OP:   "*" | "/" | "%"
unary:       UNARY_OP unary | call
UNARY_OP:    "not" | "-"
call:        primary trailer*
trailer:     LPAR args? RPAR
args:        expr ("," expr)*

primary:     INT       -> int_lit
           | FLOAT     -> float_lit
           | STRING    -> string_lit
           | TRUE      -> true_lit
           | FALSE     -> false_lit
           | NULL      -> null_lit
           | NAME      -> name_ref
           | LPAR expr RPAR -> paren

TRUE.2:  "True"
FALSE.2: "False"
NULL.2:  "None"

LPAR: "("
RPAR: ")"

%import common.CNAME -> NAME
%import common.INT
%import common.FLOAT
%import common.ESCAPED_STRING -> STRING
%import common.WS_INLINE
%declare _INDENT _DEDENT

%ignore WS_INLINE
COMMENT: "#" /[^\n]*/
%ignore COMMENT
_NL: ( /\r?\n[\t ]*/ | COMMENT )+
"""

_PARSER = Lark(GRAMMAR, parser="lalr", postlex=_PyIndenter(),
               start="start", propagate_positions=True)


def parse(src):
    # Indenter requires a trailing newline; add one if missing.
    if not src.endswith("\n"):
        src = src + "\n"
    return _PARSER.parse(src)
```

CRITICAL for python_like:
- Use `_NL` (filtered) not `NL` for newlines.
- `_INDENT` / `_DEDENT` MUST be declared via `%declare _INDENT _DEDENT`.
- Blocks are `":" _NL _INDENT stmt+ _DEDENT`: three tokens after the colon.
- `LPAR`/`RPAR` MUST be named terminals (not `"("`/`")"`) so the indenter can recognize "inside parens" and suspend NL tracking.
- Always add a trailing `\n` to source before parsing.
- Adapt keywords (`def`/`func`, `let`/`var`, `True`/`true`) to match the spec.

Use whichever shape fits the spec's `block_style`.
