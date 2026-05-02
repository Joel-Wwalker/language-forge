# Language Forge

Pick three options. Get a working compiler.

Forge generates a runnable transpiler (lexer, parser, code generator,
runtime, stdlib, tests, docs) from a small set of design choices. A
verifier runs eight canonical programs against the result. If any fail,
a repair loop rewrites the broken component and tries again.

The output is a real Python package: `pip install -e .` and the language
gets its own CLI command. Or download a single self-contained HTML file
and run programs in any browser. No install, no Python.

[![python](https://img.shields.io/badge/python-3.11%2B-blue)](#)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![tests](https://img.shields.io/badge/tests-94%20passing-success)](#tests)

## Install

```bash
git clone <this-repo> language-forge
cd language-forge
python -m venv .venv
. .venv/Scripts/activate         # Windows
. .venv/bin/activate             # macOS / Linux
pip install -e ".[dev]"
```

Set one of these so the orchestrator can call out:

```bash
export ANTHROPIC_API_KEY=sk-ant-...        # API tokens
# or install the `claude` CLI; Forge picks it up automatically.
```

## Run

```bash
python -m forge gui                                                 # browser UI
python -m forge create --syntax c_like --typing dynamic --memory host_gc --name mylang
python -m forge verify generated/mylang
python -m forge repair generated/mylang
```

The GUI auto-opens at `http://127.0.0.1:5173/`. Three tabs: Create,
Library, Playground. Plus a "Surprise me" tab that picks every option
from a single vibe word.

## What you can pick

Three required axes:

| axis    | values                       |
|---------|------------------------------|
| syntax  | `c_like`, `python_like`      |
| typing  | `static`, `dynamic`          |
| memory  | `host_gc`, `refcount`        |

Eight more axes are optional, with sensible defaults:

| axis                | values                                                      |
|---------------------|-------------------------------------------------------------|
| comment_style       | `line`, `block`, `both`, `nestable_block`                   |
| string_literals     | `single`, `double`, `both`, `triple_quoted`, `raw_and_normal`|
| numeric_literals    | `decimal_only`, `c_style`, `extended`                       |
| default_mutability  | `mutable`, `immutable`                                      |
| error_handling      | `panic_only`, `exceptions`, `result_type`                   |
| loop_forms          | subset of {while, c_for, foreach, repeat_until, loop_break} |
| multiple_returns    | `none`, `tuple`, `named`                                    |
| boolean_evaluation  | `short_circuit`, `eager`                                    |

And more knobs in the GUI: designer persona (Dijkstra/Hickey/Wirth/...),
era preset (1960s/70s/80s/00s/20s), keyword theme, feature bans
(no_loops, no_mutation, no_null), free-form constraints.

## What ships with each language

```
mylang/
├── README.md            friendly intro + syntax tour
├── LANGUAGE.md          formal reference (grammar, types, semantics, stdlib)
├── INSTALL.md           install + run instructions
├── LICENSE              MIT
├── pyproject.toml       proper Python package, registers `mylang` CLI
├── repl.html            single-file in-browser REPL (Pyodide)
├── examples/            FizzBuzz, fibonacci, counter factory, more
├── tests/               canonical test programs (eight required)
├── compile.py           CLI entrypoint
├── lexer.py
├── parser.py
├── codegen.py
├── runtime.py
└── stdlib.py
```

After `pip install -e .` from the language directory, `mylang
program.ext && python program.ext.out.py` works anywhere on the system.

## Provider

The orchestrator calls a model for code generation. Two transports are
supported and auto-detected:

- `api`. Uses `ANTHROPIC_API_KEY`. Per-token billing.
- `claude_cli`. Shells out to the `claude` CLI from a Claude.ai plan.

Force one with `--provider api` or `--provider claude_cli`.

## Architecture

```
options
  → spec_builder              deterministic; merges defaults + user choices
  → resolver  (LLM)           fills gaps, reconciles incoherent combos
  → generator (LLM, per file) lexer, parser, codegen, runtime, stdlib, tests, docs
  → verifier                  runs eight canonical programs
  → repair    (LLM)           rewrites failing components
  → ship                      pip-installable + browser-runnable
```

Source layout:

```
forge/
  cli.py                       `python -m forge`
  gui/                         Flask + SSE + vanilla JS
  orchestrator/
    spec_builder.py
    resolver.py
    generator.py
    verifier.py
    repair.py
    llm_client.py              Anthropic SDK wrapper
    llm_client_claude_cli.py   `claude` CLI wrapper (parity API)
    providers.py               auto-detect + factory
    presets.py                 era bundles (1960s/70s/80s/00s/20s)
    personas.py                designer voices (Dijkstra/Hickey/...)
    themes.py                  keyword themes (pirate/cozy/latin/...)
    bans.py                    feature bans
  prompts/                     one .md per generated component
  templates/                   Jinja: pyproject, LICENSE, INSTALL, REPL, CLI
  schemas/language_spec.schema.json
generated/                     output dir; toylang is the hand-written reference
tests/                         pytest: deterministic + gated end-to-end
```

### How a generation runs

1. `spec_builder` assembles a base spec from the option enums plus per-axis
   defaults. Era presets, keyword themes, and feature bans layer in here.
   User options always win.
2. `resolver` calls the LLM (forced tool-use, schema-validated) to fill
   nulls and reconcile incoherent combos (static + python_like becomes
   gradual typing, etc.).
3. `generator` runs per-component prompts in dependency order
   (lexer → parser → typechecker? → codegen → runtime → stdlib → tests →
   README → LANGUAGE.md). Each prompt receives the resolved spec plus the
   source of every previously generated dependency, which kills interface
   drift between components.
4. `verifier` invokes the generated `compile.py` on each canonical test,
   runs the resulting Python, compares stdout to the expected output, and
   attributes failures to a component.
5. `repair` picks the most-failing component, hands its current source
   plus the failure report back to the LLM, and replaces the file. Up to
   3 attempts per component, 2 components per run.
6. Deterministic templates render `pyproject.toml`, `LICENSE`,
   `INSTALL.md`, the in-browser REPL, and the `compile.py` shim.

## Canonical tests

Every generated language must pass these eight programs:

| name          | what it exercises                                           |
|---------------|-------------------------------------------------------------|
| hello_world   | string literal, print                                       |
| arithmetic    | integer math, operator precedence, unary minus              |
| variables     | declaration, reassignment, reuse                            |
| conditionals  | if/elif/else, comparison operators, logical and/or          |
| loops         | summation 1..10                                             |
| functions     | definition, call, return, recursion (factorial)             |
| closures      | function returning a function that mutates an outer var     |
| strings       | concatenation, length, mixed-type printing                  |

The hand-written `generated/toylang/` is the reference implementation.
The verifier was bootstrapped against it.

## CLI reference

```
python -m forge gui [--port 5173] [--no-open]
python -m forge create [options] [--name N] [--provider api|claude_cli]
python -m forge verify <lang_dir>
python -m forge repair <lang_dir> [--provider P]
```

Options for `create`: `--syntax`, `--typing`, `--memory`,
`--comment-style`, `--string-literals`, `--numeric-literals`,
`--mutability`, `--error-handling`, `--loop-forms` (comma-separated),
`--multiple-returns`, `--boolean-evaluation`.

Pytest:

```bash
pytest tests/                         # deterministic suite (no API key)
pytest tests/test_end_to_end.py       # gated; needs ANTHROPIC_API_KEY
```

## Tests

| suite                              | count | requires API key |
|------------------------------------|-------|------------------|
| test_spec_builder.py               | 14    | no               |
| test_codegen.py                    | 5     | no               |
| test_verifier.py                   | 3     | no               |
| test_customization.py              | 13    | no               |
| test_extended_options.py           | 27    | no               |
| test_speculative.py                | 17    | no               |
| test_packaging.py                  | 9     | no               |
| test_standalone_repl.py            | 6     | no               |
| test_end_to_end.py                 | 8     | yes              |

Deterministic suite covers spec-builder validation across all combos,
verifier behavior (pass / missing / failure-attribution), codegen
invariants, customization composition, every extended option axis,
speculative-feature plumbing, packaging output, and the in-browser REPL
template.

## Adding an option axis

1. Extend `forge/orchestrator/spec_builder.py` with the new enum and per-value defaults.
2. Update `schemas/language_spec.schema.json` to allow the new field.
3. Mention the axis in the relevant prompts under `forge/prompts/`.
4. Add a CLI flag in `forge/cli.py` and a card in the GUI.
5. Add tests in `tests/test_extended_options.py`.

## Out of scope

Self-hosting. Native code generation (LLVM, WASM). Module systems in
generated languages. IDE integration beyond the README snippet.
Generated languages transpile to Python; that is the only target.

## License

MIT. See [LICENSE](LICENSE).
