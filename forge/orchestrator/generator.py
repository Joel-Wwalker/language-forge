"""Stage 3: Component Generator.

For each component (lexer, parser, typechecker?, codegen, runtime, stdlib,
tests, readme) we load the per-component prompt, send it to the LLM with the
resolved spec interpolated in, and write the result to disk.

Components run in dependency order. The typechecker is skipped when the spec
chose dynamic typing.

After all components are written, a Jinja-rendered `compile.py` is written from
the templates so the language has a stable user-facing CLI.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Callable, Iterable, Optional

from jinja2 import Environment, FileSystemLoader

from .llm_client import LLMClient


PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"


# Order matters: each later component may reference names defined in earlier ones.
# `typechecker` is conditional on static typing; tests/readme don't change runtime.
COMPONENTS_DYNAMIC = ["lexer", "parser", "codegen", "runtime", "stdlib", "tests", "readme", "language_reference"]
COMPONENTS_STATIC = ["lexer", "parser", "typechecker", "codegen", "runtime", "stdlib", "tests", "readme", "language_reference"]

COMPONENT_FILENAMES = {
    "lexer": "lexer.py",
    "parser": "parser.py",
    "typechecker": "typechecker.py",
    "codegen": "codegen.py",
    "runtime": "runtime.py",
    "stdlib": "stdlib.py",
    "readme": "README.md",
    "language_reference": "LANGUAGE.md",
    # 'tests' is special: emits a directory.
}


def components_for(spec: dict) -> list[str]:
    return COMPONENTS_STATIC if spec["options"]["typing"] == "static" else COMPONENTS_DYNAMIC


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _interp(template: str, spec: dict, **extras) -> str:
    out = template.replace("{{SPEC}}", json.dumps(spec, indent=2))
    for k, v in extras.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def _user_customization_for(component: str, spec: dict) -> str:
    """User-supplied per-component instructions appended to the prompt.

    Reads `spec.customization.extra_prompt_notes[<component>]`. Falls back to
    an empty string if no notes were supplied for this component.
    """
    cust = spec.get("customization") or {}
    notes = (cust.get("extra_prompt_notes") or {}).get(component)
    if not notes:
        return ""
    notes = notes.strip()
    if not notes:
        return ""
    return (
        "\n\n## Additional instructions from the user (HIGH PRIORITY)\n\n"
        "These are user-supplied requirements for this component. Honor them "
        "exactly, even if they conflict with the defaults above.\n\n"
        f"{notes}\n"
    )


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-component generation
# ---------------------------------------------------------------------------

def _read_if_exists(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _sibling_context(name: str, lang_dir: Path) -> str:
    """Provide previously-generated sibling files as context for the next call.

    This is how we prevent interface drift: codegen MUST know the rule names
    in parser.py; runtime MUST know what codegen's PRELUDE imports; tests MUST
    know the actual syntax the parser accepts.
    """
    deps = {
        "parser":             [],
        "lexer":              ["parser.py"],
        "typechecker":        ["parser.py"],
        "codegen":            ["parser.py"],
        "runtime":            ["codegen.py"],
        "stdlib":             ["runtime.py"],
        "tests":              ["parser.py"],
        "readme":             ["parser.py", "tests"],
        "language_reference": ["parser.py", "runtime.py", "stdlib.py"],
    }
    files = deps.get(name, [])
    if not files:
        return ""
    parts = ["\n## Already-generated sibling files (treat as ground truth)\n"]
    for f in files:
        if f == "tests":
            tests_dir = lang_dir / "tests"
            if tests_dir.exists():
                names = sorted(p.name for p in tests_dir.iterdir())
                parts.append(f"\n### tests/ contains: {', '.join(names)}\n")
            continue
        path = lang_dir / f
        content = _read_if_exists(path)
        if content:
            ext = "python" if f.endswith(".py") else ""
            parts.append(f"\n### {f}\n\n```{ext}\n{content}\n```\n")
    return "".join(parts) if len(parts) > 1 else ""


def _generate_code_component(name: str, spec: dict, lang_dir: Path, client: LLMClient) -> Path:
    prompt = (
        _interp(_load_prompt(name), spec)
        + _sibling_context(name, lang_dir)
        + _user_customization_for(name, spec)
    )
    code = client.call_code(prompt, tag=f"gen-{name}")
    target = lang_dir / COMPONENT_FILENAMES[name]
    _write(target, code)
    return target


def _generate_readme(spec: dict, lang_dir: Path, client: LLMClient) -> Path:
    prompt = (
        _interp(_load_prompt("readme"), spec)
        + _user_customization_for("readme", spec)
    )
    md = client.call_code(prompt, tag="gen-readme")
    target = lang_dir / "README.md"
    _write(target, md)
    return target


def _generate_language_reference(spec: dict, lang_dir: Path, client: LLMClient) -> Path:
    """Emit `LANGUAGE.md`: the formal language reference."""
    prompt = (
        _interp(_load_prompt("language_reference"), spec)
        + _sibling_context("language_reference", lang_dir)
        + _user_customization_for("language_reference", spec)
    )
    md = client.call_code(prompt, tag="gen-language-ref")
    target = lang_dir / "LANGUAGE.md"
    _write(target, md)
    return target


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)
_CANONICAL_TESTS = [
    "hello_world", "arithmetic", "variables", "conditionals",
    "loops", "functions", "closures", "strings",
]


def _write_test_files(tests_dir: Path, files: dict, ext: str) -> set[str]:
    """Write a {filename: contents} mapping into tests_dir. Returns the set of
    canonical test names successfully written (i.e. has both source AND
    expected_output)."""
    written: set[str] = set()
    for filename, contents in files.items():
        filename = filename.replace("<EXT>", ext)
        safe = Path(filename).name
        if not safe:
            continue
        (tests_dir / safe).write_text(contents, encoding="utf-8")
    # Recompute which canonicals are complete pairs.
    for name in _CANONICAL_TESTS:
        src = tests_dir / f"{name}{ext}"
        exp = tests_dir / f"{name}.expected_output.txt"
        if src.exists() and src.stat().st_size > 0 and exp.exists() and exp.stat().st_size > 0:
            written.add(name)
    return written


def _parse_tests_json(raw: str) -> Optional[dict]:
    """Best-effort parse of the tests prompt response.

    Tries: direct json.loads, fenced ```json block, fenced unlabeled block,
    largest-balanced-object fallback. Returns None if nothing parses.
    """
    text = raw.strip()
    # 1) Direct
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2) Fenced (json or unlabeled)
    for m in _JSON_FENCE_RE.finditer(text):
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
    # 3) Greedy: longest-balanced object
    best = None
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                snippet = text[start:i+1]
                try:
                    parsed = json.loads(snippet)
                    if best is None or len(snippet) > len(json.dumps(best)):
                        best = parsed
                except json.JSONDecodeError:
                    pass
                start = -1
    return best


def _generate_tests(spec: dict, lang_dir: Path, client: LLMClient) -> Path:
    """Generate the 8 canonical tests.

    Strategy:
      A. Try the bulk prompt (one call returns a JSON object with all 8 pairs).
      B. If A fails (invalid JSON, missing tests, or zero output) fall back to
         per-test generation: one prompt per missing canonical.
      C. After all attempts, if we still don't have all 8 canonical pairs,
         raise so the caller knows generation failed.
    """
    ext = spec["file_extension"]
    tests_dir = lang_dir / "tests"
    if tests_dir.exists():
        shutil.rmtree(tests_dir)
    tests_dir.mkdir(parents=True, exist_ok=True)

    # ---- A: bulk attempt ----
    bulk_prompt = (
        _interp(_load_prompt("tests"), spec)
        + _sibling_context("tests", lang_dir)
        + _user_customization_for("tests", spec)
    )
    raw = client.call_code(bulk_prompt, tag="gen-tests-bulk")
    files = _parse_tests_json(raw) or {}
    written = _write_test_files(tests_dir, files, ext) if isinstance(files, dict) else set()

    # ---- A.5: write user-supplied additional tests verbatim ----
    additional = (spec.get("customization") or {}).get("additional_tests") or []
    for t in additional:
        name = t["name"]
        src = t["source"]
        expected = t["expected"]
        # Ensure trailing newline on expected (verifier rstrips for compare anyway)
        if not expected.endswith("\n"):
            expected += "\n"
        (tests_dir / f"{name}{ext}").write_text(src, encoding="utf-8")
        (tests_dir / f"{name}.expected_output.txt").write_text(expected, encoding="utf-8")

    # ---- B: fallback per-test ----
    missing = [c for c in _CANONICAL_TESTS if c not in written]
    if missing:
        for canonical in missing:
            try:
                _generate_one_test(canonical, spec, tests_dir, lang_dir, client)
            except Exception as e:
                # Continue trying others; we'll raise below if we can't recover.
                (tests_dir / f"{canonical}.error.log").write_text(
                    f"{type(e).__name__}: {e}\n", encoding="utf-8"
                )

    # ---- C: final validation ----
    final_written = set()
    for c in _CANONICAL_TESTS:
        src = tests_dir / f"{c}{ext}"
        exp = tests_dir / f"{c}.expected_output.txt"
        if src.exists() and exp.exists() and src.stat().st_size and exp.stat().st_size:
            final_written.add(c)
    if len(final_written) < len(_CANONICAL_TESTS):
        still_missing = sorted(set(_CANONICAL_TESTS) - final_written)
        raise RuntimeError(
            f"tests generation incomplete: missing {still_missing}. "
            f"See {lang_dir}/.forge_log/ for prompts/responses."
        )
    return tests_dir


_PER_TEST_PROMPT = """\
Generate ONE canonical test for the language described below.

Test name: `{name}`
Test description: {desc}

## Resolved spec

```json
{spec_json}
```

## Output

Return EXACTLY two fenced code blocks, in this order:

1. A fenced block labeled `source` containing the program source.
2. A fenced block labeled `expected` containing the exact expected stdout.

Both blocks should be raw text: no JSON, no escaping. The expected block
must end with a single trailing newline. Use the spec's syntax exactly.

Example shape:

```source
print("Hello, World!")
```

```expected
Hello, World!
```
"""

_TEST_DESCRIPTIONS = {
    "hello_world": "prints `Hello, World!` (no surrounding quotes in stdout).",
    "arithmetic": "exercises +, -, *, %, operator precedence, and parenthesization with multiple print lines.",
    "variables": "declaration, reassignment, reuse with multiple print lines (numeric and string).",
    "conditionals": "if/elif/else, comparison operators, AND a logical-and AND a logical-or test.",
    "loops": "while or for, summing 1..10 → prints `55`.",
    "functions": "definition, call, return, recursion. Print factorial(5) (=120) and at least one other call.",
    "closures": "function returning a function that captures and mutates a variable (counter pattern). Print 3 increments.",
    "strings": "concatenation, the spec's `len` builtin, and a print with multiple mixed-type arguments.",
}


_SOURCE_FENCE_RE = re.compile(r"```(?:source|src)?\s*\n(.*?)```", re.DOTALL)
_EXPECTED_FENCE_RE = re.compile(r"```(?:expected|stdout|output)?\s*\n(.*?)```", re.DOTALL)


def _generate_one_test(name: str, spec: dict, tests_dir: Path, lang_dir: Path,
                       client: LLMClient) -> None:
    prompt = _PER_TEST_PROMPT.format(
        name=name,
        desc=_TEST_DESCRIPTIONS[name],
        spec_json=json.dumps(spec, indent=2),
    ) + _sibling_context("tests", lang_dir)
    raw = client.call_code(prompt, tag=f"gen-test-{name}")
    # Find the two fenced blocks. Prefer labeled, but fall back to "first two
    # consecutive fenced blocks" if the model didn't label them.
    fences = re.findall(r"```([\w]*)\s*\n(.*?)```", raw, re.DOTALL)
    if len(fences) < 2:
        raise RuntimeError(f"per-test response had < 2 fenced blocks for {name}")
    source = None
    expected = None
    for label, body in fences:
        if label.lower() in ("source", "src") and source is None:
            source = body
        elif label.lower() in ("expected", "stdout", "output") and expected is None:
            expected = body
    if source is None:
        source = fences[0][1]
    if expected is None:
        expected = fences[1][1]
    ext = spec["file_extension"]
    (tests_dir / f"{name}{ext}").write_text(source.rstrip() + "\n", encoding="utf-8")
    (tests_dir / f"{name}.expected_output.txt").write_text(
        expected.rstrip() + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Final templating: __init__.py + compile.py
# ---------------------------------------------------------------------------

def _render_templates(spec: dict, lang_dir: Path) -> None:
    """Render all deterministic packaging files (no LLM).

    Produces __init__.py, compile.py, pyproject.toml, LICENSE, INSTALL.md.
    These are the files that make the language directory installable as a
    standalone Python package.
    """
    import datetime as _dt

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )
    ctx = {
        "lang_name": spec["lang_name"],
        "file_extension": spec["file_extension"],
        "static_typing": spec["options"]["typing"] == "static",
        "syntax": spec["options"]["syntax"],
        "typing": spec["options"]["typing"],
        "memory": spec["options"]["memory"],
        "year": _dt.datetime.now().year,
    }
    rendered = {
        "__init__.py":   env.get_template("package_init.py.j2").render(**ctx),
        "compile.py":    env.get_template("compiler_entry.py.j2").render(**ctx),
        "pyproject.toml": env.get_template("pyproject.toml.j2").render(**ctx),
        "LICENSE":       env.get_template("LICENSE.j2").render(**ctx),
        "INSTALL.md":    env.get_template("INSTALL.md.j2").render(**ctx),
    }
    for filename, content in rendered.items():
        (lang_dir / filename).write_text(content, encoding="utf-8")


def render_standalone_repl(spec: dict, lang_dir: Path) -> str:
    """Render a single self-contained HTML file that runs the language in the
    browser via Pyodide. Returns the HTML content; also writes it to
    `<lang>/repl.html`.

    The compiler source files are embedded as a JSON blob in a `<script>` tag.
    On page load, the JS writes those into Pyodide's virtual filesystem and
    imports them like a normal Python package.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        keep_trailing_newline=True,
    )

    # Collect the compiler source files we need on the client side.
    # Note: stdlib.py and runtime.py both ship; tests/ are excluded (loaded as examples below).
    embed = {}
    for fname in ("__init__.py", "lexer.py", "parser.py", "codegen.py",
                  "runtime.py", "stdlib.py"):
        path = lang_dir / fname
        if path.exists():
            embed[fname] = path.read_text(encoding="utf-8")
    typechecker = lang_dir / "typechecker.py"
    if typechecker.exists():
        embed["typechecker.py"] = typechecker.read_text(encoding="utf-8")

    # Bundle canonical tests + curated examples as runnable demos.
    examples = {}
    ext = spec["file_extension"]
    tests_dir = lang_dir / "tests"
    if tests_dir.exists():
        for name in ("hello_world", "arithmetic", "variables", "conditionals",
                     "loops", "functions", "closures", "strings"):
            src = tests_dir / f"{name}{ext}"
            if src.exists():
                examples[name] = src.read_text(encoding="utf-8")
    examples_dir = lang_dir / "examples"
    if examples_dir.exists():
        for src in sorted(examples_dir.glob(f"*{ext}")):
            examples[src.stem] = src.read_text(encoding="utf-8")

    html = env.get_template("standalone_repl.html.j2").render(
        lang_name=spec["lang_name"],
        file_extension=ext,
        syntax=spec["options"]["syntax"],
        compiler_files_json=json.dumps(embed),
        examples_json=json.dumps(examples),
    )
    target = lang_dir / "repl.html"
    target.write_text(html, encoding="utf-8")
    return html


def apply_runtime_shim(lang_dir: Path) -> bool:
    """Append the deterministic stdlib shim to a language's runtime.py.

    Reads the LLM-generated runtime.py, identifies missing `toy_*` helpers
    we know the codegen PRELUDE will import, and appends source for just
    those from `templates/runtime_shim.py`.

    Returns True if the runtime was modified, False if no patch was needed.
    Idempotent: a marker comment prevents double-application.
    """
    rt_path = lang_dir / "runtime.py"
    if not rt_path.exists():
        return False
    rt_text = rt_path.read_text(encoding="utf-8")
    if "FORGE_STDLIB_SHIM_BEGIN" in rt_text:
        return False  # already applied; idempotent

    shim_path = TEMPLATES_DIR / "runtime_shim.py"
    if not shim_path.exists():
        return False
    shim_text = shim_path.read_text(encoding="utf-8")

    # Identify which helpers we need. The codegen PRELUDE imports these names.
    needed = [
        "toy_input", "toy_list", "toy_get", "toy_set", "toy_push", "toy_pop",
        "toy_dict", "toy_has", "toy_keys", "toy_range",
        "toy_split", "toy_join", "toy_upper", "toy_lower", "toy_replace",
        "toy_int", "toy_float",
        "toy_read_file", "toy_write_file", "toy_argv", "toy_exit",
    ]
    missing = [n for n in needed if f"def {n}" not in rt_text]
    if not missing:
        return False

    # Extract just the named defs from the shim source. Each helper sits
    # between two def-lines so we slice the file by `def <name>` markers.
    def _extract(name: str) -> str:
        marker = f"def {name}"
        idx = shim_text.find(marker)
        if idx < 0:
            return ""
        # Find next "def " at column 0 OR the shim end marker.
        end = shim_text.find("\ndef ", idx + 1)
        if end < 0:
            end = shim_text.find("# === FORGE_STDLIB_SHIM_END ===", idx + 1)
        return shim_text[idx:end].rstrip() + "\n\n"

    snippets = "".join(_extract(n) for n in missing if _extract(n))
    if not snippets:
        return False

    # Append a clearly-marked block.
    suffix = (
        "\n\n# === FORGE_STDLIB_SHIM_BEGIN ===\n"
        "# Auto-applied by Forge: deterministic stdlib helpers the codegen\n"
        "# PRELUDE imports. Do not edit between BEGIN/END markers; rerun the\n"
        "# generator to refresh.\n"
        "import sys as _shim_sys\n"
        "import builtins as _shim_builtins\n\n"
        + snippets
        + "# === FORGE_STDLIB_SHIM_END ===\n"
    )
    rt_path.write_text(rt_text.rstrip() + suffix, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Examples: only ship samples whose stdlib needs the language can satisfy.
# ---------------------------------------------------------------------------

# Each curated sample lists the stdlib functions it calls. The emitter only
# ships a sample if every required function is in the spec's stdlib (or in
# the patched runtime).
_SAMPLE_REQUIREMENTS = {
    "fizzbuzz":            {"print"},
    "fibonacci":           {"print"},
    "counter_factory":     {"print"},
    "string_manipulation": {"print", "len"},
    "wordcount":           {"print", "len", "split", "dict", "has", "set", "get", "keys"},
    "list_operations":     {"print", "len", "list", "get"},
    "args_demo":           {"print", "len", "argv", "get", "str"},
    "mandelbrot":          {"print"},
    "prime_sieve":         {"print", "list", "push", "set", "get", "len", "join"},
    "palindrome":          {"print", "len", "lower", "replace", "get", "list"},
    "ascii_tree":          {"print"},
}


def apply_codegen_prelude_patch(lang_dir: Path) -> bool:
    """Inject missing `toy_X as X` imports into codegen.py's PRELUDE.

    The codegen PRELUDE is a string literal in `codegen.py` that gets
    prepended to every transpiled program. Older LLM-generated codegens
    only imported print/len/str/truthy. After we shim runtime.py with
    new helpers, the codegen also needs to import them so user programs
    actually see them.

    Strategy: find the line `from <lang>.runtime import (` (or with no
    parens) and add any missing `toy_<name> as <name>` lines before the
    closing `)`. Idempotent: only adds names that aren't already there.

    Returns True if codegen.py was modified.
    """
    cg_path = lang_dir / "codegen.py"
    if not cg_path.exists():
        return False
    src = cg_path.read_text(encoding="utf-8")

    # Locate the import block. We accept either single-line or paren'd form.
    paren_match = re.search(
        r"from\s+\S+\.runtime\s+import\s*\(([^)]*)\)",
        src,
    )
    if not paren_match:
        return False    # no import block we can safely patch

    block = paren_match.group(1)
    existing_aliases = set(re.findall(r"toy_(\w+)\s+as\s+\w+", block))

    needed = {
        "input", "list", "get", "set", "push", "pop", "dict", "has", "keys", "range",
        "split", "join", "upper", "lower", "replace",
        "int", "float",
        "read_file", "write_file", "argv", "exit",
    }
    missing = sorted(needed - existing_aliases)
    if not missing:
        return False

    # Build added lines, indented to match existing style.
    indent = "    "
    addition = "\n" + "\n".join(f"{indent}toy_{n} as {n}," for n in missing) + "\n"

    # Insert just before the closing paren.
    new_block = block.rstrip() + addition
    new_import = f"from{paren_match.group(0)[paren_match.group(0).index(' '):paren_match.group(0).index('import')+6]} ({new_block})"
    # Simpler: replace inside the matched span.
    start, end = paren_match.span(1)
    new_src = src[:start] + new_block + src[end:]
    cg_path.write_text(new_src, encoding="utf-8")
    return True


def _codegen_imports(lang_dir: Path) -> set[str]:
    """Bare names that codegen.py's PRELUDE imports (and so user programs see)."""
    cg = lang_dir / "codegen.py"
    if not cg.exists():
        return {"print", "len", "str"}
    text = cg.read_text(encoding="utf-8")
    # Names brought into scope via `toy_X as Y` in the codegen's import block.
    found = set(re.findall(r"toy_\w+\s+as\s+(\w+)", text))
    found.update({"print", "len", "str"})
    return found


def _runtime_available_helpers(lang_dir: Path) -> set[str]:
    """Read the language's runtime.py and figure out which user-visible
    helpers actually exist.

    Returns the bare names (`print`, `list`, `argv`, etc.) by stripping the
    `toy_` prefix from every `def toy_<name>(` we find. This is more
    truthful than reading `spec.stdlib.functions`, which can lag behind
    when the runtime gets shimmed.
    """
    rt = lang_dir / "runtime.py"
    if not rt.exists():
        return {"print", "len", "str"}    # last-ditch default
    text = rt.read_text(encoding="utf-8")
    found = set()
    for m in re.finditer(r"^def\s+toy_(\w+)\s*\(", text, re.MULTILINE):
        found.add(m.group(1))
    # `print`, `len`, `str` are always available via the codegen PRELUDE
    # even on old languages with thin runtimes.
    found.update({"print", "len", "str"})
    return found


def _translate_comments(src: str, syntax: str, comment_syntax: dict) -> str:
    """Adapt a curated sample's comments to the language's comment_style.

    Curated samples are written in either c_like (`//`) or python_like (`#`)
    flavor. If the target language uses a different `comment_syntax`, rewrite
    the comments so the lexer accepts them.

    - block-only c_like: convert `// foo` to `/* foo */`
    - line-only c_like that prefers `#` (rare but possible): convert `// foo` to `# foo`
    - python_like languages always use the line `#` form which we already write
    """
    line_form = (comment_syntax or {}).get("line")
    block_open = (comment_syntax or {}).get("block_open")
    block_close = (comment_syntax or {}).get("block_close")

    out = []
    for raw in src.split("\n"):
        # Detect a c_like-style line comment we may need to rewrite.
        stripped = raw.lstrip()
        if stripped.startswith("//"):
            indent = raw[: len(raw) - len(stripped)]
            body = stripped[2:].lstrip()
            if line_form == "//":
                out.append(raw)                                  # already accepted
            elif line_form and line_form != "//":
                out.append(f"{indent}{line_form} {body}")        # e.g. `# foo`
            elif block_open and block_close:
                out.append(f"{indent}{block_open} {body} {block_close}")
            else:
                # Last resort: drop the comment entirely.
                out.append(indent.rstrip())
            continue
        if stripped.startswith("#") and line_form not in ("#", None):
            # python_like sample on a c_like target. Convert to `//`.
            indent = raw[: len(raw) - len(stripped)]
            body = stripped[1:].lstrip()
            if line_form == "//":
                out.append(f"{indent}// {body}")
            elif block_open and block_close:
                out.append(f"{indent}{block_open} {body} {block_close}")
            else:
                out.append(indent.rstrip())
            continue
        out.append(raw)
    return "\n".join(out)


def _compile_check(lang_dir: Path, source: str, timeout: float = 8.0) -> bool:
    """Try to parse + transpile `source` using the language's compiler.

    Returns True if both `parse()` and `generate()` succeed. We don't run
    the result; just checking the language can swallow the syntax. This
    catches grammars the LLM emitted with subtle gaps (no assignment-
    as-statement, no nested expressions, etc.) without requiring us to
    enumerate every possible gap.
    """
    import subprocess as _sp
    import sys as _sys
    import os as _os
    import tempfile as _tf

    lang_dir = lang_dir.resolve()         # ensure absolute path
    compile_py = lang_dir / "compile.py"
    if not compile_py.exists():
        return False
    with _tf.NamedTemporaryFile("w", suffix=".__check__", delete=False, encoding="utf-8") as f:
        f.write(source)
        tmp_path = f.name
    try:
        env = {**_os.environ, "PYTHONPATH": str(lang_dir.parent)}
        proc = _sp.run(
            [_sys.executable, str(compile_py), tmp_path],
            capture_output=True, text=True, timeout=timeout,
            cwd=str(lang_dir), env=env,
        )
        return proc.returncode == 0
    except (_sp.TimeoutExpired, OSError):
        return False
    finally:
        try:
            _os.unlink(tmp_path)
            # Also clean up the .out.py compile.py wrote next to the source
            _os.unlink(tmp_path + ".out.py")
        except OSError:
            pass


def _emit_examples(spec: dict, lang_dir: Path) -> None:
    """Ship curated samples to <lang>/examples/. Filter by what the runtime
    actually exposes so we never write a sample that calls a missing helper.
    Translate comments per-language so the lexer always accepts them.
    """
    try:
        from forge.gui.samples import SAMPLES, get_sample
    except Exception:
        return
    examples_dir = lang_dir / "examples"
    examples_dir.mkdir(exist_ok=True)
    syntax = spec["options"]["syntax"]
    ext = spec["file_extension"]
    comment_syntax = spec.get("comment_syntax") or {}

    # A sample is shippable only when BOTH (a) the runtime has the helper
    # and (b) codegen's PRELUDE imports it. Either gap breaks the example.
    available = _runtime_available_helpers(lang_dir) & _codegen_imports(lang_dir)

    written = []
    for key in SAMPLES:
        needs = _SAMPLE_REQUIREMENTS.get(key, set())
        stale = examples_dir / f"{key}{ext}"
        if not needs.issubset(available):
            if stale.exists():
                try: stale.unlink()
                except OSError: pass
            continue
        src = get_sample(key, syntax)
        if not src:
            continue
        translated = _translate_comments(src, syntax, comment_syntax)
        # Real check: actually try to compile the sample through the
        # language's own parser+codegen. Any failure (syntax not supported,
        # operator missing, etc.) means we skip it cleanly.
        if not _compile_check(lang_dir, translated):
            if stale.exists():
                try: stale.unlink()
                except OSError: pass
            continue
        stale.write_text(translated, encoding="utf-8")
        written.append(key)

    # Drop a tiny README listing what shipped.
    listing = "\n".join(f"  - examples/{k}{ext}" for k in written) or "  (no examples)"
    readme = (
        f"# Examples for {spec['lang_name']}\n\n"
        f"Run any of these:\n\n"
        f"```bash\n"
        f"{spec['lang_name']} examples/<name>{ext} && python examples/<name>{ext}.out.py\n"
        f"```\n\n"
        f"Shipped:\n{listing}\n"
    )
    (examples_dir / "README.md").write_text(readme, encoding="utf-8")


# ---------------------------------------------------------------------------
# Top-level: generate everything
# ---------------------------------------------------------------------------

def generate_all(spec: dict, output_root: str | Path = "generated", *,
                 client: Optional[LLMClient] = None,
                 only: Optional[Iterable[str]] = None,
                 on_progress: Optional[Callable[[str, str], None]] = None) -> Path:
    """Generate every component for `spec` into `<output_root>/<lang_name>/`.

    If `only` is given, only those components are (re)generated.

    `on_progress(component, status)` is called as each component starts and
    finishes: used by the GUI to drive real-time progress updates. Status is
    one of: "running", "done", "fail".
    """
    lang_dir = Path(output_root) / spec["lang_name"]
    lang_dir.mkdir(parents=True, exist_ok=True)

    log_dir = lang_dir / ".forge_log"
    if client is None:
        client = LLMClient(log_dir=log_dir)
    elif client.log_dir is None:
        client.log_dir = log_dir

    # Persist the spec next to the generated source for verifier discovery.
    (lang_dir / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8"
    )

    components = list(components_for(spec))
    if only:
        components = [c for c in components if c in set(only)]

    def _emit(component, status):
        if on_progress:
            try:
                on_progress(component, status)
            except Exception:
                pass

    # Dependency graph: each component lists which others must finish first.
    # parser is the root; once it exists the lexer/typechecker/codegen/tests
    # can all run in parallel. Then runtime gates stdlib + readme + the
    # language reference. This roughly halves wall time vs sequential.
    DEPS = {
        "parser":             set(),
        "lexer":              {"parser"},
        "typechecker":        {"parser"},
        "codegen":            {"parser"},
        "tests":              {"parser"},
        "runtime":            {"codegen"},
        "stdlib":             {"runtime"},
        "readme":             {"tests"},
        "language_reference": {"stdlib"},
    }

    def _run_component(comp: str) -> None:
        if comp == "tests":
            _generate_tests(spec, lang_dir, client)
        elif comp == "readme":
            _generate_readme(spec, lang_dir, client)
        elif comp == "language_reference":
            _generate_language_reference(spec, lang_dir, client)
        else:
            _generate_code_component(comp, spec, lang_dir, client)

    needed = set(components)
    deps = {c: DEPS.get(c, set()) & needed for c in needed}
    pending = set(needed)
    done: set[str] = set()
    in_flight: dict = {}    # Future -> component name

    import concurrent.futures as _cf
    # 4 workers covers the widest fan-out (lexer, typechecker, codegen, tests).
    # The Anthropic SDK is HTTP-bound; the Claude CLI shells out to subprocess.
    # Both release the GIL during the network/process wait, so threads parallelize fine.
    with _cf.ThreadPoolExecutor(max_workers=4) as pool:
        while pending or in_flight:
            # Submit anything whose deps are satisfied.
            ready = [c for c in list(pending) if deps[c].issubset(done)]
            for c in ready:
                pending.remove(c)
                _emit(c, "running")
                in_flight[pool.submit(_run_component, c)] = c
            if not in_flight:
                if pending:
                    raise RuntimeError(f"dependency deadlock: pending={pending}, done={done}")
                break
            # Wait for any to finish, then loop to submit more if newly unblocked.
            done_futs, _ = _cf.wait(in_flight.keys(), return_when=_cf.FIRST_COMPLETED)
            for fut in done_futs:
                comp = in_flight.pop(fut)
                try:
                    fut.result()
                except Exception:
                    _emit(comp, "fail")
                    # Cancel pending submissions; let in-flight finish before re-raise.
                    for f in in_flight:
                        f.cancel()
                    raise
                _emit(comp, "done")
                done.add(comp)

    # Deterministic packaging: these are the files that make the language
    # directory pip-installable as a standalone package.
    _emit("packaging", "running")
    _render_templates(spec, lang_dir)
    # Patch the LLM-generated runtime.py with any missing stdlib helpers.
    # Idempotent: a marker comment prevents double-application.
    # Note: we deliberately do NOT auto-patch codegen.py's PRELUDE. LLM-
    # generated codegens can encode the PRELUDE as concatenated string
    # literals where regex-based injection breaks the Python parse. The
    # example-filter handles this safely by skipping samples whose helpers
    # the codegen doesn't import.
    apply_runtime_shim(lang_dir)
    _emit_examples(spec, lang_dir)
    # Single-HTML in-browser REPL (zero-install demo / shareable artifact).
    try:
        render_standalone_repl(spec, lang_dir)
    except Exception:
        # Don't fail the whole generation if the REPL renders poorly.
        pass
    _emit("packaging", "done")
    return lang_dir
