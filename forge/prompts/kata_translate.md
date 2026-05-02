# Kata translation prompt

You are translating a fixed set of curated LeetCode-style problems into the target language's actual syntax. The PROBLEMS are mandatory and must be preserved verbatim. The CODE (reference solutions, starter code, test calls, expected outputs) must be written in this specific language's dialect.

## CRITICAL: return EXACTLY {{KATA_COUNT}} katas, one per problem below, with these EXACT ids in this EXACT order:

{{EXPECTED_IDS}}

DO NOT return duplicates of any single problem. DO NOT skip any problem. DO NOT invent extra problems with new ids. The output array length MUST equal {{KATA_COUNT}}. If you can't fully translate a problem, return your best attempt anyway, the system will validate each one independently.

## Helpers MUST persist (LeetCode pattern: provide the data structures):

For tree problems, the kata's reference includes constructors like `node(v,l,r)` and `leaf(v)`. For linked-list problems, it includes `to_ll(items)` and `ll_to_list(head)`. The TESTS use these helpers: `max_depth(node(1, leaf(2), leaf(3)))` only works if `node()` and `leaf()` are defined.

When you translate, you MUST include those same helpers (translated) in the `reference_solution`. Otherwise the tests reference undefined functions and the kata is unusable. Match the LeetCode pattern: the user only writes the algorithm; the data-structure constructors are provided.

If the canonical c_like reference defines auxiliary functions like `node`, `leaf`, `to_ll`, `ll_to_list`, `count_chars`, `helper`, etc., translate ALL of them and include ALL of them in the new `reference_solution`. The `starter_code` should also include the helpers (without the algorithm body) so the user can use them while solving.

## CRITICAL: drops are silent. The 3 ways translations die:

1. **Phrasebook violation.** If `spec.customization.natural_language` is set, the parser ONLY accepts those templates. Standard `var`, `func`, `if`, `while`, `return` will fail. Example: if `var_decl = "make <name> equal <value>."` is set, write `make total equal 0.`, NOT `var total = 0;`. Reread the templates before writing any code.
2. **Wrong keyword spellings.** Use `spec.function_definition.keyword`, `spec.variable_declaration.keyword`, `spec.boolean_keywords.true/false`, `spec.null_keyword` EXACTLY.
3. **Feature bans.** If `spec.customization.feature_bans` includes `no_mutation`, you cannot write `i = i + 1`. Use recursion. If it includes `no_loops`, no `while`/`for`. Adapt the algorithm.
4. **Wrong stdlib.** Use only what's in `spec.stdlib.functions`. If the language uses different names (e.g. `length` vs `len`, `append` vs `push`), use the language's actual names.

## Resolved spec

```json
{{SPEC}}
```

## Curated problems to translate

Each entry below is a problem you MUST preserve. The `id`, `title`, `difficulty`, `problem`, and `function_name` must appear UNCHANGED in your output. The `tests` describe the SEMANTIC behaviour: each test_spec has an `input` (what the function is called with, in plain English / canonical-form syntax) and a `returns` (what value the function must return, in plain English / canonical-form syntax).

YOUR JOB is to write, for each problem:
- `starter_code`: a function skeleton with empty body, in this language's syntax
- `reference_solution`: a complete working solution, in this language's syntax. If the language bans mutation, use recursion; if it bans loops, use recursion.
- `tests`: each test object has a `call` string (a function call in THIS language's syntax that produces the test input) and an `expected` string (what `print(<call>)` will literally produce as stdout in THIS language).

```json
{{PROBLEMS_JSON}}
```

## Verified working sample from this language

This is real code that compiles and runs. Use it as ground truth for syntax / punctuation / keyword decisions. If your reference differs in punctuation or keyword spelling from this sample, you have a bug.

```
{{SAMPLE}}
```

## Output format

Return a JSON object with a single top-level array `katas`, ordered identically to the input problems list. Each entry MUST have these exact fields, with the `id`, `title`, `difficulty`, `problem`, and `function_name` taken VERBATIM from the input:

```
{
  "katas": [
    {
      "id": "two_sum",
      "title": "Two Sum",
      "difficulty": "easy",
      "problem": "(unchanged from input)",
      "function_name": "two_sum",
      "starter_code": "...this language's syntax...",
      "reference_solution": "...this language's syntax...",
      "tests": [
        {"call": "two_sum(...)", "expected": "what print produces in this language"},
        ...
      ]
    },
    ...
  ]
}
```

## Self-check (do this before returning)

For each translated kata:
1. Mentally execute `reference_solution` against each test's `call`.
2. The expected stdout must EXACTLY match what `print(<call>)` produces in this language's runtime. List formatting, boolean spelling, null spelling: all must match this language's print formatter.
3. If reference + expected disagree, fix until they agree.
4. Re-verify the syntax matches the verified sample's punctuation/keywords.

A translated kata that fails its own tests is dropped silently. The user wants the LeetCode classics on their language; your job is to deliver exactly that.

## Output format

Return ONLY a tool-use call to the `emit_spec` tool with the JSON object. No prose, no explanation.
