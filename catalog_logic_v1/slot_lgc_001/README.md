# slot_lgc_001

_Unearthed from a 1981 AI lab where logic programming was the only paradigm taught. Researchers insisted all computation should be queries against facts. The project was abandoned when the funding ran out, but the spec survived in a filing cabinet marked 'Too Pure For Industry'._

This language descends from a 1981 AI lab experiment where every problem was a query, every solution a proof. Programs are databases of facts and rules; execution is pattern matching and backtracking. Where most logic languages compromise with imperative features bolted on, this one keeps the clause-based core but admits the stdlib needs mutation - lists are mutable, predicates like `set/3` and `push/2` modify in place. The result is a logic shell around a procedural heart: you define predicates with `:-`, unify with `=`, and recurse instead of looping, but when you need a list reversed, you don't thread state through arguments. The lab abandoned this design when funding dried up, filing it under 'Too Pure For Industry.' They were half right. Pure logic programming remains impractical for most work. But this hybrid - unification and backtracking for control flow, mutation for data structures - carves out a niche where declarative reasoning meets pragmatic state.

A `logic_like` language with `dynamic` typing and `host_gc` memory.

Prolog-flavored: a database of facts and rules; queries return all bindings that satisfy them. `:-` separates rule head from body; `,` is conjunction; uppercase identifiers are variables, lowercase are atoms. No loops - iteration is recursion + backtracking.

## At a glance

```
parent(tom, bob).
parent(bob, ann).
ancestor(X, Z) :- parent(X, Z).
ancestor(X, Z) :- parent(X, Y), ancestor(Y, Z).
?- ancestor(tom, X), write(X), nl.
```

The `:-` operator separates the rule head from its body - `main :- ...` reads as 'main succeeds if the body succeeds.' The comma is conjunction: `write("Hello, World!"), nl` means 'write this string AND print a newline,' executed left to right. The period terminates the clause. Notice there's no return statement - predicates succeed or fail, they don't return values. The empty argument list in `main` is implicit; this is a fact with zero parameters. The whole program is one rule that, when queried, prints and succeeds.

The 1981 designers believed computation should be logical inference, not imperative steps. No loops: iteration is recursion and backtracking through multi-clause predicates. No static types: unification is the only safety net you need. But they weren't dogmatic. Prolog's traditional immutability makes list processing painful, so we made variables mutable by default and added imperative stdlib predicates. Error handling is panic-only because logic programming already has failure semantics - a goal that fails yields no solution, distinct from a runtime crash. The tension is intentional: keep the declarative surface (facts, rules, queries) but allow the imperative escape hatches that make real programs tolerable.

## Run

```bash
python -m slot_lgc_001.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Expressing recursive algorithms and relational constraints without ceremony. The clause-based syntax makes multi-case definitions readable - factorial is two facts, not a function with nested ifs. Backtracking search problems (permutations, constraint satisfaction) collapse to a few rules. The mutable stdlib means you can build up lists incrementally without threading accumulators, so ad-hoc scripting doesn't require the functional-programming mental overhead. Unification handles pattern decomposition for free.

## What this language is not good at

Programs with complex mutable state become unreadable - the clause syntax is built for rules, not stateful procedures. Dynamic typing means type errors surface at runtime, often deep in a backtracking search. The panic-only model is unforgiving; there's no try/catch, so a bad `int/1` conversion crashes the program. Debugging is hard: backtracking is invisible, and the lack of stack traces in the Prolog tradition means you add `write/1` calls and pray. Performance is Python-backend speeds, slower than compiled languages.

## A common mistake

Confusing `=` with `is`. The former is unification: `X = 2 + 3` binds X to the compound term `+(2, 3)`, not the integer 5. Use `is` for arithmetic: `X is 2 + 3` binds X to 5. New users write `Y = X * 2` expecting evaluation and get a structure instead. Also, treating variables as reassignable - within a clause, `X = 1, X = 2` fails because X can't unify with both 1 and 2.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
