# Installing slot_lgc_010

`slot_lgc_010` is a logic_like language with dynamic typing and
host_gc memory. Source files use the `.slo` extension.
The compiler transpiles to Python.

## Requirements

- Python 3.11 or newer
- A terminal that can run `python` and `pip`

The runtime is plain Python. No external compiler.

## Install

From this directory:

```bash
pip install -e .
```

This installs `slot_lgc_010` as a Python package and registers a
`slot_lgc_010` command on your PATH.

For an isolated environment:

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows
. .venv/bin/activate              # macOS / Linux
pip install -e .
```

## Verify

```bash
slot_lgc_010 --help
```

If "command not found", make sure the venv is activated. Or fall back to:

```bash
python -m slot_lgc_010.compile --help
```

## Run a program

Write `hello.slo`:

```
print("Hello, slot_lgc_010!");
```

Compile and run:

```bash
slot_lgc_010 hello.slo
python hello.slo.out.py
```

Or in one command:

```bash
slot_lgc_010 hello.slo && python hello.slo.out.py
```

## Try in a browser

Open `repl.html` in any browser. The full compiler runs locally via
Pyodide. No install required.

## Layout

```
slot_lgc_010/
├── README.md           friendly intro and syntax tour
├── LANGUAGE.md         full reference
├── INSTALL.md          this file
├── LICENSE             MIT
├── pyproject.toml      pip-installable package
├── repl.html           in-browser REPL
├── examples/           sample programs
├── tests/              canonical tests (must all pass)
└── (compiler source)   lexer.py, parser.py, codegen.py, runtime.py
```

## Run the canonical tests

```bash
cd tests
slot_lgc_010 hello_world.slo && python hello_world.slo.out.py
```

Each test has a sibling `<name>.expected_output.txt` to diff against.

## Uninstall

```bash
pip uninstall slot_lgc_010
```
