# Installing stacky

`stacky` is a stack_based language with static typing and
host_gc memory. Source files use the `.sta` extension.
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

This installs `stacky` as a Python package and registers a
`stacky` command on your PATH.

For an isolated environment:

```bash
python -m venv .venv
. .venv/Scripts/activate          # Windows
. .venv/bin/activate              # macOS / Linux
pip install -e .
```

## Verify

```bash
stacky --help
```

If "command not found", make sure the venv is activated. Or fall back to:

```bash
python -m stacky.compile --help
```

## Run a program

Write `hello.sta`:

```
print("Hello, stacky!");
```

Compile and run:

```bash
stacky hello.sta
python hello.sta.out.py
```

Or in one command:

```bash
stacky hello.sta && python hello.sta.out.py
```

## Try in a browser

Open `repl.html` in any browser. The full compiler runs locally via
Pyodide. No install required.

## Layout

```
stacky/
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
stacky hello_world.sta && python hello_world.sta.out.py
```

Each test has a sibling `<name>.expected_output.txt` to diff against.

## Uninstall

```bash
pip uninstall stacky
```
