# slot_lgc_008

_Recovered from a 1976 internal memo system at Eindhoven University of Technology. Used to formally verify purchase requisitions and resource allocations. Allegedly Dijkstra's response to a budgeting dispute._

A clause-based language for specifying resource allocation and requisition workflows, recovered from Eindhoven's 1976 bureaucratic computing experiments. Programs are databases of facts and rules evaluated by querying: predicates unify variables, recursion replaces iteration, and every deliverable must prove its preconditions before execution proceeds. The corporate vocabulary is deliberate—`asset` declarations, `deliverable` predicates, `approved`/`rejected`/`pending` truth values—enforcing the view that computation is a sequence of validated approvals, not ad-hoc state mutations. Errors are specification failures and terminate immediately. The absence of imperative loops reflects Dijkstra's documented disdain for goto-like control flow; recursion with base cases proves termination where while-loops merely promise it. Block comments only, because inline remarks scatter focus.

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

The `deliverable` keyword marks this as a defined predicate rather than a raw fact, maintaining the corporate vocabulary where functions are deliverables requiring specification. The clause structure—`deliverable name :- body.`—separates the goal from its proof obligations; here `greet` succeeds if `write` and `nl` both succeed sequentially (conjunction via `,`). No return values exist; output is a side effect via `write`, and success/failure are the only results. The trailing `.` terminates the clause, enforcing the punctuation discipline Dijkstra favored for machine-readable specifications.

Imperative loops introduce mutable counters and exit conditions you cannot formally verify; recursion with explicit base cases makes termination provable at design time. Panic-only error handling reflects the principle that runtime failures indicate specification errors, not operational conditions requiring recovery—if your requisition logic panics, the workflow itself was underspecified. The corporate keyword overlay maps directly to the original Eindhoven use case: every computation is an asset allocation or a deliverable with approval gates. Short-circuit conjunction honors least-effort evaluation: if a precondition fails, subsequent clauses need not execute. Block-only comments enforce deliberate documentation boundaries rather than marginal annotations that rot.

## Run

```bash
python -m slot_lgc_008.compile path/to/program.slo
python path/to/program.slo.out.py
```

## What this language is good at

Rule-based resource allocation and workflow validation, where predicates model approval gates and recursion traverses hierarchical requisition structures. Declarative specifications that read like formal policy documents rather than procedural scripts. Recursive algorithms expressed tersely because clause-based dispatch replaces conditional branching—multiple predicate definitions with guards act as pattern-matched case splits. Dynamic typing eliminates annotation ceremony when modeling domain entities that change shape across approval stages.

## What this language is not good at

Iteration without recursion is impossible, making simple counter-loops verbose—every increment requires a recursive call with an accumulator parameter. Panic-only error handling means no graceful degradation: one failed precondition terminates the entire workflow, which is principled but unforgiving in production systems. The corporate keyword theme becomes tedious past 200 lines when every predicate is a deliverable and every boolean is an approval status. Logic-programming semantics confuse programmers trained on assignment and mutation; unification is not intuitive when you expect variable reassignment.

## A common mistake

Confusing `is` with `=`: `X is 2 + 3` evaluates arithmetic and binds X to 5, while `X = 2 + 3` unifies X with the compound term `+(2, 3)` without evaluation. New users write lowercase variable names (`result`) when uppercase is required (`Result`)—lowercase identifiers are atoms, not variables. Attempting assignment-style mutations (`X = 5, X = 10`) fails because variables unify once; subsequent bindings cause the goal to fail, not reassign.

## Examples

See `examples/` and `tests/` for working programs.
Each canonical test (`hello_world.slo`, `arithmetic.slo`, ...) is
verified end-to-end.
