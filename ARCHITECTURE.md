# Language Forge — Architecture & Capabilities

A complete tour of the codebase: what each module does, how they fit
together, what the user gets to do, and where the seams are if you want
to improve something.

---

## 1. What is Language Forge?

A tool that **invents a working programming language** from a small set
of design choices, then **lets you write and grade code in it**.

You pick three core options (syntax family, typing discipline, memory
model) plus optional layers (keyword themes, persona, era, natural-
language phrasebook, feature bans). Forge:

1. **Builds a spec** from your choices.
2. **Calls an LLM resolver** to fill in spec gaps (keyword spellings,
   grammar details, stdlib semantics).
3. **Calls an LLM creative pass** (gen-creative) to produce 6 voiced
   README sections (intro, design philosophy, good-at, bad-at,
   example commentary, common mistake).
4. **Calls an LLM idioms pass** (gen-idioms) to produce themed
   canonical-test bodies + themed example programs.
5. **Generates per-component code** by templating from a hand-written
   reference compiler when possible (toylang / lisplang / forthlang /
   mllang) or via per-component LLM calls (lexer, parser, codegen,
   runtime, stdlib, tests, readme, language reference) when no
   reference exists for the family.
6. **Verifies** the generated language against eight canonical programs.
7. **Repairs** any broken component by re-asking the LLM with the
   actual error.
8. **Lets you write programs** in the new language via a Pyodide
   in-browser REPL or a real CLI.
9. **Solves LeetCode-style katas** in the new language (auto-graded,
   with sample tests visible and hidden tests run on Submit).

Everything is a real Python package: `pip install -e .` and the
language gets its own `lang-name` CLI command.

**Five syntax families** are wired up: `c_like`, `python_like`,
`s_expression`, `stack_based`, `ml_like`. Each of the four
non-`python_like` families has a **hand-written reference compiler**
that lives under `generated/`. They're the golden children — every
test asserts against them and every templated language in their family
is built from them via the substitution layer.

The pipeline is family-aware end-to-end: gen-creative + gen-idioms +
the README's "At a glance" renderer + `_wrap_with_test_prints` all use
per-family dispatch + spec-driven `<args>` template substitution so an
ml_like generated language reads as pattern-matching + recursion-forward,
not "c_like with different keywords." See section 12 for the variance
pipeline details.

---

## 2. Top-level project layout

```
language-forge/
├── forge/
│   ├── __main__.py              # `python -m forge` entry point
│   ├── cli.py                   # argparse CLI: create / verify / repair / gui
│   ├── scaffold.py              # writes pyproject + entry shim for new langs
│   ├── orchestrator/            # the brains
│   │   ├── spec_builder.py
│   │   ├── coherence.py
│   │   ├── resolver.py          # LLM call #1: fill in spec gaps
│   │   ├── creative.py          # LLM call #2: 6 voiced README sections
│   │   ├── idioms.py            # LLM call #3: themed canonical bodies + examples
│   │   ├── generator.py
│   │   ├── verifier.py
│   │   ├── repair.py
│   │   ├── llm_client.py
│   │   ├── llm_client_claude_cli.py
│   │   ├── providers.py
│   │   ├── personas.py / presets.py / themes.py / phrasebooks.py / bans.py
│   │   ├── katas.py
│   │   ├── kata_packs.py
│   │   ├── kata_translator.py
│   │   ├── mechanical_translator.py
│   │   ├── substitution.py      # per-family keyword override substitution
│   │   ├── case_analysis.py
│   │   └── pair_programmer.py
│   ├── catalog/                 # Phase 2-3: batch + curation + dedup
│   │   ├── batch.py             # `python -m forge.catalog.batch`
│   │   ├── curate.py            # score + dedup + load into SQLite
│   │   ├── backfill.py          # rehydrate customization columns
│   │   ├── runner.py            # per-slot subprocess driver
│   │   ├── db.py / dedup.py / quality.py / smoke_test.py
│   │   └── slots/               # slot plans (v1_phase1.json, experiment_ml_family.json, ...)
│   ├── prompts/                 # Markdown LLM prompts (one per call)
│   ├── templates/               # Jinja2 + static templates (REPL, pyproject, ...)
│   └── gui/
│       ├── app.py               # Flask app, all REST endpoints
│       ├── catalog_routes.py    # Phase 3: catalog curation UI routes
│       ├── samples.py           # Curated sample programs
│       └── static/              # index.html / app.js / catalog.{html,js,css} / style.css
├── generated/                   # Output dir for languages
│   ├── toylang/                 # Hand-written c_like reference
│   ├── lisplang/                # Hand-written s_expression reference
│   ├── forthlang/               # Hand-written stack_based reference
│   ├── mllang/                  # Hand-written ml_like reference
│   ├── stacky/                  # stack_based test fixture
│   └── <other langs>/           # LLM-generated (.gitignored except the 5 above)
├── schemas/                     # JSON-Schema for resolved specs
├── tests/                       # pytest suite (1005 tests) + tests/audit/ deep audits
└── ARCHITECTURE.md              # this file
```

---

## 3. Two main user journeys

### Journey A — "Make me a programming language"

1. User opens **GUI** (`forge gui`) → Create tab.
2. Picks `syntax` / `typing` / `memory` (radio buttons), optional
   layers (persona, era, theme, ban, phrasebook).
3. Clicks **Create**. Server starts a background generation job.
4. SSE stream shows per-component progress (Resolving spec → Generating
   lexer → parser → codegen → runtime → stdlib → tests → readme).
5. On finish, language appears in **Library**. Has its own
   `generated/<name>/` directory with full compiler.
6. User can:
   - Run programs in the **Playground** tab against any language.
   - Open the in-browser **Pyodide REPL** (no install needed).
   - Download a `<lang>-0.1.0.zip` of the project.
   - **Repair** the language if some canonical test failed.
   - **Delete** the language.

### Journey B — "Solve LeetCode problems in this weird language"

1. User goes to **Katas** tab.
2. Picks a language + a curated pack ("LeetCode classics").
3. Clicks **📚 Load pack**. Server:
   - Tries the curated reference straight on the language.
   - For mismatched languages, mechanically transpiles via toylang's
     parser + the right Backend (CLike / Phrasebook / PythonLike).
   - For ones the mechanical can't handle, asks the LLM to translate
     with budget caps + escalating fix-up.
   - For anything still failing, falls back to mechanical
     case-analysis (hardcodes test answers).
   - Stub-rescue is the absolute last resort.
4. User clicks a problem in the library, reads the description (with
   sample tests visible), writes code, hits **▶ Run** (sample tests
   only, full per-test results) or **✓ Submit** (hidden tests, first-
   failure-only).
5. On Submit pass, the **Solution** tab unlocks and shows the reference.
6. The 💬 Ask AI button hands the problem off to the language-aware
   pair programmer chat in the Playground.

---

## 4. The orchestrator — module by module

### 4.1 `spec_builder.py` — turn options into a spec

**Public API**
- `Options` (TypedDict): the user's input — syntax/typing/memory plus
  every optional axis.
- `build_spec(options, lang_name, *, customization=None, persona=None,
   era=None, keyword_theme=None, feature_bans=None,
   hostile_constraints=None, phrasebook=None,
   natural_language=None) -> dict`
- `validate_spec(spec)`: JSON-Schema validation; raises on bad spec.
- `load_schema()`: returns the JSON Schema dict.

**What it does**
1. Starts with hard-coded base specs per `syntax` family: `_C_LIKE_BASE`,
   `_PYTHON_LIKE_BASE`, `_S_EXPRESSION_BASE`, `_STACK_BASED_BASE`,
   `_ML_LIKE_BASE`. Each declares the family's surface conventions
   including a `<args>`-template `print_form` (e.g. `print(<args>);`
   for c_like, `(print <args>)` for s_expression,
   `print_any (<args>) ;;` for ml_like).
2. Layers `_typing_overlay()` and `_memory_overlay()` deltas on top.
3. Applies extended options (`comment_style`, `string_literals`,
   `numeric_literals`, `default_mutability`, `error_handling`,
   `loop_forms`, `multiple_returns`, `boolean_evaluation`,
   `naming_convention`, `null_model`).
4. Applies preset blocks (era, theme keyword swaps, persona design
   notes).
5. Applies customization (keyword/operator overrides, file_extension
   override, additional tests, extra design notes,
   `natural_language` phrasebook templates, feature_bans).
6. Validates final spec against the JSON Schema.

**Use case**: Single source of truth for "what does this language
look like." Everything downstream (resolver, generator, prompts,
mechanical translator, case analysis, GUI) reads from this dict.

### 4.2 `coherence.py` — catch impossible combos before LLM cost

A dozen rule functions check for self-contradictions in option combos.
Two severity levels:

- **`error`** — combo is genuinely impossible (e.g. `feature_bans=[no_exceptions]` plus `error_handling=exceptions`). Build aborts before the LLM is called.
- **`warning`** — combo is allowed but unusual or self-fighting (e.g. `default_mutability=immutable` plus `boolean_evaluation=eager` — eager eval is observable through side-effects, but immutable langs have fewer of those). Recorded in `design_notes` so the LLM sees it.

**Public API**
- `check(opts) -> list[Issue]`
- `errors(issues) / warnings(issues)` filters
- `CoherenceError(ValueError)` raised on hard incoherence

**Use case**: prevents wasted LLM calls on impossible specs and gives
the resolver context about quirky combos.

### 4.3 `resolver.py` — fill in spec gaps with the LLM

```
resolve(base_spec, *, client) -> dict
```

Loads `forge/prompts/resolver.md`, interpolates the spec, calls
`client.call_json(prompt, schema=load_schema(), tag="resolver")`. The
LLM returns a fully-resolved spec including:
- exact keyword spellings (`if` / `else` / `while` / etc.)
- complete grammar details (operator precedence specifics, etc.)
- stdlib function names + signatures
- spec.design_notes additions

**Use case**: bridges the gap between high-level options (`syntax=c_like`) and the per-token decisions a generator needs.

**Cache discipline**: `RESOLVER_PROMPT_VERSION` + `RESOLVER_SCHEMA_VERSION`
constants are folded into the cache key; the cache is keyed on a
content-hash of the input spec with lang_name + file_extension +
lineage stripped (so two slots sharing options + customization hit one
LLM call between them). Bumping either version invalidates stale
entries — done several times to absorb schema-description tightening
(structural-variance-channel Seam 0 + the Stage F retry).

### 4.4 `creative.py` — themed README content (LLM call #2)

```
creative_content(spec, *, client) -> dict
```

The second LLM call in the per-language pipeline. Produces six voiced
prose sections that get inlined into the templated README:

- `readme_intro` (80-180 words): the headline paragraph
- `design_philosophy` (60-120 words): why this language has its feature set
- `what_its_good_at` (40-80 words): 2-4 specific strengths
- `what_its_bad_at` (40-80 words): 1-3 honest limitations (the most
  distinctive field; most generated content avoids self-criticism)
- `example_commentary` (50-100 words): persona's commentary on the
  hello-world example
- `common_mistake` (40-80 words): warning for new users

Per-field word-count validation (±50% of target), required-headline
fallback discipline (any failure returns `{}` and the templated
renderer falls back to no-creative-content rendering), content-hash
caching keyed on prompt version + stripped spec.

**`CREATIVE_PROMPT_VERSION`** is currently 3:
- v1: original 1-field intro
- v1 → v2 (variance-improvement): expanded to 6 fields
- v2 → v3 (structural-variance-channel Seam 6): added per-family
  surface-characteristics block so `example_commentary` references
  the right family syntax (ml_like uses `;;` not `;`, pattern
  matching not if/else cascades)

**Use case**: makes a generated c_like language feel different from
another c_like language. The personality lives in these six sections
plus the keyword overrides — the templated skeleton stays the same.

### 4.5 `idioms.py` — themed canonical-test bodies (LLM call #3)

```
idiomatic_content(spec, *, client) -> dict
```

The third LLM call. Produces themed replacements for each of the 8
canonical test bodies plus 0-5 longer themed example programs. Goal:
the language's `tests/arithmetic.<ext>` reads in the persona's voice
(a pirate divides plunder, a Stroustrup-1980s CAD callback computes
geometry, a McCarthy-1962 teaching exercise sums squares) without
breaking smoke-test correctness.

Per-body validation: each themed body is compiled + run twice
(determinism check); accepted bodies overwrite both the source file
AND the `<name>.expected_output.txt`, so the smoke loop keeps
working. Rejected bodies revert to the reference template silently.

**`IDIOMS_PROMPT_VERSION`** is currently 3:
- v1: original prompt with hand-picked output expectations
- v1 → v2: stopped requiring themed bodies to match the reference's
  expected_output (themed body's actual stdout becomes the new
  expected_output)
- v2 → v3 (structural-variance-channel Seam 2): added per-family
  worked-example blocks. For each of c_like / s_expression /
  stack_based / ml_like, 2 actually-parseable reference compiler
  canonical tests are inlined into the prompt so the LLM has
  grammar-accurate anchors instead of paradigm-shaped guesses

Themed-acceptance per family (post-structural-variance-channel):

| family | rate |
| --- | --- |
| c_like | 94% |
| s_expression | 100% |
| stack_based | ~50-75% (varies; forthlang codegen brittle on themed strings) |
| ml_like | 25% (Seam 8 follow-up identified; resolver still rewrites `options.loop_forms`) |

Rejected bodies fall back to the reference template, so the overall
smoke pass rate stays at 100% even when themed-acceptance is modest.

### 4.6 `substitution.py` — per-family keyword override engine

The substitution layer that the templated-from-reference path uses
to apply spec-driven keyword overrides to BOTH the parser grammar
AND the canonical test sources at once. Phase 1.5 Stage A introduced
the per-family `KEYWORD_ROLES_BY_FAMILY` dispatch:

```python
KEYWORD_ROLES_C_LIKE       = ("var", "func", "if", "else", "while", ...)
KEYWORD_ROLES_S_EXPRESSION = ("if", "else", "true", "false", "null")
KEYWORD_ROLES_STACK_BASED  = ("if", "else", "then", "begin", ...)
KEYWORD_ROLES_ML_LIKE      = ("let", "rec", "in", "if", "then", "else",
                              "match", "with", "type", "of", "fun", ...)
```

So a themed mllang variant with `customization.keyword_overrides =
{"let": "define"}` gets `define rec fact n = ...` in both the
templated parser grammar's anonymous string literals AND in
`tests/functions.ml`'s source.

Multi-char operators (`::`, `->`, `;;`, `=`, `|`, `^`, `+.`, `*.`)
are explicitly excluded from substitution — they're not word-boundary
tokens and substituting them would require rewriting the parser's
operator tables, not just grammar strings.

### 4.7 `generator.py` — generate per-component code in parallel

The biggest single module. **Key public function**:

```
generate_all(spec, output_root="generated", *, client, on_progress=None) -> Path
```

**What it does**
1. Computes the dependency graph across components: lexer → parser →
   typechecker (static only) → codegen → runtime → stdlib → tests →
   readme → language_reference.
2. Runs the graph in **parallel waves** via ThreadPoolExecutor. Each
   wave's components launch concurrently; the next wave waits for the
   previous to finish. Cuts wall-clock time roughly in half vs.
   sequential.
3. For each component, calls `_generate_code_component()` which:
   - Loads the prompt from `forge/prompts/<name>.md`
   - Interpolates with the spec
   - Pulls in **sibling context** (e.g. parser sees the lexer's
     finished grammar)
   - Calls `client.call_code()` (LLM with code-extraction)
   - Writes to `<lang>/<name>.py`
4. Tests get special treatment: `_generate_tests()` asks for a JSON
   blob mapping filenames to source so the LLM can emit multiple
   files in one call.
5. Renders Jinja templates (`pyproject.toml`, `compiler_entry.py`,
   `runtime_shim.py`, the standalone REPL HTML, INSTALL.md) per
   language.
6. Applies post-generation fixups:
   - **`apply_runtime_shim`**: drops a `runtime_shim.py` next to
     runtime that backfills any Python builtins the runtime might
     accidentally call without import.
   - **`apply_codegen_prelude_patch`**: scans codegen output for
     references to runtime helpers and ensures the emitted Python
     imports them.
   - **`_translate_comments`**: converts `// comment` to `# comment`
     or `/* */` per the spec's `comment_syntax`.
7. Calls `_emit_examples()` to ship sample programs that compile-check
   in the new language.
8. Always re-renders the standalone REPL HTML.

**Use case**: turns a resolved spec into a runnable directory.

### 4.8 `verifier.py` — does the generated language actually work?

```
verify(lang_dir) -> VerificationReport
```

For each canonical test in `<lang>/tests/`:
1. Compile with `<lang>/compile.py`.
2. Run the generated `.out.py`.
3. Compare stdout to the matching `<test>.expected_output.txt`.
4. Attribute failures (`_attribute_failure(stderr, stage)`) to a
   likely component: lexer / parser / typechecker / codegen / runtime.

**Returns** a `VerificationReport(lang_dir, file_extension,
all_passed, tests, missing_canonical)` with `to_dict()` and
`summary()` for display.

**Use case**: deterministic gate. If `all_passed=False`, the GUI shows
a Repair button.

### 4.9 `repair.py` — fix the broken component

```
repair_run(lang_dir, *, client) -> VerificationReport
```

Walks a verify-fix-verify loop, capped at N iterations:

1. Verify. If all pass, return.
2. `_pick_component(report, spec)`: pick which file is most likely
   responsible for the failures. Reads stderr to choose lexer vs.
   parser vs. codegen vs. runtime.
3. Load the prompt `forge/prompts/repair.md`, fill in:
   - Current source of the broken file
   - The failing test's source + expected stdout + actual stderr
   - Sibling files (parser sees lexer, etc.)
4. LLM rewrites the file. Save it. Loop.

`_pick_alternate()` lets it switch components if the same one fails
N times in a row (avoids spinning on a wrong attribution).

**Use case**: generated languages often have tiny LLM bugs (an
off-by-one, a missing case in `visit_*`). Repair fixes most of them.
Also exposed via the GUI's per-language **Repair** button.

### 4.10 `llm_client.py` — talking to Anthropic

`LLMClient(api_key=None, model=None, log_dir=None)` wraps the
`anthropic` SDK with:

- **`call_json(prompt, schema, *, tag, system, max_retries)`**:
  forces structured output via tool-use, validates against the
  JSON schema, retries with the validation error text on failure.
- **`call_code(prompt, *, tag, system, max_retries)`**: extracts
  the first fenced `python` (or other-lang) block from the response.
- **`call_chat(prompt, history, *, tag, system, max_retries)`** (added
  for the pair programmer): multi-turn chat with the user's history
  appended.
- Logs every call to `<log_dir>/<tag>.<timestamp>.json` for offline
  debugging.

`llm_client_claude_cli.py` mirrors the same interface but shells out to
the `claude` CLI from a Claude.ai/Code subscription. `providers.py`
picks one or the other based on env (`ANTHROPIC_API_KEY` set →
api; else `claude` on PATH → claude_cli).

**Use case**: every LLM call in the codebase goes through this. Single
seam for retries, logging, schema enforcement.

### 4.11 `personas.py / presets.py / themes.py / phrasebooks.py / bans.py`

Five preset libraries, each with `list_*()` returning a compact list
for the GUI picker plus a `get_*()` or `apply_*()` for use in
`spec_builder`.

| File | What it adds |
|---|---|
| `personas.py` | 8 designer personas (Dijkstra, McCarthy, Hickey, Stroustrup, Wirth, Wadler, Matz, Ousterhout). Adds a system-prompt block + design-notes flavor. |
| `presets.py` | 5 era presets (1960s/70s/80s/2000s/2020s). Each overlays defaults like "1960s = static, panic_only, decimal_only". |
| `themes.py` | 5 keyword-theme overrides (pirate, shakespearean, corporate, latin, cozy). E.g. `func → capt'n`. |
| `phrasebooks.py` | 4 natural-language templates (english_storybook, shakespeare, child_speak, ritual). Replaces statement forms with prose: `var x = 0;` → `make x equal 0.`. |
| `bans.py` | 6 feature bans (no_null, no_exceptions, no_mutation, no_loops, no_inheritance, no_global_state). Adjusts options + prompt block. |

**Use case**: rapid one-click flavor changes. Most are surface-deep
(persona is mostly tone) but phrasebooks and bans do real semantic
work.

### 4.12 `katas.py` — the kata core

**Public API**
- `generate_katas(spec, lang_dir, client, on_progress=None, *,
   fix_attempts=2, time_budget_s=120.0) -> dict`
- `_self_validate(kata, lang_dir, spec) -> (ok, reason)`
- `check_solution(spec, lang_dir, kata, user_code) -> dict`
- `_batch_validate(katas, lang_dir, spec)`: fast-path single-program
  validation of a whole pack
- `load_pack(lang_dir) -> dict | None`

**What it does**
1. Asks the LLM to invent a fresh kata pack tailored to the language
   (the ✨ Generate button).
2. Self-validates each kata's reference solution by running it
   through the language's actual compiler with `print(<test.call>)`
   appended for each test.
3. Compares stdout lines to each `expected`. Drops any kata whose
   own reference fails.
4. Per-kata fix-up loop: re-asks the LLM with the actual error.
   `time_budget_s` caps total wall time.
5. Persists surviving katas to `<lang>/katas.json`.

`check_solution` runs the user's code through the same wrapper. For
stub-rescued katas (empty tests), reports `stage=no_tests` with a
helpful message instead of grading.

`_batch_validate` is a one-shot speed path: concatenate all references
+ all print lines into one program, run once, partition stdout by
sentinel lines. ~10× faster than per-kata validation.

### 4.13 `kata_packs.py` — curated LeetCode classics

Hand-written pack of 12 problems with full metadata:

| Field | Purpose |
|---|---|
| `id` | stable identifier |
| `title`, `difficulty` | UI display |
| `tags` | filter chips (array, hash-table, two-pointer, etc.) |
| `problem` | description |
| `function_name` | what the user must define |
| `examples` | visible examples (input/output/explanation) |
| `constraints` | input constraints |
| `acceptance_rate` | indicative stat for the library list |
| `starter_code` | initial editor content |
| `helpers` | code prepended at test time (LL/tree node constructors) |
| `reference_solution` | golden algorithm |
| `tests` | full test suite (sample + hidden) |
| `sample_test_indices` | which tests are visible / Run executes |

Two variants:
- **`CLASSICS_C_LIKE`**: iterative; works on c_like + dynamic + mutation.
- **`CLASSICS_C_LIKE_RECURSIVE`**: recursion-only; works on no_mutation
  languages.

`get_classics_for(spec)` auto-picks the right variant. `PACKS = {"classics": ...}` is the registry; `list_packs()` gives the GUI dropdown options.

### 4.14 `mechanical_translator.py` — c_like → target, no LLM

The fast path that handles most languages without any LLM call.

**Public API**
- `can_handle(spec) -> Backend | None`: returns a backend instance
  if mechanical can handle the language, else None (caller falls back
  to LLM).
- `transpile(c_like_source, spec) -> str | None`: parses c_like
  source via toylang's grammar, walks the tree, emits target syntax.
- `transpile_kata(kata, spec) -> dict | None`: full kata translation.
- `transpile_and_validate(kata, spec, lang_dir)`: also runs
  `_self_validate` against the target language.
- `ensure_runtime_string_support(lang_dir)`: idempotent patch that
  adds `if isinstance(coll, str): return coll[k]` to a generated
  language's `toy_get` if missing. Critical for string-iteration
  classics.
- `_rederive_expected(kata, spec, lang_dir)`: runs the reference,
  captures actual stdout, replaces the kata's `expected` strings.
  Absorbs print-formatter differences across languages.

**Three Backends**
| Backend | Targets | Emits |
|---|---|---|
| `CLikeBackend` | vanilla c_like (toylang, democ, etc.) | `func name(a, b) { ... }` with `;` terminators |
| `PhrasebookBackend` | c_like + `customization.natural_language` (kidX) | substitutes into `var_decl: "make <name> equal <value>."`, etc. |
| `PythonLikeBackend` | python_like + dynamic | `def name(a, b):\n    ...`, no semicolons, indented blocks |

`can_handle` bails on:
- `typing=static` (would need type inference)
- `feature_bans` containing `no_mutation` / `no_loops` (need recursion
  conversion — handled by `CLASSICS_C_LIKE_RECURSIVE` variant)
- `python_like` + phrasebook (rare combo, LLM is safer)

### 4.15 `kata_translator.py` — LLM translation when mechanical can't

```
translate_pack(pack_template, spec, lang_dir, client, *, on_progress,
               fix_attempts=3, mechanical=True, time_budget_s=90.0) -> dict
```

The fall-through ladder:

1. **Mechanical** (if `can_handle`) → ms per kata, no LLM.
2. **Batch translation**: one LLM call asking for all 12 katas in
   the target's dialect. Schema sized to the pack's actual length
   (sized to handle the original "12 of two_sum" duplicate-id bug).
3. **Dedupe + ID alignment**: if LLM returned duplicates, keep first;
   if returned IDs not in input, drop them.
4. **Escalating fix-up** (3 attempts per failing kata, parallel):
   - Attempt 1: standard "fix this error using the verified sample"
   - Attempt 2: "try a different algorithmic approach"
   - Attempt 3: case-analysis (LLM-driven hardcoded answers)
5. **Per-kata fresh translation** (only if batch never returned that
   kata): full LLM attention on one problem at a time.
6. **Single-test reduction**: simpler ask, just produce one test's
   answer.
7. **Mechanical case-analysis fallback** (`case_analysis.py`): always
   succeeds for Turing-complete targets.
8. **Stub-rescue** (`_stub_rescue`): empty tests + comment-only
   reference. Last resort.

Every step is gated by `time_budget_s` so a stubborn LLM can't burn
unlimited time. The user sees results in 90-120s max regardless.

### 4.16 `case_analysis.py` — guaranteed-working fallback reference

When all else fails, generate a function that hardcodes the answer
for each test:

```c_like
func two_sum(nums, target) {
    if (target == 9 && len(nums) == 4 && get(nums, 0) == 2 && ...) {
        return list(0, 1);
    }
    if (target == 6 && len(nums) == 3 && get(nums, 0) == 3 && ...) {
        return list(1, 2);
    }
    return list();
}
```

**How it works**
1. `_extract_function_params(reference, fn_name)` — parse params via
   toylang's parser.
2. `_parse_args(call_src)` — parse each test's call expression to
   extract literal args. `_classify_arg` tags each as primitive /
   list / dict / complex.
3. `_toylang_reference_outputs(kata, toylang_dir)` — run canonical
   reference on toylang once with all test prints; capture stdout
   per test as the precomputed answers.
4. `_build_clike_case_analysis(kata, params, expected_outputs)` —
   emit c_like source with cascading if-statements.
5. Hand off to `mechanical_translator.transpile()` for c_like /
   phrasebook / dynamic-python_like targets.
6. For static-typed python_like targets, `_emit_typed_python_case_analysis()`
   hand-crafts the Python with `param_types` inferred from test arg
   literals (`int`, `string`, `list`, `dict`, `bool`) and `return_type`
   from expected output shape.
7. `_rederive_expected()` runs the candidate to absorb formatter
   differences.
8. `_self_validate()` confirms it works in the target language.

**Public API**
- `build_case_analysis_kata(canonical_kata, spec, lang_dir,
   toylang_dir) -> dict | None`

Returns the kata with `case_analysis_fallback: True` set so the GUI
knows to label it.

**Use case**: makes auto-check work on languages where neither
mechanical translation nor LLM translation produce a valid algorithm.
It memorizes test answers — not a real solution, but the grader still
correctly grades the user's submission against the precomputed
expected outputs.

### 4.17 `pair_programmer.py` — language-aware AI chat

```
chat(spec, lang_dir, user_message, history, client, *,
     kata=None, current_code=None, mode="hint") -> dict
```

The 💬 chat panel in the Playground (and the **Ask AI** button on each
kata).

**What it does**
1. Builds a system prompt from the spec: current language, syntax
   examples, stdlib, comment style. The model "knows" the language.
2. If `kata` is supplied, adds the kata's problem statement + helpers
   + current_code as kata-aware context. Two modes:
   - `hint`: nudge toward the solution, don't reveal it.
   - `solution`: give the full solution.
3. Sends prompt + history via `client.call_chat`.
4. Post-processes the response to find fenced code blocks and tries
   to **parse-validate** each one against the language's actual
   parser (`validate_code_block`). Annotates blocks that fail to
   parse so the GUI can render them with a "this might not compile"
   marker. Successful blocks get a "▶ Run this" button in the chat.

**Use case**: the user asks "how do I write a while loop in this
language?" and gets actual valid syntax instead of standard Python.

---

## 5. The Flask GUI — `forge/gui/app.py`

Vanilla Flask app, ~1300 lines. Single-page front end (`index.html`
+ `app.js` + `style.css`) with view tabs.

### 5.1 Endpoints

#### Static / boot
- `GET /` — serves `index.html`
- `GET /api/providers` — which LLM providers are reachable
- `GET /api/languages` — list of generated languages with
  `{name, ext, options, shipped[]}` (the `shipped` array is the test
  + example file stems actually on disk, used by the playground
  dropdown)

#### Language creation
- `POST /api/create` — kicks off a generation Job; returns `{job_id}`.
  Validates customization; runs the coherence pre-check; spawns the
  worker thread.
- `POST /api/surprise` — "surprise me from a vibe word". The LLM
  picks every option from a description, then runs the same pipeline.
- `GET /api/stream/<job_id>` — Server-Sent Events stream of the
  background job's progress. Each `step` / `spec` / `report` / `done`
  event renders to the Progress view.
- `DELETE /api/language/<lang>` — wipe `generated/<lang>/`. Refuses to
  delete `toylang` (protected) or anything outside `generated/`.

#### Listings (preset pickers)
- `GET /api/personas`, `/api/eras`, `/api/themes`, `/api/bans`,
  `/api/phrasebooks` — return the preset registries for the GUI
  dropdowns.
- `GET /api/samples` — global curated sample programs.
- `GET /api/example/<lang>/<example>` — language-specific shipped
  example source.

#### Run / verify / repair
- `POST /api/run` — compile + run a single source string against a
  language. Returns `{stage, ok, stdout, stderr, transpiled, hint}`.
  `_explain_compile_error` turns Lark tracebacks into actionable hints.
- `POST /api/run-all` — same source against every generated language,
  side by side. Two modes: `example` (each language runs its own
  shipped copy of an example) vs. `source` (literal source on every
  language).
- `POST /api/verify/<lang>` — re-verify the canonical tests.
- `POST /api/repair/<lang>` — run the repair loop.
- `POST /api/translate-comments` — convert `// comment` to the
  language's actual comment syntax.

#### Spec / logs
- `GET /api/spec/<lang>` — the resolved spec JSON.
- `GET /api/log/<lang>` — list of files in `<lang>/.forge_log/`
  (LLM-call audit trail).
- `GET /api/log/<lang>/<filename>` — read one log file.

#### Standalone artifacts
- `GET /api/standalone/<lang>` — serves the in-browser Pyodide REPL
  HTML. With `?download=1` returns `Content-Disposition: attachment`.
- `GET /api/download/<lang>` — streams `<lang>-0.1.0.zip` of the
  generated project.

#### Katas
- `GET /api/katas/<lang>` — saved kata pack from `<lang>/katas.json`.
- `POST /api/katas/<lang>/generate` — fresh LLM-generated pack.
- `GET /api/kata-packs` — list curated packs (currently just
  "classics").
- `POST /api/katas/<lang>/load-pack/<pack_key>` — load a curated pack
  into the language. Goes through the full ladder
  (curated direct → mechanical → LLM translate → case-analysis →
  stub-rescue). Supports `?force=true` (skip cache) and `?strict=true`
  (refuse incompatible languages instead of falling through).
  Cache key includes a content hash so source-pack edits invalidate
  it automatically.
- `POST /api/katas/<lang>/<kata_id>/check` — run user code. Two
  modes:
  - `mode=run`: only sample tests, full per-test results
  - `mode=submit`: full hidden suite, first-failure-only

#### Pair programmer
- `POST /api/chat/<lang>` — one round of language-aware chat. Body
  has `message`, `history`, optional `kata_id` + `current_code` +
  `mode`. Returns the assistant message + an `code_blocks` array with
  parse-validation status for each fenced code block.

### 5.2 The single-page front end

`static/index.html` defines four views: **Create**, **Library**,
**Playground**, **Katas**. View switching is a simple toggle of
`.active` class on `.tabs button`.

**`static/app.js`** (~2000 lines) handles:
- Form serialization for the Create view + SSE progress rendering.
- Library list: per-language cards with download, run-all, verify,
  repair, delete buttons.
- Playground: language picker, sample picker, CodeMirror editor,
  Run button, side-by-side "Run on every language" comparison.
- Pair programmer chat sidebar with code-block extraction.
- Kata system: library list with filters (difficulty / tags / status)
  + search, problem detail with tabs (Description / Submissions /
  Solution), Run vs. Submit, Show solution, submission history in
  localStorage.

**`static/style.css`** (~1800 lines): shadcn-style dark theme. Royal
blue accent on slate-tinted near-black surfaces. LeetCode-style
green/amber/red difficulty pills.

---

## 6. The hand-written `toylang` reference compiler

`generated/toylang/` is the **golden child**. Hand-written, never
LLM-touched, used as:
- The reference implementation of the c_like family.
- The grammar source for `mechanical_translator` (it parses any
  c_like source via `toylang.parser`).
- The "ground truth" for the case-analysis fallback (runs
  canonical references to capture answers).
- The base for any newly-generated language's runtime patches.

Files:
- `lexer.py` — Lark grammar.
- `parser.py` — `parse(src)` returns a Lark Tree.
- `codegen.py` — tree-walker emitting Python.
- `runtime.py` — `toy_print`, `toy_str`, `toy_get`, `toy_truthy`,
  list/dict/string helpers.
- `stdlib.py` — the language's standard library, all dispatched
  through the runtime.
- `compile.py` — CLI: `python compile.py <source>` writes
  `<source>.out.py`.
- `tests/` — 8 canonical programs (hello_world, arithmetic,
  variables, conditionals, loops, functions, closures, strings) with
  matching `<name>.expected_output.txt`.
- `repl.html` — re-rendered each run; the standalone Pyodide REPL.

Everything else in `generated/` is LLM-generated by `generator.py`.

---

## 7. Templates — `forge/templates/`

Jinja2 + raw Python files copied per generated language.

| Template | Purpose |
|---|---|
| `pyproject.toml.j2` | makes the language a real `pip install -e .` package with a `<lang>` console entry |
| `compiler_entry.py.j2` | the `<lang>` CLI, calls the language's `compile.py` |
| `package_init.py.j2` | re-exports `parse()` etc. for the package |
| `INSTALL.md.j2` | installation instructions |
| `LICENSE.j2` | MIT license with the right name + year |
| `runtime_shim.py` | (literal Python) backfills any Python builtins the LLM might have called without import |
| `standalone_repl.html.j2` | self-contained Pyodide REPL: HTML + CSS + embedded compiler files. Re-rendered every generation. |
| `starter_program.j2` | a hello-world for the new language |
| `starter_README.md.j2` | starter-project readme |

---

## 8. Tests — `tests/`

Standard pytest suite (~340 tests) plus deep audits:

### `tests/audit/`
- `test_kata_audit.py` — 49-check audit of the kata system. Runs
  outside pytest, writes a single human-readable
  `KATA_AUDIT_REPORT.txt` with intent + result + fix per check.
- `test_lang_gen_audit.py` — 43-check audit of the language-generation
  pipeline (cartesian over options, every preset, every
  customization layer, components, verifier, repair).
- `README.md` — explains how to run and what they cover.

### Notable pytest files
- `test_spec_builder.py` — base/extended option propagation
- `test_coherence.py` — rule firings (covered via test_speculative)
- `test_design_axes.py` — option-combination coverage
- `test_extended_options.py` — comment_style, error_handling, etc.
- `test_phrasebook.py` — natural_language injection
- `test_layered_options.py` — era + theme + ban stacking
- `test_customization.py` — keyword/operator overrides
- `test_speculative.py` — persona / era / theme / ban / surprise
- `test_compile_error_hints.py` — `_explain_compile_error`
- `test_repair_picker.py` — `_pick_component`
- `test_verifier.py` — verify on toylang
- `test_codegen.py` — codegen patterns
- `test_applied_stdlib.py` — stdlib coverage on toylang
- `test_scaffold.py` — scaffold writes
- `test_packaging.py` — pip install paths
- `test_shim_and_examples.py` — runtime shim + examples emit
- `test_showcase_features.py` — closures/recursion smoke tests
- `test_standalone_repl.py` — REPL HTML correctness
- `test_parallel_generator.py` — wave overlap timing
- `test_voice_quality.py` — no em-dashes / Claude name-drops in user-facing files
- `test_gui_endpoints.py` — Flask routes
- `test_katas.py` — kata system (largest, ~70 tests)
- `test_pair_programmer.py` — chat plumbing

---

## 9. End-to-end flows: who calls whom

### Flow 1 — Create a language

```
GUI Create form
  → POST /api/create (app.py)
    → spec_builder.build_spec(opts, name, ...)
      → coherence.check(opts) [errors → return 400]
    → Job() spawned in thread
    → resolver.resolve(base_spec, client) [LLM]
    → generator.generate_all(spec, ...) [parallel LLM waves]
    → verifier.verify(lang_dir)
    → if !all_passed: repair.repair_run(lang_dir, client) [LLM loop]
    → Job emits 'done' SSE event
  ← /api/stream/<job_id> streams progress to GUI
```

### Flow 2 — Load a kata pack

```
GUI clicks 📚 Load pack
  → POST /api/katas/<lang>/load-pack/<pack>?force=...
    → kata_packs.get_pack(pack) [the curated template]
    → kata_packs.get_classics_for(spec) [picks iter/recursive variant]
    → mechanical_translator.ensure_runtime_string_support(lang_dir)
    → cache check (pack_hash match → return cached)
    → preflight: needs_translation = phrasebook? feature_ban? syntax mismatch?
    → if not needs_translation: katas._batch_validate (one compile+run for whole pack)
    → if needs_translation: kata_translator.translate_pack(...)
        → mechanical_translator.transpile_and_validate (try c_like/phrasebook/python emit)
        → batch LLM translate
        → escalating fix-up (3 attempts per failure, parallel)
        → per-kata fresh translation (for missed katas)
        → single-test reduction
        → case_analysis.build_case_analysis_kata
        → kata_translator._stub_rescue
    → save katas.json with pack_hash
    ← jsonify(pack)
```

### Flow 3 — Submit a kata solution

```
GUI Submit click
  → POST /api/katas/<lang>/<kata_id>/check
    body: { code, mode: "submit" }
    → katas.load_pack(lang_dir) [reads katas.json]
    → katas.check_solution(spec, lang_dir, kata, code)
      → katas._wrap_with_test_prints(code, tests, spec, helpers=kata.helpers)
      → katas._compile_and_run(lang_dir, program, ext)
      → first-failure-only comparison
    ← {passed, stage, test_index, expected, actual, ...}
```

---

## 10. Where the seams are (improvement ideas)

This is opinionated — places I'd look at first if you want to extend.

### 10.1 Static-typed languages still mostly stub

`hardcombo` (python_like + static) gets only 2/12 functional katas
because its LLM-generated typechecker has bugs (rejects `len(list)`,
doesn't know about `dict()`). Two paths:
- **Repair button**: ask the LLM to fix the typechecker. Existing
  infrastructure should handle this; the user just needs to click it.
- **Mechanical case-analysis path 2.0**: write a *typechecker-aware*
  emitter that reads the spec's stdlib signatures and chooses
  expressions known to type-check. Big project.

### 10.2 More curated kata packs

`PACKS = {"classics": ...}` could grow:
- Beginner pack (variables, conditionals, simple loops)
- Algorithms pack (sorts, searches, graph traversal)
- Data-structure pack (heap, trie, union-find)

The data model already supports them. Each new pack just needs the
kata definitions in `kata_packs.py` plus an entry in `PACKS`.

### 10.3 Persistent submissions

Submission history is currently localStorage-only. A real DB would
allow:
- "Solved on 5 languages" badges per problem
- Leaderboards
- Discussion threads per kata

### 10.4 Light mode

The shadcn dark theme is the only mode. Adding a `data-theme="light"`
toggle is straightforward — the variables system is already in place.
shadcn defines both modes; I just need to add the `.light` class
overrides and a toggle button.

### 10.5 More mechanical-translator backends

Currently three (CLike, PythonLike, Phrasebook). Could add:
- `LispBackend` for fully-paren'd languages
- `StackBackend` for Forth-likes
- Anything else syntactically distinctive

`can_handle` would route to the right one.

### 10.6 Better repair attribution

`_pick_component` is regex on stderr. Sometimes mis-attributes (e.g.
a parser bug that surfaces as a runtime IndexError gets blamed on
runtime). Could replace with a small classifier — even a heuristic
+ confidence score would beat the current first-match logic.

### 10.7 Streaming kata generation

Currently `/api/katas/<lang>/load-pack/...` is a single POST that
blocks until done. For 90s wait, an SSE stream like `/api/stream/...`
would let the GUI show per-kata progress. The translator already has
`on_progress` callbacks; just needs an SSE endpoint to forward them.

### 10.8 Test the audit scripts

The two audit scripts in `tests/audit/` are themselves untested —
they walk the codebase manually. If you change a public API, the
audit might silently false-pass because of wrong assumptions in the
audit code. Adding a meta-test that asserts the audits produce
expected counts would catch that.

### 10.9 Documentation

This file is the only architecture doc. The `forge/prompts/*.md`
files are LLM prompts, not user docs. A `docs/` directory with
walkthroughs for "how to add a new language family" or "how to write
a curated kata pack" would help future contributors.

---

## 11. File-by-file reference (quick lookup)

| File | Lines | What it owns |
|---|---|---|
| `forge/cli.py` | ~250 | argparse: create/verify/repair/list/gui |
| `forge/scaffold.py` | ~150 | starter project files for a new lang |
| `forge/orchestrator/spec_builder.py` | ~600 | options → spec |
| `forge/orchestrator/coherence.py` | ~220 | option-combo validity rules |
| `forge/orchestrator/resolver.py` | ~50 | LLM-fills-in-spec |
| `forge/orchestrator/generator.py` | ~830 | per-component LLM gen + post-fixups |
| `forge/orchestrator/verifier.py` | ~260 | run canonical tests |
| `forge/orchestrator/repair.py` | ~210 | verify-fix-verify loop |
| `forge/orchestrator/llm_client.py` | ~270 | Anthropic SDK wrapper |
| `forge/orchestrator/llm_client_claude_cli.py` | ~210 | claude CLI wrapper |
| `forge/orchestrator/providers.py` | ~70 | which client to use |
| `forge/orchestrator/personas.py` | ~110 | designer personas |
| `forge/orchestrator/presets.py` | ~140 | era presets |
| `forge/orchestrator/themes.py` | ~100 | keyword-theme overrides |
| `forge/orchestrator/phrasebooks.py` | ~110 | natural_language templates |
| `forge/orchestrator/bans.py` | ~120 | feature_bans |
| `forge/orchestrator/katas.py` | ~440 | kata core: gen + check + batch validate |
| `forge/orchestrator/kata_packs.py` | ~990 | curated classics + recursive variant + metadata |
| `forge/orchestrator/kata_translator.py` | ~600 | LLM translation ladder w/ budget |
| `forge/orchestrator/mechanical_translator.py` | ~520 | tree-walking transpiler |
| `forge/orchestrator/case_analysis.py` | ~420 | hardcoded-answer fallback |
| `forge/orchestrator/pair_programmer.py` | ~290 | language-aware chat |
| `forge/gui/app.py` | ~1300 | Flask routes |
| `forge/gui/static/app.js` | ~2000 | front-end logic |
| `forge/gui/static/index.html` | ~680 | layout + tabs |
| `forge/gui/static/style.css` | ~1800 | shadcn-style theme |
| `forge/gui/samples.py` | ~120 | curated sample programs |
| `forge/templates/` | various | Jinja2 + static templates |
| `forge/prompts/` | various | LLM prompts (Markdown) |
| `tests/audit/` | ~2000 total | deep system audits + reports |

---

## 12. The variance pipeline + catalog system

Two architectural layers added after Phase 1.5 to handle the
fundamental scaling question: how do you generate hundreds of
languages that all feel distinct from each other?

### 12.1 The three-call pipeline

Each generated language flows through three LLM calls:

1. **`resolver`** (`resolver.py`, prompt: `resolver.md`). Reads the
   base spec + user options, fills in keyword spellings, grammar
   details, stdlib semantics. Output: a fully-resolved spec.
   Cached on content-hash; cache key strips lang_name + lineage so
   two slots sharing options share one resolver call.

2. **`gen-creative`** (`creative.py`, prompt: `creative.md`). Six
   voiced README sections (intro, design philosophy, good-at,
   bad-at, example commentary, common mistake). The personality
   layer. Cached identically; v3 of the prompt is family-aware so
   `example_commentary` doesn't default to c_like-shaped framing.

3. **`gen-idioms`** (`idioms.py`, prompt: `idioms.md`). Themed
   replacements for each of the 8 canonical test bodies plus 0-5
   themed example programs. The structural-variance layer at the
   test-content level. v3 of the prompt inlines 2 reference-compiler
   canonical tests per family as worked examples so the LLM has
   grammar-accurate anchors.

Per-language cost: ~$0.008 at Sonnet 4.5 rates. Warm-cache wall:
3-6 seconds.

### 12.2 The templated reference path

When the syntax family has a hand-written reference compiler in
`generated/<reflang>/`, `generator._template_from_reference()` copies
the reference's parser, codegen, runtime, stdlib, and canonical tests
into the new language's directory, applying:

- **Package-name swap**: `from <reflang>.runtime import` rewritten to
  `from <new_lang_name>.runtime import` everywhere.
- **Spec-driven keyword overrides**: via `substitution.py`'s
  per-family `KEYWORD_ROLES_BY_FAMILY`. Themed `let -> define` for
  ml_like rewrites both the parser grammar string AND the canonical
  test sources at once.
- **`<args>`-template print form** (structural-variance-channel Seam 4):
  `spec.print_form` carries an `<args>` placeholder like
  `print_any (<args>) ;;`. The `_wrap_with_test_prints` kata wrapper
  and the `_render_templated_readme` "At a glance" snippet both
  substitute via the helper, so a phrasebook override of
  `print_form: "say <args>"` propagates without code changes.

After `_template_from_reference`, the `_overlay_idiomatic_content`
hook reads `spec.idioms.canonical_test_bodies`, validates each
themed body by compiling + running it twice (determinism check), and
swaps the reference tests with the themed ones for the ones that
pass. Rejected bodies stay as reference templates — the smoke loop
keeps working.

### 12.3 Per-family README "At a glance" rendering

`_render_templated_readme` dispatches to `_at_a_glance_snippet(spec)`
which routes by `spec.options.syntax` to one of five per-family
renderers:

- `_at_a_glance_c_like`: `func`, `var`, `print(<args>);` — three
  lines, the c_like convention.
- `_at_a_glance_s_expression`: parenthesized prefix forms.
- `_at_a_glance_stack_based`: colon definition + variable + postfix
  print.
- `_at_a_glance_ml_like`: shows a `let rec ... match lst with | [] ->
  0 | h :: t -> h + sum t ;;` pattern-match snippet — the structurally
  distinctive ML idiom no other family produces.

This is structural-variance-channel Seam 1 — the single change that
flipped a user-read from "ml_like reads like c_like with different
keywords" to "reads like ML now, I enjoy it."

### 12.4 The catalog (Phase 2-3)

For batch generation against a slot plan, the `forge.catalog`
package adds:

- **`forge.catalog.batch`**: parallel subprocess driver. Runs N
  slots through the full pipeline at concurrency 4 by default with
  per-slot timeout caps. Writes per-slot state for resume.
- **`forge.catalog.curate`**: scores each generated language on
  distinctiveness + coherence + completeness, deduplicates by
  content hash, loads into a SQLite catalog DB (`catalog.db`).
- **`forge.catalog.backfill`**: rehydrates customization columns
  (theme, persona, era, phrasebook) from the slot plan. Workaround
  for a known runner bug that NULL-s those columns at insert time.
- **`forge.catalog.dedup`**: pairwise content-hash + structural
  similarity check.

The catalog UI (`/catalog` in the GUI, served from
`forge/gui/catalog_routes.py`) lets users browse, filter, approve/
reject, tag, and launch REPL/kata workspaces for every generated
language. The Library tab uses `include_catalog=approved_only` so it
shows only curated entries by default.

---

## 13. Acronyms / terms

- **kata** — a programming problem with starter code, hidden tests,
  and a reference solution. Borrowed from the dojo concept.
- **stub-rescue** — last-resort fallback that saves a kata's
  description but with no working reference (auto-check disabled).
  Now superseded by case-analysis in most situations.
- **case-analysis** — a function that hardcodes the answer for each
  test by discriminating on argument values. Mechanically generated.
- **escalating fix-up** — three-step retry strategy for LLM
  translations: standard fix → alt-algorithm → case-analysis.
- **rederive expected** — run the candidate kata's reference, capture
  actual stdout, replace the kata's `expected` strings. Absorbs
  print-formatter differences.
- **runtime-shim** — Python file dropped next to a generated
  language's runtime that backfills any Python builtins the LLM
  might call without importing.
- **canonical test** — one of the eight handwritten programs every
  generated language must pass: hello_world, arithmetic, variables,
  conditionals, loops, functions, closures, strings.
