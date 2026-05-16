# slot_lgc_004

_Emerged from a 1974 Edinburgh attempt to make Prolog digestible for ALGOL programmers. The team grafted imperative loops onto clause syntax before the grant expired. Survived in one PDP-11 user manual._

slot_lgc_004 grafts imperative loop constructs onto a clause-based syntax, a compromise born from a 1974 Edinburgh research group's attempt to make logic programming palatable to ALGOL veterans. The result is a hybrid that accepts both traditional clause definitions (head :- body.) and procedural control flow (while, for). Variables unify, predicates succeed or fail, and yet you can mutate lists and iterate with familiar loop forms. It transpiles to Python, relying on host garbage collection rather than implementing its own runtime. The language retains logic programming's structural clarity for defining relations while offering an escape hatch for programmers who think in loops rather than recursion. It's a bridge language, frozen in the amber of a single PDP-11 user manual, never refined beyond its initial scope.

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

The :- operator separates the clause head from its body, maintaining logic syntax. The is operator evaluates arithmetic expressions, a necessary distinction in logic languages where = performs unification rather than computation. Notice the statement terminator . ending each clause - borrowed from Prolog, it signals clause completion. While the language supports traditional loops, this example stays declarative, demonstrating that clause-based definitions remain the primary mode. The block comment /* */ syntax is the only comment form; no line comments exist in the v1 design.

The designers faced ALGOL-trained programmers who balked at recursion-only iteration. Rather than evangelize the virtues of tail calls and backtracking, they grafted while and c-style for loops directly into the clause syntax. Mutable-by-default semantics and panic-only error handling simplified the implementation - no exception machinery, no immutability tracking. Dynamic typing avoided the complexity of Hindley-Milner inference, keeping the transpiler tractable for a small team on a short grant. The empty list [] doubles as the null sentinel, a pragmatic overload that saved introducing another literal form. Every choice prioritized implementation speed over theoretical purity, aiming to ship before funding dried up.

## Run

```bash
python -m slot_lgc_004.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Small utilities that need both pattern-based dispatch and traditional iteration. Programs where clause structure clarifies the problem domain but recursion feels unnatural - parsing formats with known loop counts, processing fixed-size records, traversing arrays with index arithmetic. The imperative stdlib (push, pop, mutating set) supports straightforward data manipulation without threading accumulators through recursive calls. Short scripts that benefit from clause modularity without committing to full logic programming discipline.

## What this language is not good at

Anything requiring real backtracking or constraint solving - the imperative loops break the search model. Large programs where the hybrid syntax becomes confusing rather than clarifying; past a few hundred lines, the mix of declarative clauses and procedural loops fragments into inconsistent styles. Performance-critical code, since the Python transpilation layer adds overhead. Programs that would benefit from static typing, as the dynamic model offers no compile-time safety net.

## A common mistake

Using = when you need is for arithmetic. Writing X = 2 + 3 binds X to the compound term 2 + 3, not the value 5. You want X is 2 + 3 to force evaluation. This trips up newcomers who expect = to compute. Another pitfall: mixing backtracking expectations with imperative loops. A while loop doesn't retry on predicate failure - it's purely procedural. Once you enter a loop, you've left the logic model.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
