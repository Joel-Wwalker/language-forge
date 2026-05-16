# slot_lgc_002

_Recovered from a 1982 automated theorem prover at Edinburgh's AI lab. Originally used to verify railway signaling systems until the funding dried up. The proof traces are still embedded in the comments._

slot_lgc_002 is a logic programming language recovered from Edinburgh's 1982 railway signaling verification project. Programs are databases of facts and rules evaluated by backtracking search, not sequential execution. Instead of writing functions that return values, you declare relationships between terms via unification. The railway heritage shows in the design: predicates declare what must hold, not how to compute it—a natural fit for expressing safety constraints. Dynamic typing and mutable state make it more forgiving than pure Prolog for exploratory work, but the absence of structured error handling reflects its theorem-prover origins: invalid states fail, full stop. It transpiles to Python and inherits Python's garbage collector, so you can interoperate with host libraries while keeping the logic-based surface. The `.slo` extension stands for "signaling logic," a nod to the system it once verified.

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

The example defines a rule `main` with no parameters, using the `:-` operator to declare that "main holds if write and nl both hold." This is not a function call returning a value—it's a goal that succeeds or fails. The `.` terminator marks the end of the clause, Prolog-style. Notice `write` and `nl` are predicates, not statements; they succeed by side effect (printing), then allow backtracking to continue. The uppercase identifiers you see in richer examples would be logic variables, unified by pattern matching, not assigned.

The language prioritizes declarative clarity over procedural control. Iteration is expressed as recursive rules with multiple clauses—backtracking replaces branching, so no loop keywords exist. Panic-only error handling reflects the theorem-prover lineage: a failed goal yields no solution; unrecoverable errors halt execution. This eliminates try-catch scaffolding but demands careful guards. Dynamic typing reduces annotation burden in verification scripts, though it sacrifices compile-time checks. Mutable state is allowed by default because railway signaling models track evolving state machines; pure immutability would require threading state through every predicate. The design trades Prolog's mathematical purity for pragmatic modeling: facts can change, arithmetic is eager (via `is`), and the runtime is Python's heap rather than a WAM.

## Run

```bash
python -m slot_lgc_002.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Expressing constraint satisfaction problems where backtracking naturally explores solution spaces. Pattern matching via unification handles complex term structures without manual destructuring. Rules with multiple clauses let you encode domain knowledge as guarded alternatives, making the logic explicit and auditable—exactly what verification tasks demand. Short-circuit evaluation in conjunctions means guards fail fast, and the Prolog-style relational model excels at bidirectional predicates: the same rule can answer "what satisfies X?" and "does Y satisfy X?" without separate implementations.

## What this language is not good at

Dynamic typing means type errors surface at runtime, not in proofs—ironic for a theorem prover language. Panic-only error handling offers no recovery: a malformed term crashes the program. The absence of loops makes iterative algorithms awkward; you'll write tail-recursive predicates where a for-loop would be clearer. Mutable state breaks logical purity, so tracking which predicates have side effects becomes manual.

## A common mistake

Confusing `=` with `is`: writing `X = 2 + 3` binds X to the compound term, not 5—use `X is 2 + 3` for arithmetic. Newcomers treat rules like functions, expecting `double(5, R)` to "return" into R, when the rule must explicitly compute via `is`. Panic-only error handling means no safety net: an unexpected failure halts the program, not just the current goal.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
