# slot_lgc_006

_Unearthed from a Benedictine scriptorium, circa 1147. The monks formalized their theological disputations in this notation, proving heresies by contradiction. Modern recovery dates to 2023._

Unearthed from a Benedictine scriptorium, this language preserves the monks' method for proving theological propositions through logical contradiction. Programs are not sequences of commands but collections of facts and rules; execution is a query that either succeeds by unification or fails by exhausted possibilities. The syntax descends from their dispute notation: clauses terminated with the period that ended each formal proposition, variables in uppercase as manuscript convention dictated, lowercase atoms for concrete truths. Where imperative tongues command the machine, this one petitions: one must state what is known, declare what follows, then ask whether a conclusion holds. The Latin keywords—verum and falsum, sit and munus—echo the liturgical language in which the original disputations were conducted. Modern recovery has transpiled the notation to Python, retaining the host's garbage collection, but the logic remains: no loops, no mutation in the imperative sense, only recursive descent through rule bodies and the prover's relentless backtracking.

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

The example invokes write to emit a string and nl for the newline—a pattern inherited from Prolog's I/O primitives, where output is a side-effecting predicate, not a function's return. The query begins with the interrogative symbol that marks every question posed to the rule database. The clause terminates with the period that closes a proposition, here signaling the query's end. Notice the absence of a main function or entry point: execution is the act of asking whether this goal succeeds, not calling a designated procedure. Thus the program is a petition, not a command.

The monks rejected procedural thinking in favor of declarative truth. A program is a database of propositions, not a sequence of actions; one states what holds and queries whether further propositions follow. Hence no loops—iteration is recursion over structure, as a theological proof recurses over premises. The period terminator mirrors the punctus that closed each thesis in formal disputation. Dynamic typing reflects their focus: logical structure mattered, not the metalogical apparatus of type judgments. Mutable-by-default semantics accommodate the Python host's reference model, but mutation is incidental; the language's essence is unification, not assignment. Panic-only error handling: a failed proof halts disputation, as a discovered contradiction must end the argument. The runtime is host-managed, freeing the notation from memory ceremony. What remains is pure relational thinking—facts, rules, and the question of what necessarily follows.

## Run

```bash
python -m slot_lgc_006.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Expressing recursive relationships over structured data—lists, trees, genealogies—where pattern matching via unification naturally decomposes the problem. Declarative specifications that read as logical propositions rather than procedural recipes: state the rules, ask the question, let backtracking explore the solution space. Problems that reduce to theorem-proving: constraint satisfaction, symbolic manipulation, pattern-driven transformations. The clause-based syntax encourages thinking in terms of cases and invariants, not control flow, which clarifies algorithms that are inherently relational.

## What this language is not good at

Imperative sequences where one must orchestrate side effects in strict order—the notation resists this, as it was designed for timeless propositions, not temporal commands. Programs that demand mutable state threaded through long computation chains grow awkward; unification binds once, and the imperative dance of update-read-update requires contortions. Performance-sensitive tasks suffer: the Python host is itself interpreted, and backtracking's exhaustive search compounds the cost. Modularity is absent from this recovery; scaling past a few dozen clauses becomes archaeological.

## A common mistake

Confusing the unification operator with arithmetic evaluation. Writing X = 2 + 3 binds X to the compound term itself, not the integer 5; one must write X is 2 + 3 to force evaluation, as is was the monks' operator for calculating numeric consequences. Newcomers trained in imperative tongues attempt assignment where the language offers only unification, then wonder why variables refuse re-binding. Another error: omitting the period terminator—the parser expects every clause and query to end as a proposition ends, with the punctus that marks finality.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
