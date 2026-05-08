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

# Hand-written reference compilers shipped with Forge. When the user picks
# one of these syntax families, the orchestrator templates from the reference
# instead of asking the LLM to regenerate every component. That drops
# generation time from ~15min to seconds and removes a whole class of LLM
# bugs (e.g. closures emitting `(lambda : ()[-1])` from `...` placeholders).
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_COMPILERS = {
    "s_expression": WORKSPACE_ROOT / "generated" / "lisplang",
    "stack_based":  WORKSPACE_ROOT / "generated" / "forthlang",
    # Phase 1.5 Stage B: c_like now templates from toylang. This is the
    # core of the structural fix — c_like languages no longer pay 9 LLM
    # calls per generation for parser/codegen/runtime/stdlib/tests; they
    # template from toylang and apply spec-driven keyword/comment/string
    # substitutions via _template_from_reference's Stage A layer.
    # Languages with hostile constraints toylang can't represent should
    # use the LLM-driven path explicitly via `template_from_reference=
    # False` (Stage F flag).
    "c_like":       WORKSPACE_ROOT / "generated" / "toylang",
    # `python_like` deferred — no hand-written python_like reference
    # exists yet. When one lands (a hand-written hardcombo-style
    # reference), add it here.
}

# Components a reference compiler can supply verbatim (with module-name
# substitution). The remaining components (tests, readme, language_reference)
# still go through the LLM so they get language-specific personality.
TEMPLATABLE_COMPONENTS = {"parser", "lexer", "codegen", "runtime", "stdlib"}


# Order matters: each later component may reference names defined in earlier ones.
# `typechecker` is conditional on static typing; tests/readme don't change runtime.
COMPONENTS_DYNAMIC = ["lexer", "parser", "codegen", "runtime", "stdlib", "tests", "readme", "language_reference"]
COMPONENTS_STATIC = ["lexer", "parser", "typechecker", "codegen", "runtime", "stdlib", "tests", "readme", "language_reference"]

# Map component name -> LLM-call tag prefixes the component is allowed to
# emit. Per-component telemetry (`record_component(..., llm_calls_made=N)`)
# uses this to attribute calls without an over-counting delta-snapshot
# (which would double-count under the parallel ThreadPoolExecutor in
# `generate_all`).
#
# Discipline contract (pinned by tests/test_telemetry_tag_prefixes.py):
# every component listed in COMPONENTS_STATIC must have at least one
# prefix entry, and every prefix entry must map to a real component.
# A future component using a non-conforming tag silently gets 0 LLM
# calls attributed; the test prevents that.
COMPONENT_TAG_PREFIXES = {
    "parser":             ("gen-parser",),
    "lexer":              ("gen-lexer",),
    "typechecker":        ("gen-typechecker", "gen-typecheck"),
    "codegen":            ("gen-codegen",),
    "runtime":            ("gen-runtime",),
    "stdlib":             ("gen-stdlib",),
    "tests":              ("gen-tests",),
    "readme":             ("gen-readme",),
    "language_reference": ("gen-language-ref", "gen-language-reference"),
}

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


def reference_compiler_for(spec: dict) -> Optional[Path]:
    """Return the path to a hand-written reference compiler if one exists
    for this spec's syntax family, else None.

    As of Phase 1.5 Stage B, three families have references:
      - c_like        -> toylang
      - s_expression  -> lisplang
      - stack_based   -> forthlang

    The reference must have a working `parser.py`, `codegen.py`,
    `runtime.py`, `stdlib.py`, `lexer.py`, `__init__.py`, `compile.py`,
    and a `tests/` directory with the canonical 8 tests. The substitution
    layer in `_template_from_reference` applies spec-driven keyword,
    comment-syntax, and boolean/null literal overrides on top of the
    file copies so each templated child can be visibly distinct from
    the reference.
    """
    syntax = (spec.get("options") or {}).get("syntax")
    ref = REFERENCE_COMPILERS.get(syntax)
    if ref is None or not ref.exists():
        return None
    return ref


# ---------------------------------------------------------------------------
# Stage A (Phase 1.5) — substitution layer for _template_from_reference
# ---------------------------------------------------------------------------
#
# When templating from a reference compiler (toylang for c_like, etc.) we
# now apply parameterized substitutions to the copied files so the
# resulting language can have its OWN keyword spellings, comment syntax,
# and string-literal style — not just be a name-swapped clone.
#
# The substitutions are word-boundary regex on text. They're not AST-aware
# because the reference's source is structured enough (keywords appear as
# quoted Lark tokens or as bare-word source tokens) that careful regex
# does the right thing. Anything more invasive — e.g. naming-convention
# substitution that would rewrite stdlib function names — needs a real
# AST pass and is deferred to a follow-up stage.
#
# Per file-role substitution rules:
#   - parser.py: keyword overrides applied INSIDE the GRAMMAR triple-
#     quoted string only (so we don't touch Python code that mentions
#     keywords as data, e.g. `if "var" in tokens`). Comment-syntax
#     overrides applied to the LINE_COMMENT and BLOCK_COMMENT terminals.
#   - tests/<name><ext>: keyword + comment overrides applied as user-
#     facing source. Word-boundary regex.
#   - tests/<name>.expected_output.txt: substitute literal true/false/
#     null since toy_str renders these as whatever the spec says.
#   - runtime.py: substitute the literal returns in toy_str (the
#     `return "true"` / `return "false"` / `return "null"` lines).
#   - codegen.py / lexer.py / stdlib.py: only the existing module-name
#     swap; their internal Python keywords (`return`, `if`, etc.) are
#     Python keywords for the host, not target-language keywords.

_KEYWORD_ROLES = (
    "var", "func", "if", "else", "while", "return",
    "true", "false", "null",
)


def _keyword_overrides_from_spec(spec: dict) -> dict[str, str]:
    """Build a {canonical: spelling} mapping for keyword substitution.

    Sources, in priority order:
      1. spec.customization.keyword_overrides (already a {canon: spelling}
         dict; produced by themes / phrasebooks via spec_builder).
      2. Structured spec fields (variable_declaration.keyword,
         function_definition.keyword, ...) for cases where overrides
         got embedded structurally instead of via the override dict.

    Falls back to identity for any role not specified."""
    cust = spec.get("customization") or {}
    direct = dict(cust.get("keyword_overrides") or {})
    # Backfill from structured spec fields (cheap correctness — these
    # are usually consistent with keyword_overrides but not always).
    structured = {
        "var":    (spec.get("variable_declaration") or {}).get("keyword"),
        "func":   (spec.get("function_definition") or {}).get("keyword"),
        "if":     (spec.get("if_statement") or {}).get("keyword"),
        "else":   (spec.get("if_statement") or {}).get("else_keyword"),
        "while":  (spec.get("while_statement") or {}).get("keyword"),
        "return": (spec.get("return_statement") or {}).get("keyword"),
    }
    for role, value in structured.items():
        if value and role not in direct:
            direct[role] = value
    # Identity fallback so the substitution loop can iterate uniformly.
    return {role: direct.get(role, role) for role in _KEYWORD_ROLES}


def _comment_syntax_from_spec(spec: dict) -> dict:
    """Return the spec's comment syntax. Defaults to c_like (// + /* */)
    when fields are absent."""
    cs = spec.get("comment_syntax") or {}
    return {
        "line": cs.get("line") or "//",
        "block_open": cs.get("block_open") or "/*",
        "block_close": cs.get("block_close") or "*/",
    }


def _substitute_grammar_keywords(grammar: str, overrides: dict[str, str]) -> str:
    """Substitute keyword spellings inside a Lark grammar string.

    Targets bare quoted-string occurrences like `"var"` or `"func"` —
    these are the anonymous tokens in toylang's grammar. The
    `re.escape` on the value prevents any new spelling from being
    interpreted as regex metachars.
    """
    out = grammar
    for canon, new in overrides.items():
        if new == canon:
            continue
        # Match `"canon"` exactly (with the surrounding quotes); replace
        # with `"new"`. Quotes are part of the match so we don't touch
        # bare identifiers named after the keyword.
        out = re.sub(rf'"{re.escape(canon)}"', f'"{new}"', out)
    return out


def _substitute_grammar_comments(grammar: str, comment: dict) -> str:
    """Substitute the LINE_COMMENT and BLOCK_COMMENT terminals in a
    Lark grammar string when the spec uses non-toylang comment syntax.
    Toylang's defaults are `// ... \\n` line comments and `/* ... */`
    block comments. If the spec changes either, swap the terminal."""
    out = grammar
    new_line = comment["line"]
    new_open = comment["block_open"]
    new_close = comment["block_close"]
    if new_line != "//":
        # `LINE_COMMENT: "//" /[^\n]*/`
        out = re.sub(
            r'LINE_COMMENT:\s*"//"',
            f'LINE_COMMENT: "{new_line}"',
            out,
        )
    if new_open != "/*" or new_close != "*/":
        # `BLOCK_COMMENT: "/*" /(.|\\n)*?/ "*/"`
        out = re.sub(
            r'BLOCK_COMMENT:\s*"/\*"\s*/\(\.\|\\n\)\*\?/\s*"\*/"',
            f'BLOCK_COMMENT: "{re.escape(new_open)}" /(.|\\n)*?/ "{re.escape(new_close)}"',
            out,
        )
    return out


def _substitute_source_keywords(source: str, overrides: dict[str, str]) -> str:
    """Word-boundary substitution of keyword spellings in a target-
    language source file (e.g. tests/variables.toy). Won't touch
    keywords inside string literals (a future hardening; for now we
    accept that string-literal collisions are rare in the canonical
    tests)."""
    out = source
    for canon, new in overrides.items():
        if new == canon:
            continue
        out = re.sub(rf'\b{re.escape(canon)}\b', new, out)
    return out


def _substitute_source_comments(source: str,
                                old: dict, new: dict) -> str:
    """Replace comment markers in a source file. Skips work when the
    syntax is unchanged."""
    out = source
    if new["line"] != old["line"]:
        # Line-comment markers: replace at start-of-line or after
        # whitespace. We use a simple text replace because the markers
        # are punctuation, not word-bounded — `re.sub(r'\b//\b', ...)`
        # would not match `//` since neither side is a word char.
        out = out.replace(old["line"], new["line"])
    if new["block_open"] != old["block_open"]:
        out = out.replace(old["block_open"], new["block_open"])
    if new["block_close"] != old["block_close"]:
        out = out.replace(old["block_close"], new["block_close"])
    return out


def _substitute_runtime_str_literals(runtime_src: str,
                                     overrides: dict[str, str]) -> str:
    """In runtime.py's toy_str (or equivalent), the rendered names for
    True / False / None are baked in as `return "true"`, `return
    "false"`, `return "null"`. If the spec maps those keywords to new
    spellings, the renderer should output the new spellings too —
    otherwise the canonical conditionals test would fail (the
    expected_output.txt file we'll have substituted to say `aye` but
    toy_str would still emit `true`)."""
    out = runtime_src
    for canon in ("true", "false", "null"):
        new = overrides.get(canon, canon)
        if new == canon:
            continue
        # Match `return "canon"` exactly. The .py source uses double
        # quotes for these literals in toylang's runtime; if a future
        # reference uses single quotes we'd extend the pattern.
        out = re.sub(
            rf'return\s+"{re.escape(canon)}"',
            f'return "{new}"',
            out,
        )
    return out


def _apply_template_substitutions(spec: dict, text: str, *,
                                  file_role: str) -> str:
    """Apply the appropriate substitutions for a file's role.

    file_role: "parser" | "runtime" | "test_source" | "expected_output" |
               "module_swap_only" (codegen / lexer / stdlib / __init__ /
               compile)."""
    overrides = _keyword_overrides_from_spec(spec)
    new_comment = _comment_syntax_from_spec(spec)
    old_comment = {"line": "//", "block_open": "/*", "block_close": "*/"}

    if file_role == "parser":
        # Find the GRAMMAR triple-quoted string and substitute inside it.
        # toylang declares it as `GRAMMAR = r"""..."""`. We match that
        # form and apply substitutions inside the body.
        m = re.search(r'(GRAMMAR\s*=\s*r?""")(.*?)(""")', text, re.DOTALL)
        if not m:
            return text
        head, body, tail = m.group(1), m.group(2), m.group(3)
        body = _substitute_grammar_keywords(body, overrides)
        body = _substitute_grammar_comments(body, new_comment)
        return text[:m.start()] + head + body + tail + text[m.end():]

    if file_role == "runtime":
        return _substitute_runtime_str_literals(text, overrides)

    if file_role == "test_source":
        out = _substitute_source_keywords(text, overrides)
        out = _substitute_source_comments(out, old_comment, new_comment)
        return out

    if file_role == "expected_output":
        # Word-boundary substitution of true/false/null only. Other
        # keywords don't appear in canonical expected outputs.
        out = text
        for canon in ("true", "false", "null"):
            new = overrides.get(canon, canon)
            if new != canon:
                out = re.sub(rf'\b{re.escape(canon)}\b', new, out)
        return out

    return text  # module_swap_only — handled by the existing _rewrite


def _template_from_reference(spec: dict, lang_dir: Path,
                             ref_dir: Path) -> set[str]:
    """Copy the reference compiler's core files into `lang_dir`, swapping
    the package name and applying spec-driven substitutions. Returns the
    set of components that have been fulfilled by the template (so
    generate_all can skip them).

    Substitutions performed:
      Module name swaps (everywhere):
        - `from <ref_name>.runtime import` → `from <lang_name>.runtime import`
        - `import <ref_name>.X` → `import <lang_name>.X`
        - CLI prog name + `-m <ref_name>` doc strings.
      Spec-driven substitutions (Phase 1.5 Stage A):
        - parser.py: keyword spellings inside the GRAMMAR string,
          comment-syntax inside LINE_COMMENT / BLOCK_COMMENT terminals.
        - runtime.py: literal returns in toy_str (`return "true"` →
          `return "<spec.true>"`).
        - tests/<name><ext>: keyword spellings + comment markers in
          test source so the templated parser accepts them.
        - tests/<name>.expected_output.txt: true/false/null literals
          substituted so they match what the templated runtime emits.

    File extension in tests is rewritten from the reference's extension
    (`.lsp`) to the spec's `file_extension`.
    """
    ref_name = ref_dir.name           # e.g. "lisplang"
    lang_name = spec["lang_name"]     # e.g. "mylisp"
    target_ext = spec["file_extension"]
    # Detect the reference's extension by inspecting one of its tests.
    ref_ext = ".lsp"
    ref_tests = ref_dir / "tests"
    if ref_tests.exists():
        for f in ref_tests.iterdir():
            if f.suffix and f.suffix not in (".txt",):
                ref_ext = f.suffix
                break

    fulfilled: set[str] = set()

    def _rewrite(text: str) -> str:
        # Module name swaps. Doing the import-statement form first prevents
        # accidentally rewriting the word "lisplang" inside a docstring or
        # comment.
        out = text
        out = out.replace(f"from {ref_name}.", f"from {lang_name}.")
        out = out.replace(f"import {ref_name}.", f"import {lang_name}.")
        # CLI prog name + the `python -m <ref_name>.compile` doc string.
        out = out.replace(f"prog=\"{ref_name}\"", f"prog=\"{lang_name}\"")
        out = out.replace(f"-m {ref_name}", f"-m {lang_name}")
        return out

    # 1. Code components. The role determines which spec-driven
    # substitutions apply on top of the module-name swap.
    file_to_component_role = {
        "parser.py":  ("parser", "parser"),
        "lexer.py":   ("lexer",  "module_swap_only"),
        "codegen.py": ("codegen","module_swap_only"),
        "runtime.py": ("runtime","runtime"),
        "stdlib.py":  ("stdlib", "module_swap_only"),
    }
    for fname, (comp, role) in file_to_component_role.items():
        src_path = ref_dir / fname
        if not src_path.exists():
            continue
        dst_path = lang_dir / fname
        text = src_path.read_text(encoding="utf-8")
        text = _rewrite(text)
        text = _apply_template_substitutions(spec, text, file_role=role)
        dst_path.write_text(text, encoding="utf-8")
        fulfilled.add(comp)

    # 2. __init__.py and compile.py — module name swap only; no
    # target-language keywords appear in these.
    for fname in ("__init__.py", "compile.py"):
        src_path = ref_dir / fname
        if not src_path.exists():
            continue
        text = src_path.read_text(encoding="utf-8")
        (lang_dir / fname).write_text(_rewrite(text), encoding="utf-8")

    # 3. Canonical tests. Test sources get keyword + comment
    # substitutions so the templated parser accepts them. Expected-
    # output files get true/false/null substitutions so they match
    # what the templated runtime emits.
    if ref_tests.exists():
        dst_tests = lang_dir / "tests"
        dst_tests.mkdir(exist_ok=True)
        for src_file in ref_tests.iterdir():
            if not src_file.is_file():
                continue
            text = src_file.read_text(encoding="utf-8")
            if src_file.suffix == ".txt":
                # `<name>.expected_output.txt`
                text = _apply_template_substitutions(
                    spec, text, file_role="expected_output")
                (dst_tests / src_file.name).write_text(text, encoding="utf-8")
            elif src_file.suffix == ref_ext:
                text = _apply_template_substitutions(
                    spec, text, file_role="test_source")
                stem = src_file.stem
                (dst_tests / f"{stem}{target_ext}").write_text(
                    text, encoding="utf-8")
        fulfilled.add("tests")

    return fulfilled


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
    # Templated languages (s_expression / stack_based) get a deterministic
    # README rendered from the spec instead of an LLM call. Saves 10-30s
    # of API latency and stays consistent with the hand-written reference
    # compiler. Only the c_like / python_like / phrasebook languages, which
    # already vary widely, still go through the LLM for a personality-
    # driven readme.
    if reference_compiler_for(spec) is not None:
        target = lang_dir / "README.md"
        _write(target, _render_templated_readme(spec))
        return target
    prompt = (
        _interp(_load_prompt("readme"), spec)
        + _user_customization_for("readme", spec)
    )
    md = client.call_code(prompt, tag="gen-readme")
    target = lang_dir / "README.md"
    _write(target, md)
    return target


def _render_templated_readme(spec: dict) -> str:
    """Deterministic README for templated languages. We know the surface
    syntax + semantics exactly (they came from a hand-written reference)
    so a parameterized template is more accurate than an LLM call."""
    name = spec["lang_name"]
    syntax = spec["options"]["syntax"]
    typing = spec["options"]["typing"]
    memory = spec["options"]["memory"]
    ext = spec["file_extension"]
    origin = spec.get("origin_story") or ""
    func_ex = (spec.get("function_definition") or {}).get("syntax_example", "")
    var_ex  = (spec.get("variable_declaration") or {}).get("syntax_example", "")
    print_ex = spec.get("print_form", "")
    family_blurb = {
        "s_expression": "Lisp-style: every form is `(operator operand ...)`. Code is data.",
        "stack_based":  "Forth-style: postfix evaluation on an implicit data stack.",
    }.get(syntax, "")

    lines = [f"# {name}\n"]
    if origin:
        lines.append(f"_{origin.strip()}_\n")
    lines.append(f"A {syntax} language with {typing} typing and {memory} memory.\n")
    if family_blurb:
        lines.append(family_blurb + "\n")
    lines.append("## At a glance\n")
    lines.append("```")
    if func_ex: lines.append(func_ex)
    if var_ex:  lines.append(var_ex)
    if print_ex: lines.append(print_ex)
    lines.append("```\n")
    lines.append("## Run\n")
    lines.append(f"```bash")
    lines.append(f"python -m {name}.compile path/to/program{ext}")
    lines.append(f"python path/to/program{ext}.out.py")
    lines.append("```\n")
    lines.append("## Examples\n")
    lines.append(f"See `examples/` and `tests/` for working programs.")
    lines.append(f"Each canonical test (`hello_world{ext}`, `arithmetic{ext}`, ...) is")
    lines.append(f"verified end-to-end.")
    return "\n".join(lines) + "\n"


def _render_templated_language_reference(spec: dict) -> str:
    """Deterministic LANGUAGE.md for templated languages. Spec already
    documents every surface form; we just lay it out as Markdown."""
    name = spec["lang_name"]
    syntax = spec["options"]["syntax"]
    fd = spec.get("function_definition") or {}
    vd = spec.get("variable_declaration") or {}
    cs = spec.get("comment_syntax") or {}
    bk = spec.get("boolean_keywords") or {}
    ops = spec.get("operators") or {}

    lines = [f"# {name} language reference\n"]
    lines.append(f"Family: **{syntax}**.")
    lines.append(f"Typing: **{spec['options']['typing']}**.")
    lines.append(f"Memory: **{spec['options']['memory']}**.\n")

    lines.append("## Lexical syntax\n")
    if cs.get("line"):
        lines.append(f"- Line comments: `{cs['line']}`")
    if cs.get("block_open") and cs.get("block_close"):
        lines.append(f"- Block comments: `{cs['block_open']} ... {cs['block_close']}`")
    lines.append(f"- Statement terminator: `{spec.get('statement_terminator')!r}`")
    lines.append(f"- Block style: {spec.get('block_style')}")
    lines.append("")

    lines.append("## Function definition\n")
    lines.append("```")
    lines.append(fd.get("syntax_example", ""))
    lines.append("```\n")

    lines.append("## Variable declaration\n")
    lines.append("```")
    lines.append(vd.get("syntax_example", ""))
    lines.append("```\n")

    lines.append("## Booleans + null\n")
    lines.append(f"- True: `{bk.get('true', '?')}`")
    lines.append(f"- False: `{bk.get('false', '?')}`")
    lines.append(f"- Null: `{spec.get('null_keyword', '?')}`")
    lines.append("")

    lines.append("## Operators\n")
    for cat in ("arithmetic", "comparison", "logical", "assignment"):
        items = ops.get(cat) or []
        if items:
            lines.append(f"- **{cat}**: " + ", ".join(f"`{op}`" for op in items))
    lines.append("")

    stdlib = (spec.get("stdlib") or {}).get("functions") or []
    if stdlib:
        lines.append("## Stdlib\n")
        for fn in stdlib:
            lines.append(f"- `{fn['name']}` — {fn.get('description', '')}")

    return "\n".join(lines) + "\n"


def _generate_language_reference(spec: dict, lang_dir: Path, client: LLMClient) -> Path:
    """Emit `LANGUAGE.md`: the formal language reference."""
    if reference_compiler_for(spec) is not None:
        target = lang_dir / "LANGUAGE.md"
        _write(target, _render_templated_language_reference(spec))
        return target
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
    raw = client.call_code(prompt, tag=f"gen-tests-{name}")
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

    # Roadmap §3.1: per-language CSS theme. Always written (the spec always
    # has spec.theme thanks to spec_builder); the GUI fetches it when this
    # language becomes active.
    _render_theme_css(spec, lang_dir)


def _render_theme_css(spec: dict, lang_dir: Path) -> None:
    """Write `<lang>/theme.css` from the spec's theme tokens."""
    from .style_tokens import render_theme_css
    tokens = (spec.get("theme") or {}).get("tokens") or {}
    if not tokens:
        return
    css = render_theme_css(tokens)
    (lang_dir / "theme.css").write_text(css, encoding="utf-8")


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
                out.append(f"{indent}{line_form} {body}")        # e.g. `# foo` or `; foo`
            elif block_open and block_close:
                out.append(f"{indent}{block_open} {body} {block_close}")
            else:
                # Last resort: drop the comment entirely.
                out.append(indent.rstrip())
            continue
        if stripped.startswith("#") and line_form not in ("#", None):
            # python_like sample on a c_like-or-other target. Convert.
            indent = raw[: len(raw) - len(stripped)]
            body = stripped[1:].lstrip()
            if line_form == "//":
                out.append(f"{indent}// {body}")
            elif line_form == ";":
                out.append(f"{indent}; {body}")
            elif block_open and block_close:
                out.append(f"{indent}{block_open} {body} {block_close}")
            else:
                out.append(indent.rstrip())
            continue
        # s_expression-style `;` line comment on a non-Lisp target.
        # `;` looks the same as a c_like statement terminator, so we only
        # rewrite when the line starts with `;` followed by space-or-end
        # (i.e. obviously a comment, not an empty c_like statement). And
        # only when the target's line_form ISN'T `;` (otherwise no-op).
        if (line_form not in (";", None) and stripped.startswith(";")
                and (len(stripped) == 1 or stripped[1] in " \t;")):
            indent = raw[: len(raw) - len(stripped)]
            # Trim leading `;` runs (covers `;;` Scheme-style top-level comments)
            body = stripped.lstrip(";").lstrip()
            if line_form == "//":
                out.append(f"{indent}// {body}")
            elif line_form == "#":
                out.append(f"{indent}# {body}")
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
    # Computed ONCE before the loop (was previously read inside each
    # iteration in older code paths).
    available = _runtime_available_helpers(lang_dir) & _codegen_imports(lang_dir)

    # Stage 1: prepare candidates (cheap, no subprocess). Filter by
    # available helpers and translate comments.
    candidates: list[tuple[str, str, Path]] = []   # (key, translated_src, target_path)
    for key in SAMPLES:
        needs = _SAMPLE_REQUIREMENTS.get(key, set())
        target = examples_dir / f"{key}{ext}"
        if not needs.issubset(available):
            if target.exists():
                try: target.unlink()
                except OSError: pass
            continue
        # Pass the full spec so s_expression mechanical transpilation has
        # the language's keyword overrides + null/boolean keywords.
        src = get_sample(key, syntax, spec=spec)
        if not src:
            continue
        translated = _translate_comments(src, syntax, comment_syntax)
        candidates.append((key, translated, target))

    # Stage 2: parallel compile-check. Each `_compile_check` spawns
    # Python twice; on Windows that's ~50-200ms per spawn. Running 4
    # in parallel turns ~1.6s sequential into ~400ms wall-clock for a
    # typical 8-sample pack.
    written: list[str] = []
    if candidates:
        import concurrent.futures as _cf
        max_workers = min(4, len(candidates))
        with _cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_compile_check, lang_dir, translated): (key, translated, target)
                for key, translated, target in candidates
            }
            for fut in _cf.as_completed(futures):
                key, translated, target = futures[fut]
                try:
                    ok = fut.result()
                except Exception:
                    ok = False
                if ok:
                    target.write_text(translated, encoding="utf-8")
                    written.append(key)
                else:
                    if target.exists():
                        try: target.unlink()
                        except OSError: pass
    # Stable order regardless of completion order
    written.sort(key=lambda k: list(SAMPLES).index(k))

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
                 on_progress: Optional[Callable[[str, str], None]] = None,
                 seed: Optional[int] = None,
                 telemetry: Optional["TelemetryRecorder"] = None,
                 write_summary: bool = True,
                 verify_after_generation: bool = True) -> Path:  # type: ignore[name-defined]
    """Generate every component for `spec` into `<output_root>/<lang_name>/`.

    If `only` is given, only those components are (re)generated.

    `on_progress(component, status)` is called as each component starts and
    finishes: used by the GUI to drive real-time progress updates. Status is
    one of: "running", "done", "fail".

    Phase 0.4/0.5 additions:
      seed: optional integer recorded in `generation_summary.json` for
            reproducibility. Future-proofed; the resolver/repair LLM
            calls don't currently honor a seed (Anthropic API doesn't
            expose one) but the field is plumbed and stamped.
      telemetry: an existing TelemetryRecorder (when called from a batch
            runner that wants to aggregate). If None, a fresh recorder
            is created and a `generation_summary.json` is written at the
            end. Pass `write_summary=False` to suppress the write (e.g.
            when the caller wants to merge several recorders before
            writing).
    """
    from .telemetry import TelemetryRecorder, attach as _attach_telem
    lang_dir = Path(output_root) / spec["lang_name"]
    lang_dir.mkdir(parents=True, exist_ok=True)

    # Set up telemetry. The recorder is attached to the LLM client so
    # every call_code/call_json/call_chat appends a record automatically.
    own_recorder = telemetry is None
    if telemetry is None:
        telemetry = TelemetryRecorder(lang_name=spec["lang_name"], seed=seed)
    # Attach the events file BEFORE any work happens so a crash in the
    # very first component still leaves a survival record on disk.
    # Phase 0 closeout #2: incremental telemetry writes.
    try:
        telemetry.attach_events_file(lang_dir / "generation_events.jsonl")
    except Exception:
        pass  # never fail generation because of telemetry setup

    # Clear any stale __pycache__ from a previous generation. Without this,
    # Python's bytecode cache can serve old parser.py / codegen.py bytecode
    # even after we overwrite the .py source - the new code "doesn't take
    # effect" until the user manually deletes the cache. Best-effort only;
    # OSError on Windows file locks is not fatal.
    pycache = lang_dir / "__pycache__"
    if pycache.exists():
        try:
            shutil.rmtree(pycache)
        except OSError:
            pass

    log_dir = lang_dir / ".forge_log"
    if client is None:
        client = LLMClient(log_dir=log_dir)
    elif client.log_dir is None:
        client.log_dir = log_dir
    # Attach telemetry; LLMClient picks it up via getattr in `_emit_telemetry`.
    _attach_telem(client, telemetry)

    # Persist the spec next to the generated source for verifier discovery.
    (lang_dir / "resolved_spec.json").write_text(
        json.dumps(spec, indent=2), encoding="utf-8"
    )

    components = list(components_for(spec))
    if only:
        components = [c for c in components if c in set(only)]

    # Roadmap families.md: when a hand-written reference compiler exists
    # for this syntax family (e.g. lisplang for s_expression), template
    # from it instead of asking the LLM to generate parser/codegen/runtime
    # /stdlib/lexer/tests from scratch. The remaining components (readme,
    # language_reference, typechecker if static) still go through the LLM
    # so the language gets per-spec personality and docs.
    ref_dir = reference_compiler_for(spec)
    if ref_dir is not None and not only:
        import time as _t
        _ref_t0 = _t.monotonic()
        fulfilled = _template_from_reference(spec, lang_dir, ref_dir)
        # All templated components share the elapsed time of the reference
        # template stage; they didn't make any LLM calls. Record them so
        # the components dict in the summary is complete (downstream
        # quality filters will check "did every expected component finish").
        ref_elapsed = _t.monotonic() - _ref_t0
        per_comp = (ref_elapsed / max(1, len(fulfilled))) if fulfilled else 0.0
        for comp in fulfilled:
            telemetry.record_component(comp, per_comp, success=True, llm_calls_made=0)
            if on_progress:
                try:
                    on_progress(comp, "running")
                    on_progress(comp, "done")
                except Exception:
                    pass
        components = [c for c in components if c not in fulfilled]

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

    # Tag-prefix attribution map lives at module level
    # (`COMPONENT_TAG_PREFIXES`) so a discipline test can pin it.
    def _count_calls_for(comp: str) -> int:
        prefixes = COMPONENT_TAG_PREFIXES.get(comp, ())
        if not prefixes:
            return 0
        # Note: telemetry.llm_calls is appended-to by other threads, but
        # iterating over a list is thread-safe under the GIL. We snapshot
        # via list() to absorb any concurrent appends cleanly.
        snap = list(telemetry.llm_calls)
        return sum(1 for c in snap if any(c.tag.startswith(p) for p in prefixes))

    def _run_component(comp: str) -> None:
        # Phase 0 closeout #4: per-component telemetry. Tag-based
        # attribution (see COMPONENT_TAG_PREFIXES) so parallel components
        # don't double-count each other's LLM calls.
        import time as _t
        t0 = _t.monotonic()
        success = True
        try:
            if comp == "tests":
                _generate_tests(spec, lang_dir, client)
            elif comp == "readme":
                _generate_readme(spec, lang_dir, client)
            elif comp == "language_reference":
                _generate_language_reference(spec, lang_dir, client)
            else:
                _generate_code_component(comp, spec, lang_dir, client)
        except Exception:
            success = False
            telemetry.record_component(
                comp, _t.monotonic() - t0, success=False,
                llm_calls_made=_count_calls_for(comp),
            )
            raise
        telemetry.record_component(
            comp, _t.monotonic() - t0, success=success,
            llm_calls_made=_count_calls_for(comp),
        )

    needed = set(components)
    deps = {c: DEPS.get(c, set()) & needed for c in needed}
    pending = set(needed)
    done: set[str] = set()
    in_flight: dict = {}    # Future -> component name

    import concurrent.futures as _cf
    # 4 workers covers the widest fan-out (lexer, typechecker, codegen, tests).
    # The Anthropic SDK is HTTP-bound; the Claude CLI shells out to subprocess.
    # Both release the GIL during the network/process wait, so threads parallelize fine.
    #
    # Phase 0 closeout #2: any exception below this line still leaves the
    # events file on disk as the survival record. The outer try/except
    # near the bottom of this function flushes a partial summary before
    # re-raising so debug tooling has both .json and .jsonl artifacts.
    try:
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
    except Exception as _gen_exc:
        # Phase 0 closeout #2: flush a partial summary so debug tooling can
        # find {.json + .jsonl} on disk after a mid-run crash. Re-raise.
        if write_summary and own_recorder:
            try:
                telemetry.record_error(
                    "generate_all",
                    f"crashed: {type(_gen_exc).__name__}: {_gen_exc}",
                )
                telemetry.write_summary(lang_dir)
            except Exception:
                pass
        raise

    # Phase 0.4: write the per-generation telemetry summary. This includes
    # canonical-test pass rate via a quick verify pass; failure to verify
    # is recorded as an error but doesn't break the generation (the user
    # might still want the partial output).
    #
    # The verify call runs every canonical test as a subprocess and adds
    # ~100ms per test. Tests that benchmark generation parallelism pass
    # `verify_after_generation=False` to skip this post-processing cost.
    # Phase 1.4: write the summary whenever `write_summary` is True,
    # regardless of who created the recorder. Previously this was
    # gated on `own_recorder`, which meant a caller passing in a
    # shared recorder (the subprocess worker, post-fix) didn't get
    # a summary file. Callers that DON'T want the summary should
    # pass `write_summary=False`.
    if write_summary:
        if verify_after_generation:
            try:
                from .verifier import verify
                report = verify(lang_dir)
                passed = sum(1 for t in report.tests if t.status == "pass")
                telemetry.set_canonical_results(passed, len(report.tests))
            except Exception as _ve:
                telemetry.record_error("verifier", str(_ve))
        try:
            telemetry.write_summary(lang_dir)
        except Exception:
            pass  # never fail generation because of summary write
    return lang_dir
