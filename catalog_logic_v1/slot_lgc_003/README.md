# slot_lgc_003

_Discovered in McCarthy's desk drawer at Stanford AI Lab, 1978. An attempt to reconcile Lisp's uniform representation with Prolog's relational semantics. Never published, deemed too austere for practical use._

A logic programming system stripped to first principles. Programs are databases of facts and rules; computation is query resolution through unification and backtracking. Variables bind once per clause—no assignment, no mutation within scope. Control flow emerges from predicate success and failure, not from explicit branching. The syntax honors Prolog's heritage while removing ornament: predicates succeed or fail, conjunctions short-circuit, recursion replaces iteration. The standard library includes pragmatic imperative operations (set, push, pop) that acknowledge the host runtime's mutation model, a concession to utility. Every top-level clause terminates with a period, a typographic finality that McCarthy insisted upon. The language was found incomplete, documented in margin notes suggesting that removing loops and structured exceptions was not an oversight but a deliberate return to relational purity.

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

The clause head names the predicate; the :- operator separates specification from implementation; the body is a conjunction of goals. The period is mandatory—omit it and the clause remains incomplete, syntactically unresolved. The write/1 and nl/0 predicates handle output; their side effects are acknowledged but not reflected in the type system. The query form ?- initiates evaluation. This is logic programming with Lisp's minimalism: no syntactic conveniences, no implicit conversions, no ceremony beyond what unification requires.

Programs should be declarative specifications, not instruction sequences. Loops imply an execution order that obscures the relational invariant; recursion states the invariant directly. A single unification operator subsumes assignment, pattern matching, and equality testing—three concepts collapsed into one. Dynamic typing permits the flexibility required for symbolic computation, while the absence of null (replaced by the empty list) eliminates a category of errors. Error handling via panic reflects the view that a logic program either proves a goal or fails cleanly; partial success is incoherent. The period terminator is not punctuation—it is the declaration that a clause's semantics are complete. Austerity is not deprivation; it is the removal of choice where choice is distraction.

## Run

```bash
python -m slot_lgc_003.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Expressing algorithms as relations rather than procedures. Backtracking search over solution spaces without explicit state management. Pattern matching via unification handles destructuring and binding simultaneously. Recursive predicates with base and inductive cases map naturally to the clause structure. Programs that are small, self-contained proofs are tersely stated—the twenty-line solution often suffices where imperative code sprawls.

## What this language is not good at

Iteration without recursion is unavailable, making bulk transformations verbose until the recursive idiom is internalized. Panic-only error handling means a single failure in a compound query aborts the entire computation; defensive checking must be explicit. Dynamic typing defers detection of arity mismatches and type confusions to runtime. The austere syntax offers no syntactic affordances for common imperative patterns—stateful programs require threading accumulators through arguments, a discipline that feels unnatural to programmers expecting mutable locals.

## A common mistake

Confusing = (unification) with is (arithmetic evaluation). Writing X = 2 + 3 binds X to the compound term +(2, 3), not to 5; use X is 2 + 3 for evaluation. Variables are immutable within a clause's scope—attempting to 're-assign' a bound variable by unifying it with a different term will fail. Beginners expect loops; the language provides none. Express iteration as recursive predicates with explicit base cases.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
