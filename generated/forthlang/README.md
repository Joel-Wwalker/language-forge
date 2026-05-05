# forthlang

A Forth-flavored stack_based / concatenative dialect. Hand-written
reference compiler that ships with Language Forge — when you create a
new stack-based language in the GUI, the orchestrator templates from
this directory instead of asking the LLM to regenerate everything.

## What's a stack-based language?

There are no variables in the conventional sense. Programs are
sequences of operations that manipulate an implicit data stack:

```forth
2 3 + 4 *      \ pushes 20 (which is (2+3)*4 in postfix)
```

Function definitions consume + produce stack values. Composition is
just juxtaposition — putting words next to each other applies them
in order.

## Syntax

```forth
: square ( n -- n*n )    \ stack-effect comment
    dup * ;              \ definition body, terminated by ;

\ Variables and constants:
variable counter
0 counter !              \ store
counter @ .              \ fetch + print

42 constant answer
answer .                 \ prints 42

\ Conditionals:
7 0 > if ." positive" cr else ." not" cr then

\ Loops:
begin
    counter @ 1 + counter !
    counter @ 10 >
until                    \ runs until top-of-stack is true

\ Strings:
." inline-printed text"  \ prints during execution
s" pushed text"          \ pushes onto stack
```

## Why this exists

Without a hand-written reference, every stack-based language Forge
generated would have to be LLM-built from scratch — slow and unreliable
because Forth tokenization is context-sensitive (`."` and `(` change
how the next bytes are parsed) and the LLM tends to mis-emit. The
reference is verified against all 8 canonical tests; new languages
inherit that correctness for free.

## Canonical tests

All 8 (plus a 9th stdlib) pass:

| test          | exercises                                     |
|---------------|-----------------------------------------------|
| hello_world   | `." text"` + `cr`                             |
| arithmetic    | postfix `+ - * / mod`                         |
| variables     | `variable` + `! @` + `constant`               |
| conditionals  | `if/else/then`                                |
| loops         | `begin ... until`                             |
| functions     | `: name body ;` + recursion                   |
| closures      | counter pattern (Forth doesn't do real closures) |
| strings       | `." inline"` + `s" push"`                     |
| stdlib        | `dup drop swap over rot`                      |

## Run

```bash
python -m forthlang.compile tests/factorial.fth
python tests/factorial.fth.out.py
```
