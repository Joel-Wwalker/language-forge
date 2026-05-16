# slot_lgc_009

_Recovered from a 1972 Stanford AI Lab memo titled 'Cozy Logic.' McCarthy's handwritten notes suggest an attempt to make Prolog 'feel like home.' The keyword 'recipe' appears alongside Horn clauses. Nobody admits to compiling it._

Programs are recipes for truth, not instructions for machines. This language descends from a 1972 Stanford AI Lab experiment: what if we made Horn clauses feel like home? Facts and rules replace functions and statements. You define what is true—`parent(alice, bob).`—and ask what follows—`?- parent(X, bob).` The system searches, backtracks, unifies. The keywords (`thing`, `recipe`, `yes`/`no`) were McCarthy's attempt to soften formal logic's edges, though the underlying engine is unchanged. No loops, no assignment, no returning values—just predicates that succeed, fail, or leave variables bound. The memo suggests this was meant for teaching, a gentler entry to computational logic. Whether it succeeded is unclear. The fact that it compiles at all is the real surprise.

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

The `recipe` keyword is McCarthy's cozy overlay—it declares a predicate just as Prolog's bare clause syntax does. The `:-` still introduces the rule body; you can't escape Horn logic's structure. The statement terminator `.` closes the logical sentence, not a procedural command. Notice `write` and `nl` for output—logic languages have no 'return values,' only side effects like printing. The system doesn't execute this top-to-bottom; it queries `?- main.` and unifies.

Computation is search through a space of logical consequences. Loops are a procedural crutch; recursion and backtracking suffice. Assignment is mutation; unification is truth-finding. The type system is deferred to runtime because formal logic doesn't distinguish integers from atoms until evaluation demands it. Error handling is panic-only because a failed proof should halt, not recover—there's no 'exception' to a contradiction. The cozy keywords (`recipe` for clause definitions, `yes`/`no` for booleans) overlay the austere Horn structure, an ergonomic experiment that doesn't compromise the underlying calculus. The `.` terminator marks the boundary of a logical sentence, preserving the declarative clarity McCarthy insisted on. This is logic programming with warm lighting.

## Run

```bash
python -m slot_lgc_009.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Declarative problem-solving where the solution space is explored via backtracking. Knowledge bases, constraint satisfaction, symbolic reasoning—any domain where you can state what is true and let the engine find what follows. Pattern matching through unification handles structural queries elegantly. Small programs that encode rules rather than procedures stay terse and readable. The logic paradigm shines when the algorithm is 'try all possibilities until one works,' because that's the native execution model.

## What this language is not good at

Procedural algorithms feel unnatural when expressed as recursive clauses. Dynamic typing means arithmetic bugs surface at runtime, often deep in a backtracking search. Panic-only error handling offers no recovery—one failed unification in a nested rule can abort the entire query. The cozy keywords don't actually make Horn clause reasoning easier; `recipe` still introduces a rule head, and newcomers still conflate `=` (unification) with `is` (arithmetic evaluation). The joke stops being funny around 300 lines.

## A common mistake

Confusing `=` (unification) with `is` (arithmetic evaluation). Writing `X = 2 + 3` binds X to the compound term `+(2, 3)`, not 5. You need `X is 2 + 3` to force evaluation. Another: expecting variables to mutate. Once `X` unifies with a value, it's bound for that clause's scope—this isn't assignment. Finally, trying to write imperative loops. There are none. Recursion with multiple clause definitions is the iteration primitive.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
