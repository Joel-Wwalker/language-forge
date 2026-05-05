"""Forge CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .orchestrator.spec_builder import build_spec
from .orchestrator.verifier import verify

# Rich: pretty terminal output. Falls back gracefully if not installed.
try:
    from rich.console import Console
    from rich.traceback import install as _install_rich_tb
    _install_rich_tb(show_locals=False)
    _console = Console()
    def cprint(*args, **kwargs):
        _console.print(*args, **kwargs)
except Exception:    # pragma: no cover: only triggers when rich is uninstalled
    _console = None
    def cprint(*args, **kwargs):
        # Rich-syntax tags (e.g. [bold]x[/]) are stripped for the plain fallback.
        import re
        msg = " ".join(str(a) for a in args)
        msg = re.sub(r"\[/?[a-z][a-z0-9_ #]*\]", "", msg)
        print(msg, **{k: v for k, v in kwargs.items() if k in ("file", "end")})


def _interactive_options() -> dict:
    print("Language Forge: interactive mode")
    syntax = _choose("Syntax family", ["c_like", "python_like", "s_expression", "stack_based"], default="c_like")
    typing = _choose("Typing", ["static", "dynamic"], default="dynamic")
    memory = _choose("Memory model", ["host_gc", "refcount"], default="host_gc")
    return {"syntax": syntax, "typing": typing, "memory": memory}


def _choose(label: str, options: list[str], default: str) -> str:
    while True:
        opts = " | ".join(o + (" (default)" if o == default else "") for o in options)
        ans = input(f"{label} [{opts}]: ").strip()
        if not ans:
            return default
        if ans in options:
            return ans
        print(f"  invalid, choose one of: {', '.join(options)}")


def cmd_create(args):
    if args.syntax and args.typing and args.memory:
        opts = {"syntax": args.syntax, "typing": args.typing, "memory": args.memory}
    else:
        opts = _interactive_options()
    # Stir in extended options if provided.
    extended = {
        "comment_style": getattr(args, "comment_style", None),
        "string_literals": getattr(args, "string_literals", None),
        "numeric_literals": getattr(args, "numeric_literals", None),
        "default_mutability": getattr(args, "default_mutability", None),
        "error_handling": getattr(args, "error_handling", None),
        "multiple_returns": getattr(args, "multiple_returns", None),
        "boolean_evaluation": getattr(args, "boolean_evaluation", None),
        "naming_convention": getattr(args, "naming_convention", None),
        "null_model": getattr(args, "null_model", None),
    }
    for k, v in extended.items():
        if v is not None:
            opts[k] = v
    if getattr(args, "loop_forms", None):
        opts["loop_forms"] = [s.strip() for s in args.loop_forms.split(",") if s.strip()]
    name = args.name or input("Language name: ").strip() or "mylang"

    base = build_spec(opts, name)

    from .orchestrator.providers import make_client
    from .orchestrator.resolver import resolve
    from .orchestrator.generator import generate_all
    from .orchestrator.repair import repair_run

    log_dir = Path(args.output) / name / ".forge_log"
    client = make_client(args.provider, log_dir=log_dir)
    cprint(f"[bold]Forge[/] using LLM provider: [cyan]{type(client).__name__}[/]")

    cprint("\n[bold yellow]Stage 1[/] · Resolving spec…")
    resolved = resolve(base, client=client)
    cprint("[green]✓[/] Spec resolved")

    cprint("\n[bold yellow]Stage 2[/] · Generating components…")

    def _on_step(component, status):
        icon = {"running": "[cyan]…[/]", "done": "[green]✓[/]", "fail": "[red]✕[/]"}.get(status, " ")
        cprint(f"  {icon} {component}")

    lang_dir = generate_all(resolved, output_root=args.output, client=client, on_progress=_on_step)
    cprint(f"\n[green]✓[/] Generated [bold]{lang_dir}[/]")

    cprint("\n[bold yellow]Stage 3[/] · Verifying…")
    report = verify(lang_dir)
    cprint(report.summary())
    if not report.all_passed:
        cprint("\n[yellow]Verification failed: running repair loop…[/]")
        report = repair_run(lang_dir, client=client)
        cprint(report.summary())

    if report.all_passed:
        cprint(f"\n[green bold]Done.[/] Try it: [cyan]cd {lang_dir} && pip install -e . && {name} examples/fibonacci{resolved['file_extension']}[/]")
    return 0 if report.all_passed else 1


def cmd_verify(args):
    report = verify(args.lang_dir)
    print(report.summary())
    return 0 if report.all_passed else 1


def cmd_repair(args):
    from .orchestrator.providers import make_client
    from .orchestrator.repair import repair_run
    client = make_client(args.provider, log_dir=Path(args.lang_dir) / ".forge_log")
    report = repair_run(args.lang_dir, client=client)
    print(report.summary())
    return 0 if report.all_passed else 1


def cmd_gui(args):
    try:
        from .gui.app import run_gui
    except ModuleNotFoundError as e:
        missing = e.name or "a dependency"
        print(f"Missing dependency: {missing}", file=sys.stderr)
        print(
            "Install Forge's GUI dependencies with one of:\n"
            f"  pip install {missing}\n"
            "  pip install -e .[dev]    (from the workspace root)\n"
            "  pip install flask anthropic lark jsonschema jinja2",
            file=sys.stderr,
        )
        return 2
    run_gui(port=args.port, open_browser=not args.no_open)
    return 0


def cmd_init(args):
    """Scaffold a starter project for an existing language."""
    from .scaffold import init_project
    try:
        out = init_project(
            project_name=args.name,
            lang=args.lang,
            parent_dir=Path(args.dir).resolve() if args.dir else None,
        )
    except (FileExistsError, FileNotFoundError, ValueError) as e:
        cprint(f"[red]error:[/] {e}")
        return 1
    cprint(f"[green]Scaffolded[/] [bold]{out}[/]")
    cprint(f"  cd {out}")
    cprint(f"  ./run.sh main{out.glob('main.*').__next__().suffix}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="forge", description="Language Forge")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="Create a new language")
    p_create.add_argument("--syntax", choices=["c_like", "python_like"])
    p_create.add_argument("--typing", choices=["static", "dynamic"])
    p_create.add_argument("--memory", choices=["host_gc", "refcount"])
    p_create.add_argument("--name", help="Language name (e.g. mylang)")
    p_create.add_argument("--output", default="generated", help="Output root (default: generated)")
    p_create.add_argument("--provider", choices=["api", "claude_cli"], default=None,
                          help="LLM provider (default: api if ANTHROPIC_API_KEY set, else claude_cli)")
    # Extended options (Tier 1 from forge-extended-options.md). All optional.
    p_create.add_argument("--comment-style", choices=["line", "block", "both", "nestable_block"])
    p_create.add_argument("--string-literals", choices=["single", "double", "both", "triple_quoted", "raw_and_normal"])
    p_create.add_argument("--numeric-literals", choices=["decimal_only", "c_style", "extended"])
    p_create.add_argument("--mutability", dest="default_mutability", choices=["mutable", "immutable"])
    p_create.add_argument("--error-handling", choices=["panic_only", "exceptions", "result_type"])
    p_create.add_argument("--loop-forms", help="Comma-separated subset of: while, c_for, foreach, repeat_until, loop_break")
    p_create.add_argument("--multiple-returns", choices=["none", "tuple", "named"])
    p_create.add_argument("--boolean-evaluation", choices=["short_circuit", "eager"])
    p_create.add_argument("--naming-convention", choices=["snake_case", "camelCase", "PascalCase"])
    p_create.add_argument("--null-model", choices=["nullable", "option", "none"])
    p_create.set_defaults(func=cmd_create)

    p_verify = sub.add_parser("verify", help="Verify a generated language")
    p_verify.add_argument("lang_dir")
    p_verify.set_defaults(func=cmd_verify)

    p_repair = sub.add_parser("repair", help="Run repair loop on the last failure")
    p_repair.add_argument("lang_dir")
    p_repair.add_argument("--provider", choices=["api", "claude_cli"], default=None)
    p_repair.set_defaults(func=cmd_repair)

    p_gui = sub.add_parser("gui", help="Launch the browser-based GUI")
    p_gui.add_argument("--port", type=int, default=5173)
    p_gui.add_argument("--no-open", action="store_true", help="Don't auto-open the browser")
    p_gui.set_defaults(func=cmd_gui)

    p_init = sub.add_parser("init", help="Scaffold a starter project that uses an existing language")
    p_init.add_argument("name", help="Project directory name (must be a Python identifier)")
    p_init.add_argument("--lang", default="toylang", help="Existing language name (default: toylang)")
    p_init.add_argument("--dir", default=None, help="Parent directory (default: current dir)")
    p_init.set_defaults(func=cmd_init)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
