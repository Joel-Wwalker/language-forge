"""forthlang. Hand-written reference stack_based / concatenative compiler.

Mirrors lisplang's role for s_expression. When a user picks
`syntax = stack_based` in the GUI, the orchestrator templates from this
directory rather than asking the LLM to generate parser/codegen/runtime
from scratch. Drops generation time from minutes to seconds.

Dialect: Forth-flavored, with a Factor-influenced print form. Forms supported:
  : name body ;            colon definition (consumes/produces stack values)
  ( ... )                  paren comments (stack-effect notation)
  \\ rest of line           line comments
  if cond_body else then   conditional (`else` is optional)
  begin ... until          loop until top-of-stack is true
  begin ... again          infinite loop (Forth requires `leave` to exit;
                           we don't ship `leave`, so use `until` instead)
  do ... loop              counted loop: `limit start do ... loop`
  variable name            declare a mutable cell
  value name !             store
  name @                   fetch
  dup drop swap over rot   stack manipulation
  + - * / mod              arithmetic (postfix)
  = <> < > <= >=           comparison; returns Python True/False
  and or not               logical
  ." text"                 inline-print string literal
  s" text"                 push string literal
  .                        print top of stack
  cr                       newline

Booleans: `true` / `false`. Null: `nil`.
File extension: `.fth`.
"""
__version__ = "0.1.0"
