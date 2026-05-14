# Kata pack prompt

Produce 5 katas for the language described below: 2 easy, 2 medium, 1 hard. Each kata is a small, self-contained programming problem the user solves by writing one function in this language. The user submits a solution; an automated checker runs it against your test cases.

## CRITICAL: drops are silent. The 4 ways katas die:

1. **Phrasebook violation.** If `spec.customization.natural_language` is set, the parser ONLY accepts those templates. Standard `var`, `func`, `if`, `while`, `return` will fail. Example: if `var_decl = "make <name> equal <value>."` is set, write `make total equal 0.`, NOT `var total = 0;`. Reread the templates before writing any code.
2. **Wrong keyword spellings.** Use `spec.function_definition.keyword`, `spec.variable_declaration.keyword`, `spec.boolean_keywords.true/false`, `spec.null_keyword` EXACTLY. If `boolean_keywords.true = "yes"`, your test `expected` must say `yes`, not `true`.
3. **Wrong stdlib.** Use only what's in `spec.stdlib.functions`. The list is not exhaustive of Python builtins. If `map` isn't there, don't write `map(...)`.
4. **Wrong syntax family.** If `spec.options.syntax == "s_expression"`, EVERYTHING is in prefix form: `(defn fname (a b) (+ a b))` not `func fname(a, b) { return a + b; }`. Test calls are `(fname arg arg)` not `fname(arg, arg)`. Lists print as `(1 2 3)` not `[1, 2, 3]`. Booleans print as `true`/`false` (unquoted symbols), null as `nil`. If `spec.options.syntax == "stack_based"` (Forth-flavored), EVERYTHING is in postfix form: `: fname ( a b -- a+b ) + ;` not `func fname(a, b) { return a + b; }`. Test calls are `arg arg fname` not `fname(arg, arg)`. Print with `.` (number) or `." text"` (string). Arithmetic + comparison are postfix function calls: `2 3 +` not `2 + 3`.

## Resolved spec

```json
{{SPEC}}
```

## Before writing code, copy these from the spec above:

- `function_definition.syntax_example` (your function template, c_like or phrasebook form)
- `variable_declaration.syntax_example` (your variable declaration form)
- `statement_terminator` (`;` or newline)
- `boolean_keywords.true` / `.false` (exact spellings to use in `expected`)
- `customization.natural_language` (if present, every statement uses its templates)

If a phrasebook is present, your reference solution must read like prose. Mental check before you submit: does this code match the templates, or does it use `var`/`func`/`if`/`while`?

## What you must produce

A JSON object with one top-level array, `katas`, of exactly 5 entries:

```
{
  "katas": [
    {
      "id": "snake_case_id",
      "title": "Short memorable title",
      "difficulty": "easy",
      "problem": "1-2 sentence problem statement in plain English.",
      "function_name": "the_function_user_must_write",
      "starter_code": "function skeleton with empty body",
      "reference_solution": "complete working solution",
      "tests": [
        {"call": "the_function_user_must_write(some, args)", "expected": "expected stdout"},
        ...
      ]
    },
    ...
  ]
}
```

## Constraints

- `starter_code` and `reference_solution` MUST use this language's exact syntax. Honor `comment_syntax`, `function_definition.keyword`, `variable_declaration.keyword`, `block_style`, `statement_terminator`, and `boolean_keywords`. If the spec has a `customization.natural_language` phrasebook, write the code using THOSE templates.
- `function_name` is a single identifier, snake_case if `naming_convention=snake_case`, camelCase if camelCase, etc.
- Each test's `call` is a valid expression in this language. The checker will run the user's solution then print(`call`); `expected` is the literal stdout that print will produce.
- Tests should cover:
  - happy path (typical input)
  - edge case: empty / minimum input
  - edge case: single element
  - one or two more
- 4 to 7 tests per kata.

## Self-check (do this before returning)

For each kata:
1. Mentally execute `reference_solution` against each test's `call`.
2. The expected stdout must EXACTLY match what the language's print form produces (see `spec.print_form` - typically `print(<args>)` for c_like, `(print <args>)` for s_expression, `<args> .` for stack_based, `print_any (<args>) ;;` for ml_like; phrasebooks may override). Booleans use the spec's `boolean_keywords`. Lists use the language's runtime form, typically `[1, 2, 3]` but check the spec's list formatter.
3. If reference + expected disagree, fix one until they agree.

Generated katas are about to be run end-to-end through the actual compiler. If a reference solution fails its own tests, the kata is dropped silently. Don't waste output on katas you didn't validate mentally.

## Difficulty rubric

- **easy**: one or two stdlib calls. No edge cases beyond empty/single. Examples: sum a list, count vowels, double each item.
- **medium**: needs a loop AND a condition. Examples: prime check, palindrome, longest run.
- **hard**: needs algorithmic thinking. Examples: balanced parentheses, longest common prefix, simple expression evaluator.

## Output format

Return ONLY a tool-use call to the `emit_spec` tool with the JSON object. No prose, no explanation.
