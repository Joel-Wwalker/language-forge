# lisplang

A Clojure-flavored Lisp dialect. Hand-written reference compiler that ships
with Language Forge — when you create a new s-expression language in the
GUI, the orchestrator templates from this directory instead of asking the
LLM to regenerate everything from scratch.

## Why this exists

The first attempt at S-expression generation in Forge took ~15 minutes per
language (parser, codegen, runtime, stdlib all written by the LLM with three
repair attempts) and still produced subtle bugs. Closures, in particular,
emitted `(lambda : ()[-1])` — accessing the last element of an empty tuple
— because the codegen prompt had `...` placeholders the model filled in
creatively.

The fix was to ship a hand-written reference, the same way `toylang` is the
reference for `c_like`. New s-expression languages are now templated from
this directory in ~1.3 seconds and pass all 8 canonical tests deterministically.

## Syntax

```lisp
(def x 10)                       ; global binding
(defn add (a b) (+ a b))         ; function
(if cond then else)              ; conditional (always 3-arg)
(when cond body+)                ; conditional, returns nil when false
(while cond body+)               ; imperative loop
(let ((n v) ...) body+)          ; local bindings
(do form+)                       ; sequence; value is the last form
(set! NAME expr)                 ; mutation
(fn (a b) body+)                 ; anonymous function
```

## Canonical tests

All 8 pass:

| test          | exercises                                     |
|---------------|-----------------------------------------------|
| hello_world   | print + string literal                        |
| arithmetic    | prefix `+` `-` `*` `/` `mod`                  |
| variables     | `def` + `set!`                                |
| conditionals  | `if` and `when`                               |
| loops         | `while` with `set!`                           |
| functions     | `defn` + recursion + tail return              |
| closures      | nested `fn` capturing + mutating outer scope  |
| strings       | string concatenation, `len`, `upper`          |

## Run

```bash
python -m lisplang.compile tests/closures.lsp
python tests/closures.lsp.out.py
```
