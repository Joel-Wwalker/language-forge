# Language Forge

Generate small programming languages from a structured spec. Each
generated language ships as a pip-installable Python package with its
own parser, codegen, runtime, stdlib, canonical test suite, themed
README + design philosophy, themed kata pack, and an in-browser REPL.

## Status

Phases 0-3 complete. Six subsequent targeted-architecture interventions
merged on top: variance-improvement (gen-creative six-field expansion),
structural-variance (themed canonical-test bodies + themed examples),
ml-family-experiment (`ml_like` reference compiler + family integration),
structural-variance-channel (per-family de-flattening so the generation
pipeline carries structural variance rather than collapsing to c_like
shapes), phase4-preflight (Seam 8 fix + 100-slot validation batch +
Option D pipeline parallelization), and logic-family-experiment
(`logic_like` reference compiler — pragmatic Prolog subset, the
project's first paradigm-different family).

Test suite: **1042 tests passing, 23 skipped, 0 failing.** Deterministic
tests run without API credentials; end-to-end tests are gated on
`ANTHROPIC_API_KEY` or the `claude` CLI. Six syntax families are
wired up: `c_like`, `python_like`, `s_expression`, `stack_based`,
`ml_like`, `logic_like`. Hand-written reference compilers live under
`generated/` and are templated from for new languages in the same family.

The three-call generation pipeline (resolver → gen-creative →
gen-idioms, the latter two now running in parallel via Option D) plus
the templated reference path produces a working language in ~3-5
seconds warm-cache, ~$0.008 per language. Cross-family structural
variance was confirmed by successive user-reads — most recently a
10-slot logic_like validation batch ("reads like Prolog, catalog feels
richer") — rather than measured purely via internal acceptance metrics.

## Quick start

```bash
git clone https://github.com/Joel-Wwalker/language-forge.git
cd language-forge
python -m venv .venv
. .venv/Scripts/activate                 # Windows
. .venv/bin/activate                     # macOS / Linux
pip install -e ".[dev]"
```

Set a provider (either works):

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # API mode
# or install the Claude CLI and let auto-detect find it
```

Run the test suite (deterministic, no API key needed for the bulk):

```bash
pytest -m "not slow"                     # 1042 passed, 23 skipped
```

Generate a language interactively:

```bash
python -m forge create --syntax logic_like --typing dynamic --memory host_gc --name myprolog
python -m forge verify generated/myprolog
```

Or open the GUI:

```bash
python -m forge gui                      # http://127.0.0.1:5173/
```

## What you get when you generate a language

- A pip-installable Python package at `generated/<name>/`
- A working compiler: parser, codegen, runtime, stdlib, compile.py
- 8 canonical tests in the language's idiomatic surface syntax
  (the `gen-idioms` LLM call themes the test bodies; rejected
  themed bodies fall back to the reference templates)
- A themed README with 6 voiced sections (intro, design philosophy,
  good-at, bad-at, example commentary, common mistake) plus a
  family-correct "At a glance" code block
- A LANGUAGE.md reference doc
- A standalone single-file Pyodide REPL (`repl.html`)
- A 6-12 kata pack (LeetCode-style) curated for the language family,
  each kata with reference solution + hidden tests + auto-grading

## Six syntax families

| family | reference compiler | surface example |
| --- | --- | --- |
| `c_like` | `generated/toylang/` | `func add(a, b) { return a + b; }` |
| `python_like` | (no reference yet; LLM-generated) | `def add(a, b):\n    return a + b` |
| `s_expression` | `generated/lisplang/` | `(defn add (a b) (+ a b))` |
| `stack_based` | `generated/forthlang/` | `: add ( a b -- sum ) + ;` |
| `ml_like` | `generated/mllang/` | `let rec sum lst = match lst with \| [] -> 0 \| h :: t -> h + sum t ;;` |
| `logic_like` | `generated/prologlang/` | `factorial(N, F) :- N > 0, N1 is N - 1, factorial(N1, F1), F is N * F1.` |

Five of the six families have a hand-written reference compiler.
Each reference is tested and serves as the template for every
generated language in its family. The substitution layer applies
per-family keyword overrides + spec-driven `<args>`-template print
forms so a themed pirate ml_like language has its `let` renamed to
`yarr` (or whatever) in both the parser grammar AND the canonical
test sources at once.

`logic_like` is the project's **first paradigm-different family** —
where the other five families all evaluate expressions to produce
values, `logic_like` evaluates queries against a database of facts
and rules via unification + chronological backtracking. No cut, no
dynamic assert/retract, no DCGs (pragmatic Prolog subset). The
architecture absorbed this paradigm shift without structural rework
— the same five seams (`spec_builder` base + `REFERENCE_COMPILERS`
+ `_at_a_glance` + schema sub-properties + substitution roles)
accepted the new family additively.

## The catalog system (Phase 2-3)

Beyond one-off `python -m forge create` runs, the project supports
batch generation against a slot plan plus a curation UI:

```bash
# Batch-generate against a slot plan
python -m forge.catalog.batch \
    --plan forge/catalog/slots/v1_phase1.json \
    --output catalog_raw_v1 \
    --concurrency 4 \
    --client-provider claude_cli

# Score + dedup + load into a SQLite catalog DB
python -m forge.catalog.curate \
    --input catalog_raw_v1 \
    --db catalog.db

# Backfill customization columns (workaround for a known runner bug)
python -m forge.catalog.backfill \
    --db catalog.db \
    --plan forge/catalog/slots/v1_phase1.json
```

The catalog UI (in the GUI, `/catalog`) lets you review every
generated language, approve/reject, add tags, run their READMEs,
launch their REPLs, and drill into customization breakdowns. The
Library tab shows the curated set (approved-only by default).

## Repository layout

```
forge/
  cli.py                          python -m forge entry
  gui/                            Flask + SSE + vanilla JS
    app.py                        REST endpoints + playground + library
    catalog_routes.py             curation UI routes
    static/{app,catalog}.{js,css} frontend
  orchestrator/                   generation pipeline + LLM calls + repair
    spec_builder.py               options + customization -> spec
    resolver.py                   LLM call: fill in spec gaps
    creative.py                   LLM call: 6 voiced README sections
    idioms.py                     LLM call: themed canonical tests + examples
    generator.py                  per-component code + templated path
    katas.py                      kata generation + auto-grading
    mechanical_translator.py      syntactic c_like -> target translation
    substitution.py               per-family keyword override substitution
    verifier.py / repair.py       canonical test verification + LLM repair
  catalog/                        batch + curate + dedup + DB
  prompts/                        one .md per LLM call
  templates/                      Jinja: pyproject, LICENSE, REPL shell
schemas/                          language_spec.schema.json
generated/                        languages (5 reference compilers + LLM output)
  toylang/                        c_like reference
  lisplang/                       s_expression reference
  forthlang/                      stack_based reference
  mllang/                         ml_like reference
  prologlang/                     logic_like reference (pragmatic Prolog)
  stacky/                         stack_based test fixture
tests/                            pytest suite (1042 tests)
```

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md): full architectural tour:
  module-by-module breakdown, pipeline, kata system, GUI surface,
  variance pipeline, design seams.

## License

See [`LICENSE`](LICENSE).
