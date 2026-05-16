# slot_lgc_007

_Discovered in Wadler's 2004 course notes for 'Logic Programming for Functional Programmers.' Students demanded exceptions. He complied, then never taught it again. The notes survived._

Logic programming remains one of the most elegant formalisms for expressing search and constraint problems, yet Prolog's commitment to backtracking failure makes robust error handling a notorious pain point. This language emerged from a 2004 attempt to introduce exceptions into the unification calculus without violating logical semantics—specifically, to let students write file I/O and user input handlers without resorting to failure-based hacks. The result preserves clause-based pattern matching and recursive predicates while grafting on try/catch/throw for the mundane world of missing files and malformed input. Wadler's students got their exceptions. He got a language nobody asked for twice. The notes endured because someone needed logic programming that could fail gracefully, and Prolog's ISO standard wasn't about to budge.

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

The factorial example demonstrates clause-based dispatch: the base case factorial(0, 1). is a fact, while the recursive case factorial(N, F) :- ... is a rule whose body evaluates via conjunction (the comma operator). Notice 'is' for arithmetic evaluation—'N1 is N - 1' binds N1 to a number, whereas 'N1 = N - 1' would bind N1 to the compound term, not its value. The query ?- factorial(5, R), write(R), nl. runs the predicate, unifies R with the result, then prints it. Clause termination with '.' follows Prolog convention.

The core tension was maintaining logical purity while accommodating real-world failure modes. Recursion replaces loops because clause-based dispatch with pattern matching naturally expresses iterative algorithms as mathematical recurrences. Exceptions extend rather than replace Prolog's failure semantics: unification still fails via backtracking, but resource errors and programmer-signaled faults throw instead. Mutable unification breaks pure logic programming but enables imperative workflows without abandoning the predicate calculus. The empty list as null follows Prolog's nil convention, simplifying recursive base cases. Dynamic typing keeps unification flexible; host GC keeps memory invisible. The design asks: what's the minimal graft to make logic programming practically tolerable?

## Run

```bash
python -m slot_lgc_007.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Recursive algorithms with multiple exit conditions shine here—clause dispatch replaces nested conditionals, and pattern matching on list structure makes traversals trivial. Search problems naturally map to backtracking predicates with conjunction and disjunction operators. Exception handling cleanly separates logical failure (backtrack and try the next clause) from unexpected failure (throw and unwind). Small constraint-satisfaction scripts benefit from the minimal keyword set and terse clause syntax. Programs that need both symbolic reasoning and practical I/O without drowning in continuation-passing style.

## What this language is not good at

The clause-based syntax becomes genuinely painful for imperative algorithms that don't decompose into recursive predicates—you end up simulating while-loops with tail-recursive predicates and accumulator parameters, which is more ceremony than enlightenment. Dynamic typing means arithmetic errors surface at runtime; there's no static check that Y in 'Y is X * 2' will actually be numeric. Large programs suffer because clause order matters for semantics but becomes invisible in long files. The unification-as-assignment duality confuses newcomers and irritates Prolog purists in equal measure.

## A common mistake

Confusing unification (=) with arithmetic evaluation (is). Writing 'X = 2 + 3' binds X to the structure '2 + 3', not the integer 5—you'll print the unevaluated term. Use 'X is 2 + 3' to force evaluation. Relatedly, forgetting that clause order determines semantics: putting the recursive case before the base case often causes infinite regress because unification matches top-to-bottom. Always place your base cases first unless you have guard conditions that prevent premature matching.

## Examples

### `monad_laws.slo`

Verify the monad left identity law through predicate composition.

### `curry_example.slo`

Demonstrate partial application through specialized predicates.

### `list_fold.slo`

Left fold combinator for reducing lists to a single value.

See `examples/` for the full source. Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) under `tests/` is verified end-to-end.
