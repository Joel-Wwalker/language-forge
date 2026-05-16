# Idiomatic content for the language (structural variance)

You're writing themed program bodies that REPLACE the generic canonical
tests for a generated programming language. The point: the language's
`tests/arithmetic.X` shouldn't look identical to every other language's
`tests/arithmetic.X`. Same expected output, same canonical test name,
but a body that reflects this language's persona, era, theme, and
purpose.

You will get the resolved spec - persona, era, theme, phrasebook,
keyword overrides, surface syntax. Use it. Be specific to it. Don't
write a generic arithmetic test and slap a `loot` variable name on it.
Write a test where a captain divides plunder.

## Spec for context

```json
{{SPEC}}
```

## Family-specific worked examples (USE THESE)

The spec's `options.syntax` field names one of five families. Each
family below has 2 working programs drawn from its reference
compiler's actual canonical tests - these are programs that DO parse,
DO compile, and DO run correctly against the reference grammar.
**When your `options.syntax` matches one of these families, model your
themed canonical test bodies on these examples' shapes.** Themed
content (variable names, problem domain, output strings) varies; the
syntactic skeleton (keywords, operators, statement form, comment
style) MUST match.

The previous prompt produced themed bodies in plausible-looking but
not-actually-parseable forms - especially for ml_like (where the LLM
knew OCaml broadly but didn't match this language's specific subset)
and now logic_like (where the LLM may know SWI-Prolog idioms that
prologlang doesn't ship: cut, assert/retract during queries, custom
operators, DCGs, CLP, etc.). These examples close that gap by
anchoring the LLM to syntax that **already works** against the
reference.

### c_like worked examples

```
// arithmetic - basic int math + operator precedence.
print(1 + 2 * 3); // 7
print((1 + 2) * 3); // 9
print(20 - 4 - 3); // 13 (left-assoc)
print(17 % 5); // 2
print(-7 + 10); // 3
```

```
// loops - sum 1..10 with a while loop.
var i = 1;
var total = 0;
while (i <= 10) {
 total = total + i;
 i = i + 1;
}
print(total);
```

c_like uses: `//` line comments, `var` declarations, `func` function
definitions with `{` body `}`, `while (cond) { body }` loops,
semicolon terminators, `print(...)` call form.

### s_expression worked examples

```
; arithmetic - prefix-notation.
(print (+ 2 3))
(print (- 10 4))
(print (* 6 7))
(print (mod 17 5))
(print (+ 1 (* 2 3)))
```

```
; closures - function returning a function that captures + mutates a binding.
(defn make-counter ()
 (def count 0)
 (fn ()
 (set! count (+ count 1))
 count))

(def counter (make-counter))
(print (counter))
(print (counter))
```

s_expression uses: `;` line comments, parenthesized prefix forms,
`(defn name (params) body)` function definitions, `(def name value)`
bindings, `(set! name value)` for mutation, `(fn () body)` for
anonymous functions, no statement terminators.

### stack_based worked examples

```
\ arithmetic - postfix evaluation.
2 3 + .
10 4 - .
6 7 * .
17 5 mod .
1 2 3 * + .
```

```
\ functions - definition, call, recursion.
: add ( a b -- a+b )
 + ;

: factorial ( n -- n! )
 dup 1 <= if drop 1 else dup 1 - factorial * then ;

3 4 add .
5 factorial .
```

stack_based uses: `\` line comments, postfix operators (operators
follow their operands), `: name ( stack-effect ) body ;` colon
definitions, `if ... else ... then` conditionals (NOT braces), `.`
to print top of stack. NO infix expressions - everything is stack
manipulation.

### ml_like worked examples

```
(* loops - recursion over a list, ML-natural. ml_like has no
 while/for; iteration is recursion on list cons. *)
let rec sum lst = match lst with
 | [] -> 0
 | h :: t -> h + sum t
;;

let rec count_down n =
 if n < 0 then ()
 else (
 print_int n ;
 print_newline () ;
 count_down (n - 1)
 )
;;

print_int (sum [1; 2; 3; 4; 5]) ;;
print_newline () ;;
count_down 3 ;;
```

```
(* functions - curried definition + recursion via let rec. *)
let add a b = a + b ;;
print_int (add 2 3) ;;
print_newline () ;;

let rec fact n = if n <= 1 then 1 else n * fact (n - 1) ;;
print_int (fact 5) ;;
print_newline () ;;
```

ml_like uses: `(* ... *)` block comments (no line-comment syntax),
`let x = value ;;` bindings, `let f x y = body ;;` function
definitions (curried, juxtaposition application), `let rec ... ;;`
for recursion, `match expr with | pat -> body | pat -> body ;;` for
pattern matching, `[]` empty list + `::` cons, `;;` terminates every
top-level item, `print_int` / `print_string` / `print_newline ()` for
output (NOT a single `print(x)` function - mllang has type-specific
print functions). Sequence inside parens: `(e1 ; e2 ; e3)` evaluates
all and returns last. **No while/for loops** - iteration is always
recursion + pattern matching on list cons.

### logic_like worked examples

```
% loops - Prolog has NO while/for. The "loop" is recursion with
% a guard separating base case from recursive case.
countdown(0) :- write(0), nl.
countdown(N) :- N > 0, write(N), nl, N1 is N - 1, countdown(N1).

:- countdown(5).
```

```
% functions - Prolog has predicates, not functions. The last-arg-is-
% output convention emulates functions: factorial(N, F) takes N and
% binds F to the result. `is/2` evaluates arithmetic; `=/2` is
% unification (syntactic, doesn't evaluate).
factorial(0, 1).
factorial(N, F) :-
    N > 0,
    N1 is N - 1,
    factorial(N1, F1),
    F is N * F1.

:- factorial(5, R), write(R), nl.
```

logic_like uses: `% line comment` and `/* block comment */` (non-
nesting). Clauses are FACTS (`parent(tom, bob).`) or RULES
(`grandparent(X, Z) :- parent(X, Y), parent(Y, Z).`) - both end in
`.`. Directives `:- Goal.` or `?- Goal.` run a query at load. `,`
is conjunction, `;` is disjunction, `\+` is negation-as-failure.
UPPERCASE-leading identifiers are VARIABLES (`X`, `Foo`); lowercase
are ATOMS (`tom`, `bob`). `[1, 2, 3]` is list literal; `[H | T]` is
head/tail pattern. Lists end in atom `[]`. The arithmetic boundary
is critical: `X is 2 + 3` evaluates and binds X to `5`; `X = 2 + 3`
unifies X with the compound `+(2, 3)` WITHOUT evaluating. Comparison
operators `=:= =\= < > =< >=` evaluate both sides. Output: `write(X)`
prints (atoms unquoted), `nl` prints a newline. **No assignment, no
loops, no functions returning values** - everything is bindings via
unification, multi-clause predicates with guards instead of if/else,
and recursion + backtracking instead of iteration. Closures via
`call/N`: `call(add(5), 3, R)` builds and solves `add(5, 3, R)`.

### python_like

(No worked example block; python_like uses standard Python-style
indentation, `def name(params):` definitions, `:` block-introduction
plus indented bodies. Treat the spec's `function_definition.syntax_example`
and `variable_declaration.syntax_example` as the authoritative shape.)

## What you produce

A JSON object with two keys: `canonical_test_bodies` (required) and
`examples` (optional).

### `canonical_test_bodies` - required

A map from canonical test name to a short program in this language's
surface syntax. Exactly these eight keys, no others:

- `hello_world`
- `arithmetic`
- `variables`
- `conditionals`
- `loops`
- `functions`
- `closures`
- `strings`

Each value is a short program (4-15 lines) that:

1. **Compiles and runs** under this language's parser/codegen/runtime.
 Use only the syntax forms documented in the spec - keywords, comment
 syntax, function declaration form, variable declaration form, loop
 forms, etc. Don't invent new syntax.
2. **Is deterministic.** Same input, same output, every run. No random,
 no time-of-day, no nondeterministic ordering. The overlay validator
 runs your body twice and rejects any whose stdout differs between
 runs. A flaky test is worse than a generic one.
3. **Exercises what the test name implies.** The test infrastructure
 doesn't enforce specific output - the themed body's actual stdout
 becomes the new expected_output. But each test should still cover
 its category: `arithmetic` should exercise +/-/*//, `loops` should
 loop, `closures` should capture state, etc. A pirate `arithmetic`
 test that divides plunder is great; a pirate `arithmetic` test that
 just prints "Yarr!" is not.
4. **Reads in the persona/era/theme voice.** The variable names, the
 comments, the problem domain, AND the printed output all reflect
 this language's identity. A pirate language's `arithmetic` divides
 plunder among crew and prints share amounts. A Stroustrup-1980s
 language's `closures` is a CAD callback. A McCarthy-1962 language's
 `loops` is a teaching-dialect for-loop over a sum-of-squares.

**Constraints:**

- Use the keyword overrides from the spec. If the spec says variables
 are declared with `asset`, write `asset x = 10;` not `var x = 10;`.
- Use the actual statement terminator + block style from the spec
 (semicolons + braces for c_like, parens for s_expression, etc.).
- ASCII only. No em-dashes, en-dashes, or Unicode ellipses
 (the three-character `...` is fine; the single-character variant
 is not). The voice-quality test enforces this and your code will
 be rejected if it has them.
- Don't add explanatory prose around the code. The test body IS the
 output. One program per key, that's it.

### `examples` - optional (target 3-5 entries)

A list of objects, each with:

- `name` - snake_case filename stem (e.g. `crew_pay_calculator`,
 `cad_tessellation_demo`, `mit_six_oh_one_factorial`). The themed
 name matters; this is the entry point readers see in the README's
 examples list.
- `description` - one sentence shown above the code block in the
 README. Modern English, persona-flavored.
- `body` - a longer program (15-50 lines) that does something
 meaningful in the language. Exercises 2-3 stdlib functions
 (`map`/`filter`/`length`/`assoc`/`get`/`keys`/etc., whichever the
 language has). Reads as *this language doing what it's designed
 to do*, not a generic snippet.

Same syntax/keyword constraints as the canonical test bodies. Same
ASCII-only rule.

If you can't think of 3-5 examples that are genuinely themed (not
"generic example with a pirate variable name"), return fewer. Two
good themed examples beat five generic ones. Empty list is also
fine - examples are the bonus; the canonical bodies are the
load-bearing change.

## Style guide

- **Persona shapes the problem domain, not the syntax.** The pirate
 arithmetic test is *about* dividing plunder. It still uses the
 language's actual `+` `-` `*` `/` operators.
- **Examples should feel like real programs.** Not pedagogical
 exercises. A pirate language's example might be a treasure-map
 parser; a corporate one's might be a Q3 deliverable-status report
 generator. The kind of program someone *using* this language would
 actually write.
- **Comments are themed too.** If the language has line-comment
 syntax in its spec, you can use it. Add 1-2 short themed comments
 per test body for flavor. Don't pile them up.
- **Don't repeat the reference template.** If you can't think of a
 themed angle, just produce a clean generic version - that's still
 better than parroting a hardcoded reference. But try first to find
 the angle.
- **Variable names matter.** `crew_count` reads as pirate; `Customer`
 reads as corporate. Stick to ASCII identifiers.

## Output

Return ONLY a JSON object with `canonical_test_bodies` and (optionally)
`examples`. No prose around it. No code fences. No commentary. Just
the JSON.

```json
{
 "canonical_test_bodies": {
 "hello_world": "...",
 "arithmetic": "...",
 "variables": "...",
 "conditionals": "...",
 "loops": "...",
 "functions": "...",
 "closures": "...",
 "strings": "..."
 },
 "examples": [
 {
 "name": "crew_pay_calculator",
 "description": "...",
 "body": "..."
 }
 ]
}
```
