"""lisplang. Hand-written reference s_expression compiler.

Mirrors the role toylang plays for c_like and python_like generation.
When a user picks `syntax = s_expression` in the GUI, the orchestrator
templates from this directory rather than asking the LLM to generate
parser/codegen/runtime from scratch. That drops generation time from
~15 minutes to seconds and removes a whole class of LLM-introduced
bugs (e.g. the `(lambda : ()[-1])` closure bug).

Dialect: Clojure-flavored Lisp. Forms supported:
  - (def NAME expr)             - global binding
  - (defn NAME (a b ...) body+) - function definition; last form is the return
  - (fn (a b ...) body+)        - anonymous function; same return rule
  - (if cond then else)         - conditional expression (always 3-arg)
  - (when cond body+)           - conditional, returns nil when false
  - (while cond body+)          - imperative loop, returns nil
  - (let ((n v) ...) body+)     - local bindings
  - (do form+)                  - sequence; value is the last form
  - (set! NAME expr)            - mutation (use sparingly)
  - (return expr)               - early return (rare in Lisp; honored)
  - (op a b)                    - prefix arithmetic / comparison / logic
  - (f a b ...)                 - function call

Comments: `; line` and `#| block |#`.
Booleans: `true` / `false`. Null: `nil`.
"""
__version__ = "0.1.0"
