# slot_lgc_010

_Discovered in McCarthy's 1968 notebooks during his sabbatical at a Jesuit monastery in Rome. An experiment in whether liturgical Latin could serve symbolic reasoning better than s-expressions. The monks preserved the manuscripts but never compiled them._

This language emerged from McCarthy's 1968 notebooks during a sabbatical at a Jesuit monastery in Rome, where he investigated whether liturgical Latin could serve symbolic reasoning better than s-expressions. The result is a logic programming system—facts and rules evaluated by unification and backtracking—wrapped in Latin keywords that echo the manuscript's monastic origins. There are no loops; iteration proceeds by recursion alone. There is no global state; every computation unfolds within predicate clauses. The `munus` keyword declares predicates, `verum` and `falsum` name truth values, and `sit` binds variables through unification rather than assignment. Programs read as declarative proofs, not imperative procedures. The monks preserved the manuscripts but never compiled them—until now.

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

Notice the clause syntax: `factorial(N, F) :- ...` declares a rule with head `factorial(N, F)` and body following `:-`. The `is` operator evaluates arithmetic—`F is N * F1` binds F to the product—while `=` would merely unify terms without evaluation. The `munus` keyword (Latin for duty, function) replaced McCarthy's original `defpred`. Uppercase identifiers (`N`, `F`) are variables; lowercase atoms (`factorial`) are predicate names. The statement terminator `.` mirrors Prolog but echoes the manuscript's liturgical punctuation.

The prohibition on loops and global state follows directly from the logic-programming foundation. Iteration is recursion; state is threaded through predicate arguments. McCarthy's notes emphasize that symbolic manipulation demands unification, not mutation. The Latin keywords were deliberate: verum and falsum felt more precise than true/false in a logical calculus, and munus (duty, function) captured the declarative nature of predicates better than defn or func. Block comments only—no line comments—mirror the manuscript's marginal annotations. The design enforces discipline: every computation is a proof, every proof a function.

## Run

```bash
python -m slot_lgc_010.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Expressing recursive algorithms—factorial, list traversal, tree search—through concise clause definitions. Pattern matching via unification eliminates explicit conditional branches. Symbolic reasoning tasks (term rewriting, constraint solving) map naturally to the clause-based model. Small programs that compose without ceremony: no boilerplate, no initialization, just facts and rules. The absence of loops and global state enforces referential transparency, making proofs easier to verify.

## What this language is not good at

The ban on loops makes imperative iteration patterns awkward—no while, no for, only tail recursion or backtracking. The absence of global state forces threading context through every predicate argument, which grows verbose. Latin keywords impose a learning curve: newcomers must memorize verum, munus, and redde before writing their first clause. Eager boolean evaluation prevents short-circuiting, so side-effecting expressions evaluate both branches unconditionally.

## A common mistake

Confusing `=` (unification) with `is` (arithmetic evaluation). Writing `X = 2 + 3` binds X to the compound term `2 + 3`, not the integer 5; you want `X is 2 + 3`. Similarly, attempting to write loops—the language has none. Recursion with base and recursive clauses replaces while/for. Finally, declaring top-level variables fails: only predicate definitions are allowed at module scope.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
