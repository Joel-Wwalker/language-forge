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
