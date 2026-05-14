"""mllang transpiler CLI.

Usage:
    python -m mllang.compile <source>.ml [-o <out.py>]

Reads an mllang source file, parses it, transpiles to Python, and
writes the result to `<source>.out.py` (or `--output` if provided).
Parallel to toylang.compile / lisplang.compile.
"""
from __future__ import annotations

import argparse
import os
import sys


def _ensure_package_imports():
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if parent not in sys.path:
        sys.path.insert(0, parent)


def main(argv=None):
    _ensure_package_imports()
    from mllang.parser import parse
    from mllang.codegen import generate

    p = argparse.ArgumentParser(prog="mllang", description="mllang transpiler")
    p.add_argument("source", help="Input .ml file")
    p.add_argument("-o", "--output", default=None,
                   help="Output .py path (default: <source>.out.py)")
    args = p.parse_args(argv)

    with open(args.source, "r", encoding="utf-8") as f:
        src = f.read()
    tree = parse(src)
    py_source = generate(tree)
    out_path = args.output or (args.source + ".out.py")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(py_source)
    print(out_path)


if __name__ == "__main__":
    main()
