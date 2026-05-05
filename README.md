# Language Forge

Generate small programming languages from a structured spec. Each
generated language ships as a pip-installable Python package with its
own lexer, parser, codegen, runtime, stdlib, canonical test suite,
docs, and an in-browser REPL.

## Status

Phase 0 of the production roadmap is complete: telemetry, repair
budgets, resolver caching, seed plumbing, and subprocess isolation
are in place. The pipeline can generate one language interactively
and is ready for batch generation against a structured slot list
(Phase 1).

Test suite: **711 tests passing, 10 skipped, 0 failing.** Deterministic
tests run without API credentials; end-to-end tests are gated on
`ANTHROPIC_API_KEY`. Four syntax families are wired up: `c_like`,
`python_like`, `s_expression`, `stack_based`. Reference compilers
under `generated/` are hand-written and templated from for new
languages in the same family.

## Quick start

```bash
git clone https://github.com/Joel-Wwalker/language-forge.git
cd language-forge
python -m venv .venv
. .venv/Scripts/activate                 # Windows
. .venv/bin/activate                     # macOS / Linux
pip install -e ".[dev]"
```

Set a provider:

```bash
export ANTHROPIC_API_KEY=sk-ant-...      # or install the `claude` CLI
```

Run the test suite (deterministic, no API key needed):

```bash
pytest -m "not slow"
```

Generate a language:

```bash
python -m forge create --syntax c_like --typing dynamic --memory host_gc --name mylang
python -m forge verify generated/mylang
```

Or open the GUI:

```bash
python -m forge gui                      # http://127.0.0.1:5173/
```

## Repository layout

```
forge/
  cli.py                  python -m forge entry
  gui/                    Flask + SSE + vanilla JS
  orchestrator/           generation pipeline + telemetry + repair
  prompts/                one .md per generated component
  templates/              Jinja: pyproject, LICENSE, REPL, CLI shim
schemas/                  language_spec.schema.json
generated/                output dir (toylang, lisplang, forthlang, stacky tracked)
tests/                    pytest suite
```

## Documentation

- [`PROJECT_REPORT.md`](PROJECT_REPORT.md): analytical map of the
  codebase: pipeline, kata system, GUI surface, design seams.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): deeper architecture notes.

## License

MIT. See [LICENSE](LICENSE).
