"""lisplang transpiler CLI.

Usage:
    python -m lisplang.compile <source>.lsp [-o <out.py>]
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
    from lisplang.parser import parse
    from lisplang.codegen import generate

    p = argparse.ArgumentParser(prog="lisplang", description="lisplang transpiler")
    p.add_argument("source", help="Input .lsp file")
    p.add_argument("-o", "--output", default=None, help="Output .py path (default: <source>.out.py)")
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
