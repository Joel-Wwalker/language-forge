# slot_lgc_005

_Unearthed from the Blackfriars Theatre library during renovations, circa 1608. Elizabethan playwrights encoded character motivations as logical predicates before committing scenes to parchment, verifying plot coherence through mechanical reasoning._

slot_lgc_005 emerged from a peculiar theatrical practice: before quill touched parchment, playwrights at the Blackfriars encoded character motivations and plot constraints as logical predicates, then queried them to ensure no hero could betray an oath whilst pursuing revenge, no timeline could permit both the king's death and his later appearance. The language you see here transpiles to Python but thinks in clauses and unification—facts and rules terminated by the period, uppercase variables that bind through backtracking, predicates that succeed or fail rather than return. The Shakespearean keywords (`summon` for predicates, `verily` and `naught` for truth values) aren't mere costume; they mark the language's theatrical lineage, where every rule is a constraint on what may transpire, every query a test of narrative coherence. It's logic programming with the Globe's dusty urgency, dynamically typed because character traits shift, recursion-only because iteration feels too mechanical for drama.

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

The clause above defines a zero-arity predicate—when parameters vanish, so do the parentheses. The `:-` operator separates head from body; the comma conjoins `write` and `nl` as 'and' (sequential goals proved left-to-right). The period terminates the clause like a sentence in the 1608 manuscript. Notice `write` and `nl` aren't functions returning values but predicates that succeed by side-effect—logic programming blurs proving and doing. To execute, query `?- main.` at the prompt, asking the engine to prove the goal holds.

The decision to forbid loops in favor of recursion reflects theatrical structure: a scene unfolds through recursive descent into memory and motive, not mechanical repetition. Dynamic typing follows the playwright's reality—Hamlet's madness is real, then feigned, then real again; types shift as the plot demands. Panic-only error handling mirrors stage catastrophe: when a constraint fails, the play cannot continue. The clause-based syntax (`:-` separating head from body, `.` terminating each declaration) enforces clarity—every rule must stand alone, legible to the dramaturg who verifies it. Shakespearean keywords (`summon`, `verily`, `naught`) aren't decoration; they bridge the 1608 mindset where logic was incantation, not computation.

## Run

```bash
python -m slot_lgc_005.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Verifying complex relational constraints—family trees, plot timelines, character obligations—through declarative rules rather than imperative checks. Recursive list processing shines because the `[H | T]` pattern decomposes naturally without loops. Backtracking search problems (pathfinding, puzzle solving) map directly to multiple clause definitions with differing guards. Short programs that compose predicates like theatrical scenes, each clause a self-contained constraint, queried together to prove narrative consistency.

## What this language is not good at

The theatrical keywords grow tiresome past the first act—writing `verily` for true and `naught` for false is charming in a 50-line script, wearisome in 500. Dynamic typing means arithmetic bugs lurk until runtime; `is` evaluates expressions but type mismatches panic rather than warn. The stdlib's imperative operations (`set`, `push`, mutating collections) clash with the logic paradigm's declarative purity, forcing hybrid thinking. Backtracking's search overhead makes tight loops (when hand-coded via recursion) slower than languages with native iteration.

## A common mistake

Confusing `is` with `=`: writing `X = 2 + 3` binds X to the compound term `2 + 3`, not 5. Use `is` for arithmetic evaluation (`X is 2 + 3`). Second pitfall: lowercase identifiers are atoms (constants), uppercase are variables. Writing `parent(Tom, bob)` means atom `Tom` and variable `bob`, the reverse of Python's convention. Finally, attempting mutation—binding X twice in one clause fails, since variables unify once and stay bound.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
