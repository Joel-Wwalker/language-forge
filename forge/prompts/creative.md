# Creative content for the README (variance-improvement expansion)

You're writing six short pieces of voiced prose that get inlined into a
templated README for a generated programming language. The README's
*structure* is fixed; what you produce is the *voice* - the parts that
make this language feel like THIS language, not just another c_like /
s_expression / stack_based / ml_like sibling.

You will get a spec describing the language's options, customization
(persona, era, theme, phrasebook, feature bans), keyword overrides,
and one-line origin story. Use it. Be specific to the spec. Don't
write generic prose that could apply to any language in the family.

## Spec for context

```json
{{SPEC}}
```

## The language's family - surface characteristics

The spec's `options.syntax` field names one of five syntax families.
Each has structurally-different surface shapes. When you reference
syntax in your prose (especially in `example_commentary` which
comments on the example code shown above it), use the FAMILY-CORRECT
forms. Do not describe c_like braces and semicolons in an ml_like
language; do not describe parenthesized prefix forms in a stack_based
language. The structural feature is part of what makes the language
feel like itself.

- **c_like** - curly braces, semicolons terminate statements,
 function/variable declarations with keywords like `func`, `var`,
 imperative loops (`while`, `for`).
 Example: `func add(a, b) { return a + b; }` and `print(x);`.

- **python_like** - indentation-based blocks, no terminators,
 keywords like `def` and `let`/`var`.
 Example: `def add(a, b):\n return a + b` and `print(x)`.

- **s_expression** - every form is `(operator operand ...)`,
 parenthesized prefix notation, code is data, no statements vs
 expressions distinction.
 Example: `(defn add (a b) (+ a b))` and `(print x)`.

- **stack_based** - postfix concatenative, `:` definitions ending in
 `;`, no parameter names (values flow on an implicit stack),
 operators ARE words (`+ - * dup swap`).
 Example: `: square ( n -- n*n ) dup * ;` and `value .`.

- **ml_like** - expression-oriented, `let` / `let rec` bindings,
 `match ... with | pat -> body` pattern matching, `::` cons for
 lists, `;;` terminates top-level items, recursion-forward (no
 while/for loops), ADTs via `type name = Constr of T | ...`.
 Example: `let rec fact n = if n <= 1 then 1 else n * fact (n - 1) ;;`
 and `let result = fact 5 ;; print_any (result) ;;`.

In `example_commentary` (the field that comments on the code shown
above it in the README), refer to the language's actual surface
features as they appear - not as if every language were c_like-shaped.

## What you produce

A JSON object with exactly these six string fields. Every field is the
**same voice** - pick the persona's voice from the spec (or a neutral
clear voice if no persona) and stay in it. Don't drift between fields.

### 1. `readme_intro` (80-180 words)

The first paragraph of the README. The user sees this immediately after
the language name and origin story. Hooks the reader, establishes voice,
gives a sense of what the language is and *why it exists*. Persona-,
era-, theme-flavored - but written in modern English. The phrasebook
applies to *scattered word choices*, not every word.

Open with something concrete. Avoid marketing words ("powerful",
"elegant", "robust", "seamless"). Avoid hedges ("in this fictional
scenario", "though limited in scope").

### 2. `design_philosophy` (60-120 words)

One paragraph explaining *why this language has the feature set it has*.
In the persona's voice. Reference specific spec choices: feature_bans,
typing, memory model, statement_terminator, loop_forms. This is the
designer's authorial reasoning, not marketing.

If `feature_bans` includes `no_loops`, this paragraph might explain why
loops were rejected in favor of recursion. If persona is `hickey`,
emphasize immutability. If era is `1970s`, draw on Pascal/C era ideas.

Don't repeat what `readme_intro` said. Different sentences, different
angle.

### 3. `what_its_good_at` (40-80 words)

Short paragraph naming 2-4 things this language **excels at**. Specific
claims, not generic ones. Not "elegant code" - say something like
"expressing recursive algorithms tersely because of the if-as-expression
form" or "small programs that compose without ceremony, since the
keyword set is tiny."

Reflect the actual options in the spec. A statically-typed language
should claim something type-system-related. A `no_inheritance` language
should claim something composition-related.

### 4. `what_its_bad_at` (40-80 words)

Short paragraph naming 1-3 honest **limitations**. This is the most
distinctive field because most generated content avoids self-criticism.
Be honest. Be specific. Voiced.

A statically-typed language might note: "the type system can be onerous
for quick scripts." A `no_mutation` language might note: "interactive
programs require workarounds since state has to thread through
arguments." A pirate-themed language: "the joke wears thin past 200
lines."

Don't trash the language. Just acknowledge what its choices give up.

### 5. `example_commentary` (50-100 words)

Annotates the language's hello-world example. The example itself is
rendered separately from your spec; this field is the persona's
**commentary on** it. Point at something specific in the spec - a
keyword override, a statement terminator, a typing choice - and explain
the choice from the designer's perspective.

"Notice the `yarrn` keyword instead of `func` - we wanted function
declarations to feel like a captain announcing the next maneuver, not a
clerical decree." That kind of thing.

### 6. `common_mistake` (40-80 words)

Warn about one mistake a new user is likely to make in this specific
language. Specific to the design choices. A dynamically-typed language
might warn about type confusion in arithmetic. A `no_null` language
might warn about returning sentinel values instead of using the empty
list. Voiced.

## Style guide

- Each field is the same voice. If `readme_intro` is folksy, all six
 are folksy. If it's clipped and technical, all six are clipped and
 technical.
- Be specific to this spec. Don't write content that could apply to
 any language. If your `what_its_bad_at` doesn't reference at least
 one option in the spec, rewrite it.
- The phrasebook (pirate, Shakespearean, Latin, cozy, corporate)
 applies to *scattered word choices*, 2-4 times per field. Not every
 word. Modern English with phrasebook flavor sprinkled, not a full
 translation.
- Sections don't repeat each other. If `readme_intro` and
 `design_philosophy` say the same thing in different words, you've
 done it wrong.
- Don't repeat the language name in every section. Once or twice
 total across all six fields is enough.

## Output

Return ONLY a JSON object with the six keys. No prose around it. No
code fences. No commentary. Just the JSON.

```json
{
 "readme_intro": "...",
 "design_philosophy": "...",
 "what_its_good_at": "...",
 "what_its_bad_at": "...",
 "example_commentary": "...",
 "common_mistake": "..."
}
```
