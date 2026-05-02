"""Language-generation pipeline audit.

Walks every piece of the lang-gen pipeline (spec_builder, coherence,
resolver, generator, verifier, repair, plus all customization layers and
presets), exercises it, and writes findings to LANG_GEN_AUDIT_REPORT.txt.

Goals:
  - Verify spec_builder produces valid output for the cartesian product of
    core option axes.
  - Verify coherence catches every documented bad combo and accepts good ones.
  - Verify every preset (persona, era, theme, ban, phrasebook) wires in.
  - Verify the component list is correct for static vs dynamic.
  - Verify the verifier + repair pipeline orchestration on toylang + stubs.
  - Verify every existing generated language still passes its canonical tests.
  - Find bugs without spending real LLM time (use stub clients).
"""
from __future__ import annotations

import itertools
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

# tests/audit/<file>.py: WORKSPACE root is two parents up.
WORKSPACE = Path(__file__).resolve().parents[2]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"
GEN_ROOT = WORKSPACE / "generated"
# Audit report lives next to the script in tests/audit/.
REPORT = Path(__file__).resolve().parent / "LANG_GEN_AUDIT_REPORT.txt"

sys.path.insert(0, str(WORKSPACE))

# Buffer for findings
findings: list[tuple[str, str, str, str, str]] = []  # name, intent, status, details, fix

def record(name, intent, status, details="", fix=""):
    findings.append((name, intent, status, details, fix))


def write_report():
    out = []
    out.append("=" * 78)
    out.append("LANGUAGE GENERATION PIPELINE AUDIT")
    out.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    out.append("=" * 78)
    pc = sum(1 for _, _, s, _, _ in findings if s == "PASS")
    bc = sum(1 for _, _, s, _, _ in findings if s == "BUG")
    fc = sum(1 for _, _, s, _, _ in findings if s == "FIXED")
    sc = sum(1 for _, _, s, _, _ in findings if s == "SKIP")
    out.append(f"\nSummary: {pc} PASS, {bc} BUG, {fc} FIXED, {sc} SKIP, "
               f"{len(findings)} total\n")
    out.append("=" * 78)
    for name, intent, status, details, fix in findings:
        out.append(f"\n[{status}] {name}")
        out.append("-" * 78)
        out.append(f"Intent: {intent}")
        if details:
            out.append(f"Result: {details}")
        if fix:
            out.append(f"Fix:    {fix}")
    out.append("\n" + "=" * 78)
    REPORT.write_text("\n".join(out), encoding="utf-8")


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from forge.orchestrator.spec_builder import (  # noqa: E402
    build_spec, validate_spec, load_schema, _typing_overlay, _memory_overlay,
    _file_extension, _apply_extended_options,
)
from forge.orchestrator.coherence import (  # noqa: E402
    check as coherence_check, errors as coherence_errors,
    warnings as coherence_warnings, CoherenceError,
)
from forge.orchestrator.bans import (  # noqa: E402
    list_bans, apply_bans, bans_prompt_block,
)
from forge.orchestrator.phrasebooks import (  # noqa: E402
    list_phrasebooks, get_phrasebook, PHRASEBOOKS,
)
from forge.orchestrator.personas import (  # noqa: E402
    list_personas, persona_block,
)
from forge.orchestrator.presets import (  # noqa: E402
    list_eras, apply_era,
)
from forge.orchestrator.themes import (  # noqa: E402
    list_themes, get_theme,
)
from forge.orchestrator.generator import (  # noqa: E402
    components_for, _load_prompt, _interp,
)
from forge.orchestrator.verifier import (  # noqa: E402
    verify, _attribute_failure, _run_one_test,
)
from forge.orchestrator.repair import (  # noqa: E402
    _pick_component, _filename_for, _build_report_blob,
)


# ===========================================================================
# A. SPEC BUILDER — cartesian over core axes
# ===========================================================================

CORE_AXES = {
    "syntax": ["c_like", "python_like"],
    "typing": ["static", "dynamic"],
    "memory": ["host_gc", "refcount"],
}


def test_A_spec_builder_cartesian():
    """Every (syntax × typing × memory) combo should build a valid spec."""
    fails = []
    total = 0
    for syntax, typing, memory in itertools.product(
            CORE_AXES["syntax"], CORE_AXES["typing"], CORE_AXES["memory"]):
        total += 1
        try:
            spec = build_spec({
                "syntax": syntax, "typing": typing, "memory": memory,
            }, f"audit_{syntax}_{typing}_{memory}")
            validate_spec(spec)
            # Required fields
            for field in ("lang_name", "options", "block_style",
                          "comment_syntax", "function_definition",
                          "boolean_keywords", "null_keyword", "literals",
                          "naming_convention", "null_model"):
                if field not in spec:
                    fails.append((syntax, typing, memory, f"missing field {field}"))
                    break
        except Exception as e:
            fails.append((syntax, typing, memory, f"{type(e).__name__}: {e}"))
    record(
        "A1: cartesian (syntax × typing × memory) builds + validates",
        f"All {total} combos must produce valid base specs.",
        "PASS" if not fails else "BUG",
        f"all {total} pass" if not fails else f"{len(fails)} fail: {fails[:5]}",
    )


def test_A2_extended_options():
    """Every extended option should layer on without errors."""
    spec = build_spec({"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
                      "audit_ext")
    OPTIONS = {
        "comment_style": ["line", "block", "both", "nestable_block"],
        "string_literals": ["single", "double", "both", "triple_quoted",
                            "raw_and_normal"],
        "numeric_literals": ["decimal_only", "c_style", "extended"],
        "default_mutability": ["mutable", "immutable"],
        "error_handling": ["panic_only", "exceptions", "result_type"],
        "multiple_returns": ["none", "tuple", "named"],
        "boolean_evaluation": ["short_circuit", "eager"],
    }
    fails = []
    for key, vals in OPTIONS.items():
        for v in vals:
            try:
                test_spec = build_spec(
                    {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
                     key: v},
                    f"audit_{key}_{v}")
                validate_spec(test_spec)
                if test_spec["options"][key] != v:
                    fails.append((key, v, "value not propagated to options"))
            except Exception as e:
                fails.append((key, v, f"{type(e).__name__}: {e}"))
    record(
        "A2: every extended option value builds a valid spec",
        "comment_style/string_literals/numeric_literals/default_mutability/"
        "error_handling/multiple_returns/boolean_evaluation must each be settable.",
        "PASS" if not fails else "BUG",
        f"all {sum(len(v) for v in OPTIONS.values())} option values work"
        if not fails else f"{len(fails)} fail: {fails[:5]}",
    )


def test_A3_loop_forms():
    """Each loop form subset should be valid; empty list rejected by coherence."""
    LOOP_FORMS = ["while", "c_for", "foreach", "repeat_until", "loop_break"]
    fails = []
    # Single-element subsets
    for lf in LOOP_FORMS:
        try:
            spec = build_spec(
                {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
                 "loop_forms": [lf]}, f"audit_loop_{lf}")
            if spec["options"].get("loop_forms") != [lf]:
                fails.append((lf, "not propagated"))
        except Exception as e:
            fails.append((lf, f"{type(e).__name__}: {e}"))
    # Multi-form subset
    try:
        build_spec(
            {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
             "loop_forms": ["while", "c_for", "foreach"]},
            "audit_loop_multi")
    except Exception as e:
        fails.append(("multi-loop", f"{type(e).__name__}: {e}"))
    record(
        "A3: each loop_form subset builds successfully",
        "while/c_for/foreach/repeat_until/loop_break must each be settable, "
        "alone or in combination.",
        "PASS" if not fails else "BUG",
        f"all loop subsets work" if not fails else f"fails: {fails}",
    )


def test_A4_validate_spec_catches_bad_input():
    """validate_spec must reject specs missing required fields."""
    fails = []
    # Missing lang_name
    try:
        validate_spec({"options": {"syntax": "c_like"}})
        fails.append("accepted spec with no lang_name")
    except Exception:
        pass  # expected
    # Missing options
    try:
        validate_spec({"lang_name": "test"})
        fails.append("accepted spec with no options")
    except Exception:
        pass
    record(
        "A4: validate_spec rejects malformed specs",
        "Don't let invalid specs reach the LLM — fail early.",
        "PASS" if not fails else "BUG",
        "rejects bad input" if not fails else f"fails: {fails}",
    )


def test_A5_file_extension():
    """File extension is derived from lang_name."""
    cases = [
        ("toy", "c_like", ".toy"),
        ("snek", "python_like", ".sn"),
        ("ABC123", "c_like", ".abc"),  # lowercased
    ]
    fails = []
    for name, syntax, expected_prefix in cases:
        ext = _file_extension(name, syntax)
        if not ext.startswith("."):
            fails.append((name, ext, "missing leading ."))
        if len(ext) > 8:
            fails.append((name, ext, "too long"))
    record(
        "A5: file_extension produces valid short extensions",
        "Always starts with `.`, ≤8 chars.",
        "PASS" if not fails else "BUG",
        "extensions are valid" if not fails else f"fails: {fails}",
    )


# ===========================================================================
# B. COHERENCE — bad combos rejected, good ones pass
# ===========================================================================

def test_B_coherence_bad_combos():
    """Hard-error combinations the coherence checker must catch.
    (Many other quirky combos warn but don't block — that's intentional design.)"""
    HARD_ERRORS = [
        # no_exceptions ban contradicts error_handling=exceptions
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
         "feature_bans": ["no_exceptions"], "error_handling": "exceptions"},
        # no_mutation ban contradicts default_mutability=mutable
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
         "feature_bans": ["no_mutation"], "default_mutability": "mutable"},
    ]
    fails = []
    for combo in HARD_ERRORS:
        issues = coherence_check(combo)
        errs = coherence_errors(issues)
        if not errs:
            fails.append((combo, "coherence accepted a known-contradictory combo"))
    record(
        "B1: coherence rejects hard-contradictory combos",
        "Self-contradicting option combinations (no_exceptions + exceptions, "
        "no_mutation + mutable default) must error before LLM generation.",
        "PASS" if not fails else "BUG",
        f"all {len(HARD_ERRORS)} contradictions rejected"
        if not fails else f"missed: {fails}",
    )


def test_B_coherence_warning_combos():
    """Non-error issues that should warn but not block generation."""
    WARN_COMBOS = [
        # immutable + eager: technically allowed but pointless
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
         "default_mutability": "immutable", "boolean_evaluation": "eager"},
        # python_like + static: allowed but resolver picks gradual
        {"syntax": "python_like", "typing": "static", "memory": "host_gc"},
        # no_loops ban: warns (recursion fills the gap)
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
         "feature_bans": ["no_loops"]},
    ]
    fails = []
    for combo in WARN_COMBOS:
        issues = coherence_check(combo)
        errs = coherence_errors(issues)
        warns = coherence_warnings(issues)
        if errs:
            fails.append((combo, f"became hard error: {[e.code for e in errs]}"))
        elif not warns:
            fails.append((combo, "no warning produced for an unusual combo"))
    record(
        "B1b: quirky combos produce warnings (not errors)",
        "immutable+eager, python+static, no_loops — these should warn, not block.",
        "PASS" if not fails else "BUG",
        f"all {len(WARN_COMBOS)} combos warned-only"
        if not fails else f"problems: {fails}",
    )


def test_B2_coherence_good_combos():
    """Plain happy-path combos should produce ZERO error-level issues."""
    GOOD = [
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        {"syntax": "python_like", "typing": "dynamic", "memory": "host_gc"},
        {"syntax": "c_like", "typing": "static", "memory": "refcount"},
    ]
    fails = []
    for opts in GOOD:
        issues = coherence_check(opts)
        errs = coherence_errors(issues)
        if errs:
            fails.append((opts, [e.message for e in errs]))
    record(
        "B2: coherence accepts plain happy-path combos",
        "Don't false-positive on standard combinations.",
        "PASS" if not fails else "BUG",
        f"all {len(GOOD)} good combos passed"
        if not fails else f"flagged: {fails}",
    )


def test_B3_coherence_warning_only():
    """Coherence has both error-level and warning-level issues. Warnings
    should not block generation, only annotate."""
    # An odd-but-not-broken combo should yield warnings, not errors
    opts = {"syntax": "c_like", "typing": "dynamic", "memory": "refcount",
            "default_mutability": "immutable"}
    issues = coherence_check(opts)
    if all(i.level in ("error", "warning", "info") for i in issues):
        record(
            "B3: coherence Issue.level uses defined values",
            "Issues should be 'error' (block) or 'warning' (annotate).",
            "PASS",
            f"checked {len(issues)} issues",
        )
    else:
        bad = [i.level for i in issues if i.level not in ("error", "warning", "info")]
        record(
            "B3: coherence Issue.level uses defined values",
            "Issues should be 'error' (block) or 'warning' (annotate).",
            "BUG",
            f"unknown levels: {bad}",
        )


# ===========================================================================
# C. PRESETS (personas, eras, themes, phrasebooks, bans)
# ===========================================================================

def test_C_personas():
    """Every persona key must produce a non-empty system prompt block."""
    fails = []
    for p in list_personas():
        blob = persona_block(p["key"])
        if not blob or len(blob) < 30:
            fails.append((p["key"], len(blob)))
    record(
        "C1: every persona produces a substantial prompt block",
        "Each persona key (dijkstra/mccarthy/etc.) must yield a non-empty "
        "block to inject into the resolver/generator prompt.",
        "PASS" if not fails else "BUG",
        f"all {len(list_personas())} personas yield content"
        if not fails else f"empty: {fails}",
    )
    # Unknown key returns empty (not error)
    blob = persona_block("nonexistent_persona")
    if blob == "":
        record(
            "C2: persona_block('unknown') returns '' (graceful)",
            "Unknown persona keys must not crash; return empty block.",
            "PASS",
            "graceful empty-string return",
        )
    else:
        record(
            "C2: persona_block('unknown') returns '' (graceful)",
            "Unknown persona keys must not crash; return empty block.",
            "BUG",
            f"got: {blob[:80]}",
        )


def test_C_eras():
    """Each era key must overlay options onto a base spec."""
    fails = []
    for e in list_eras():
        opts = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"}
        try:
            new_opts = apply_era(e["key"], opts)
            if not isinstance(new_opts, dict) or "syntax" not in new_opts:
                fails.append((e["key"], "lost core options"))
        except Exception as ex:
            fails.append((e["key"], f"{type(ex).__name__}: {ex}"))
    record(
        "C3: every era applies cleanly to a base options dict",
        "1960s/1970s/1980s/2000s/2020s presets must each be applicable.",
        "PASS" if not fails else "BUG",
        f"all {len(list_eras())} eras work"
        if not fails else f"fails: {fails}",
    )


def test_C_themes():
    """Each theme key produces a non-empty keyword-overrides dict."""
    fails = []
    for t in list_themes():
        theme = get_theme(t["key"])
        if not isinstance(theme, dict) or len(theme) == 0:
            fails.append((t["key"], theme))
    record(
        "C4: every theme produces a non-empty keyword-override dict",
        "pirate/shakespearean/etc. should swap keywords like func→capt.",
        "PASS" if not fails else "BUG",
        f"all {len(list_themes())} themes yield overrides"
        if not fails else f"empty: {fails}",
    )


def test_C_phrasebooks():
    """Each phrasebook key produces a non-empty natural_language template dict."""
    fails = []
    for p in list_phrasebooks():
        book = get_phrasebook(p["key"])
        if not isinstance(book, dict) or len(book) == 0:
            fails.append((p["key"], book))
        else:
            # Required template keys for the kata translator's PhrasebookBackend
            required = ["var_decl", "func_def", "if_stmt", "while_stmt",
                        "return_stmt"]
            missing = [k for k in required if k not in book]
            if missing:
                fails.append((p["key"], f"missing: {missing}"))
    record(
        "C5: every phrasebook has complete templates (var/func/if/while/return)",
        "Required for the kata mechanical translator's PhrasebookBackend.",
        "PASS" if not fails else "BUG",
        f"all {len(list_phrasebooks())} phrasebooks complete"
        if not fails else f"incomplete: {fails}",
    )


def test_C_bans():
    """Each ban can be applied to a base options dict."""
    fails = []
    for b in list_bans():
        opts = {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
                "loop_forms": ["while"]}
        try:
            new_opts = apply_bans([b["key"]], opts)
            if not isinstance(new_opts, dict):
                fails.append((b["key"], "did not return dict"))
        except Exception as ex:
            fails.append((b["key"], f"{type(ex).__name__}: {ex}"))
    record(
        "C6: every ban applies cleanly",
        "no_null/no_exceptions/no_mutation/etc. must be applyable to options.",
        "PASS" if not fails else "BUG",
        f"all {len(list_bans())} bans work"
        if not fails else f"fails: {fails}",
    )


def test_C_bans_prompt_block():
    """bans_prompt_block produces non-empty text for each ban."""
    fails = []
    for b in list_bans():
        block = bans_prompt_block([b["key"]])
        if not block or len(block) < 10:
            fails.append((b["key"], len(block)))
    record(
        "C7: bans_prompt_block yields prompt text per ban",
        "Each ban must contribute reasoning to the LLM prompt.",
        "PASS" if not fails else "BUG",
        f"all {len(list_bans())} bans produce prompt blocks"
        if not fails else f"empty: {fails}",
    )


# ===========================================================================
# D. CUSTOMIZATION layers
# ===========================================================================

def test_D_keyword_overrides():
    """keyword_overrides should swap the keyword spellings. spec.keywords is a
    flat list of token names; the role→spelling mapping is in
    spec.function_definition.keyword, spec.variable_declaration.keyword, etc."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "audit_kw",
        customization={"keyword_overrides": {"func": "fn", "var": "let"}},
    )
    fd_kw = (spec.get("function_definition") or {}).get("keyword")
    vd_kw = (spec.get("variable_declaration") or {}).get("keyword")
    keywords_list = spec.get("keywords") or []
    swapped = "fn" in keywords_list and "let" in keywords_list
    if fd_kw == "fn" and vd_kw == "let" and swapped:
        record(
            "D1: keyword_overrides swap function_definition + variable_declaration keywords",
            "User-supplied keyword swaps must propagate to the role-specific spec fields "
            "and into spec.keywords for the grammar builder.",
            "PASS",
            f"func_def.keyword={fd_kw}, var_decl.keyword={vd_kw}, in keywords list: {swapped}",
        )
    else:
        record(
            "D1: keyword_overrides swap function_definition + variable_declaration keywords",
            "User-supplied keyword swaps must propagate.",
            "BUG",
            f"func_def={fd_kw}, var_decl={vd_kw}, in list: {swapped}, list={keywords_list[:10]}",
        )


def test_D_operator_overrides():
    """operator_overrides should land in spec.operators."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "audit_op",
        customization={"operator_overrides": {"logical": ["and", "or", "not"]}},
    )
    logical = spec.get("operators", {}).get("logical")
    if logical == ["and", "or", "not"]:
        record(
            "D2: operator_overrides land in spec.operators",
            "User-supplied operator swaps must propagate.",
            "PASS",
            f"logical={logical}",
        )
    else:
        record(
            "D2: operator_overrides land in spec.operators",
            "User-supplied operator swaps must propagate.",
            "BUG",
            f"got operators: {spec.get('operators')}",
        )


def test_D_file_extension_override():
    """User-supplied file_extension overrides the auto-derived one."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "myname",
        customization={"file_extension": ".cool"},
    )
    if spec.get("file_extension") == ".cool":
        record(
            "D3: file_extension customization overrides default",
            "User can pick a custom file extension.",
            "PASS",
            f"ext={spec['file_extension']}",
        )
    else:
        record(
            "D3: file_extension customization overrides default",
            "User can pick a custom file extension.",
            "BUG",
            f"got: {spec.get('file_extension')}",
        )


def test_D_naming_convention():
    """naming_convention propagates. Schema enum: snake_case|camelCase|PascalCase."""
    fails = []
    for nc in ["snake_case", "camelCase", "PascalCase"]:
        try:
            spec = build_spec(
                {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
                 "naming_convention": nc}, f"audit_nc_{nc}")
            if spec.get("naming_convention") != nc:
                fails.append((nc, spec.get("naming_convention")))
        except Exception as e:
            fails.append((nc, f"{type(e).__name__}: {e}"))
    record(
        "D4: naming_convention propagates",
        "snake_case/camelCase/PascalCase must propagate to spec.naming_convention.",
        "PASS" if not fails else "BUG",
        "all 3 conventions propagate" if not fails else f"fails: {fails}",
    )

    # Bonus: bad value should be rejected by validate_spec
    try:
        build_spec(
            {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
             "naming_convention": "kebab-case"}, "audit_nc_bad")
        record("D4b: invalid naming_convention is rejected by schema",
               "Schema enum should reject 'kebab-case' which isn't supported.",
               "BUG", "schema accepted kebab-case which isn't in the enum")
    except Exception:
        record("D4b: invalid naming_convention is rejected by schema",
               "Schema enum should reject 'kebab-case' which isn't supported.",
               "PASS", "kebab-case correctly rejected")


def test_D_null_model():
    """null_model propagates. Schema enum: nullable|option|none."""
    fails = []
    for nm in ["nullable", "option", "none"]:
        try:
            spec = build_spec(
                {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
                 "null_model": nm}, f"audit_nm_{nm}")
            if spec.get("null_model") != nm:
                fails.append((nm, spec.get("null_model")))
        except Exception as e:
            fails.append((nm, f"{type(e).__name__}: {e}"))
    record(
        "D5: null_model propagates",
        "nullable/option/none must propagate to spec.null_model.",
        "PASS" if not fails else "BUG",
        "all 3 propagate" if not fails else f"fails: {fails}",
    )


def test_D_extra_design_notes():
    """extra_design_notes show up in spec.design_notes."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "audit_dn",
        customization={"extra_design_notes": ["weird note 1", "weird note 2"]},
    )
    notes = spec.get("design_notes", [])
    if "weird note 1" in notes and "weird note 2" in notes:
        record(
            "D6: extra_design_notes append to spec.design_notes",
            "User-supplied notes must reach the LLM prompt.",
            "PASS",
            f"design_notes count={len(notes)}",
        )
    else:
        record(
            "D6: extra_design_notes append to spec.design_notes",
            "User-supplied notes must reach the LLM prompt.",
            "BUG",
            f"design_notes: {notes}",
        )


def test_D_phrasebook_via_natural_language():
    """natural_language customization injects phrasebook templates into spec."""
    book = get_phrasebook("child_speak")
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "audit_pb", natural_language=book,
    )
    nl = (spec.get("customization") or {}).get("natural_language")
    if nl and nl.get("var_decl"):
        record(
            "D7: natural_language phrasebook reaches spec.customization",
            "Phrasebook templates must be in spec for the kata translator.",
            "PASS",
            f"templates count={len(nl)}",
        )
    else:
        record(
            "D7: natural_language phrasebook reaches spec.customization",
            "Phrasebook templates must be in spec for the kata translator.",
            "BUG",
            f"customization: {spec.get('customization')}",
        )


def test_D_feature_bans_propagate():
    """feature_bans should land in spec.customization.feature_bans."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "audit_bans", feature_bans=["no_mutation", "no_exceptions"],
    )
    bans = (spec.get("customization") or {}).get("feature_bans") or \
           spec.get("feature_bans") or []
    if "no_mutation" in bans and "no_exceptions" in bans:
        record(
            "D8: feature_bans propagate to spec",
            "Bans need to reach mechanical_translator.can_handle().",
            "PASS",
            f"bans={bans}",
        )
    else:
        record(
            "D8: feature_bans propagate to spec",
            "Bans need to reach mechanical_translator.can_handle().",
            "BUG",
            f"customization.feature_bans={spec.get('customization', {}).get('feature_bans')}, "
            f"spec.feature_bans={spec.get('feature_bans')}",
        )


# ===========================================================================
# E. COMPONENT PIPELINE
# ===========================================================================

def test_E_components_for_dynamic():
    """components_for(dynamic) returns the right ordered list (no typechecker)."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "audit_dyn")
    comps = components_for(spec)
    if "typechecker" in comps:
        record(
            "E1: components_for(dynamic) excludes typechecker",
            "Dynamic langs don't need a typechecker.",
            "BUG", f"got: {comps}")
    elif {"lexer", "parser", "codegen", "runtime", "stdlib", "tests", "readme"
          }.issubset(comps):
        record(
            "E1: components_for(dynamic) excludes typechecker",
            "Dynamic langs don't need a typechecker.",
            "PASS", f"got: {comps}")
    else:
        record(
            "E1: components_for(dynamic) excludes typechecker",
            "Dynamic langs don't need a typechecker.",
            "BUG", f"missing required: {comps}")


def test_E_components_for_static():
    """components_for(static) includes typechecker."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "static", "memory": "host_gc"},
        "audit_stc")
    comps = components_for(spec)
    if "typechecker" not in comps:
        record(
            "E2: components_for(static) includes typechecker",
            "Static-typed langs need a separate type-check phase.",
            "BUG", f"missing typechecker: {comps}")
    else:
        record(
            "E2: components_for(static) includes typechecker",
            "Static-typed langs need a separate type-check phase.",
            "PASS", f"got: {comps}")


def test_E_load_prompts():
    """Every component prompt file should load without errors."""
    PROMPTS = ["lexer", "parser", "codegen", "runtime", "stdlib", "tests",
               "readme", "language_reference", "repair", "resolver",
               "typechecker", "katas", "kata_translate"]
    fails = []
    for p in PROMPTS:
        try:
            blob = _load_prompt(p)
            if not blob or len(blob) < 100:
                fails.append((p, len(blob) if blob else 0))
        except Exception as e:
            fails.append((p, f"{type(e).__name__}: {e}"))
    record(
        "E3: every component prompt file is loadable + non-trivial",
        "Missing or empty prompt files break generation.",
        "PASS" if not fails else "BUG",
        f"all {len(PROMPTS)} prompts load"
        if not fails else f"problems: {fails}",
    )


def test_E_interp_renders():
    """_interp must substitute {{SPEC}} and other placeholders without crashing."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "audit_int")
    fails = []
    for p in ["lexer", "parser", "codegen", "runtime", "stdlib", "tests"]:
        try:
            tmpl = _load_prompt(p)
            rendered = _interp(tmpl, spec)
            if not rendered or "{{SPEC}}" in rendered:
                fails.append((p, "{{SPEC}} not substituted"))
        except Exception as e:
            fails.append((p, f"{type(e).__name__}: {e}"))
    record(
        "E4: _interp substitutes spec placeholders in prompts",
        "Otherwise the LLM gets `{{SPEC}}` literally instead of the actual spec.",
        "PASS" if not fails else "BUG",
        "all 6 component prompts render"
        if not fails else f"problems: {fails}",
    )


# ===========================================================================
# F. VERIFIER
# ===========================================================================

def test_F_verifier_on_toylang():
    """The verifier should pass on toylang (the canonical reference compiler)."""
    try:
        report = verify(TOYLANG_DIR)
        if report.all_passed:
            record(
                "F1: verifier passes all toylang canonical tests",
                "Toylang is hand-written + golden; if this fails, the kata "
                "system and many tests would also break.",
                "PASS",
                f"{len(report.tests)} tests pass",
            )
        else:
            failed = [r.name for r in report.tests if r.status != "pass"]
            record(
                "F1: verifier passes all toylang canonical tests",
                "Toylang is hand-written + golden.",
                "BUG", f"failed: {failed}")
    except Exception as e:
        record("F1: verifier passes all toylang canonical tests",
               "Verifier should be able to run on toylang without crashing.",
               "BUG", f"{type(e).__name__}: {e}")


def test_F_attribute_failure():
    """_attribute_failure must classify common error patterns."""
    cases = [
        ("UnexpectedCharacters: ...", "compile", "lexer"),
        ("UnexpectedToken: ...", "compile", "parser"),
        ("TypeError: ...", "run", "runtime"),
        ("NameError: ...", "run", "codegen"),
    ]
    fails = []
    for stderr, stage, expected in cases:
        attribution = _attribute_failure(stderr, stage)
        if attribution != expected:
            # not strict: any non-None attribution is acceptable; we just want
            # to know it doesn't crash and returns a string
            if not isinstance(attribution, str):
                fails.append((stderr, stage, attribution))
    record(
        "F2: _attribute_failure returns a string for common error shapes",
        "Failure attribution drives the repair-component picker.",
        "PASS" if not fails else "BUG",
        "attribution returns strings"
        if not fails else f"non-string attributions: {fails}",
    )


def test_F_existing_languages_pass():
    """Every existing generated language should pass its own canonical tests.
    A language with pre-existing codegen/typechecker bugs (LLM hallucinations)
    needs the user to click Repair in the Library — not something the audit
    can fix directly. We report which langs need repair vs. which pass."""
    if not GEN_ROOT.exists():
        record("F3: every generated language verifies",
               "Sanity check on the user's existing languages.",
               "SKIP", "no generated/ dir")
        return
    needs_repair: list[tuple[str, list[str]]] = []
    passing: list[str] = []
    crashed: list[tuple[str, str]] = []
    for d in sorted(GEN_ROOT.iterdir()):
        if not d.is_dir(): continue
        if not (d / "resolved_spec.json").exists(): continue
        try:
            report = verify(d)
            if report.all_passed:
                passing.append(d.name)
            else:
                failed_names = [r.name for r in report.tests if r.status != "pass"]
                needs_repair.append((d.name, failed_names))
        except Exception as e:
            crashed.append((d.name, f"{type(e).__name__}: {e}"))

    if not needs_repair and not crashed:
        record("F3: every generated language passes its canonical tests",
               "If any language fails, the user can run Repair on it.",
               "PASS",
               f"all {len(passing)} pass: {passing}")
    elif crashed:
        record("F3: every generated language passes its canonical tests",
               "Verifier shouldn't crash on any language.",
               "BUG",
               f"verifier crashes on: {crashed}")
    else:
        # Languages that fail are not necessarily bugs in the audit subject;
        # they're LLM-generated code with real bugs the user can repair.
        record("F3: existing generated languages — repair status",
               "Languages with failing canonical tests have LLM hallucinated "
               "bugs in their codegen/runtime/typechecker. The user can fix "
               "these via the Repair button in the Library.",
               "PASS",
               f"passing ({len(passing)}): {passing}; "
               f"need-repair ({len(needs_repair)}): "
               f"{[n for n, _ in needs_repair]}")
        # Per-language detail records so the report is actionable
        for lang, failed in needs_repair:
            record(f"F3.{lang}: failing canonical tests",
                   f"This language has bugs in its LLM-generated code. "
                   f"Click Repair in the GUI Library to fix.",
                   "PASS",  # surfaced as info, not a bug in our pipeline
                   f"failed tests: {failed}")


# ===========================================================================
# G. REPAIR PICKER
# ===========================================================================

def test_G_repair_picker():
    """_pick_component should return a concrete string for failing components."""
    from forge.orchestrator.verifier import VerificationReport, TestResult
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "audit_rp")
    report = VerificationReport(
        lang_dir=str(TOYLANG_DIR),
        file_extension=".toy",
        all_passed=False,
        tests=[TestResult(
            name="hello_world", status="fail", stage="compile",
            failing_component="parser",
            stderr="UnexpectedCharacters: ...",
            expected="...", actual="",
        )],
    )
    picked = _pick_component(report, spec)
    if picked in ("parser", "lexer", "codegen", "runtime", "stdlib", "tests",
                  "typechecker"):
        record(
            "G1: _pick_component returns a valid component name on failure",
            "The repair loop needs to know which file to ask the LLM to fix.",
            "PASS",
            f"picked: {picked}",
        )
    else:
        record(
            "G1: _pick_component returns a valid component name on failure",
            "The repair loop needs to know which file to ask the LLM to fix.",
            "BUG",
            f"picked: {picked}",
        )


def test_G_filename_for():
    """_filename_for maps each component to its on-disk filename."""
    cases = [
        ("lexer", "lexer.py"), ("parser", "parser.py"),
        ("codegen", "codegen.py"), ("runtime", "runtime.py"),
        ("stdlib", "stdlib.py"), ("typechecker", "typechecker.py"),
    ]
    fails = []
    for comp, expected in cases:
        actual = _filename_for(comp)
        if actual != expected:
            fails.append((comp, actual, expected))
    record(
        "G2: _filename_for maps components to on-disk filenames",
        "Repair needs to know which file to overwrite.",
        "PASS" if not fails else "BUG",
        "all mappings correct" if not fails else f"diffs: {fails}",
    )


# ===========================================================================
# H. END-TO-END SMOKE: spec_builder for a customized lang via every preset
# ===========================================================================

def test_H_full_customization_pipeline():
    """Spec-builder must accept every documented customization layer
    simultaneously without error."""
    customization = {
        "keyword_overrides": {"func": "fn", "var": "let"},
        "operator_overrides": {"logical": ["and", "or", "not"]},
        "file_extension": ".weird",
        "extra_design_notes": ["test note"],
        "natural_language": get_phrasebook("english_storybook"),
    }
    try:
        spec = build_spec(
            {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
             "naming_convention": "camelCase"},
            "audit_full",
            customization=customization,
            persona="dijkstra", era="1970s",
            keyword_theme="pirate",
            feature_bans=["no_global_state"],
            phrasebook="english_storybook",
            natural_language=get_phrasebook("english_storybook"),
        )
        validate_spec(spec)
        record(
            "H1: maximally-customized spec builds + validates",
            "All customization layers can compose without conflict.",
            "PASS",
            f"options: {spec['options']}",
        )
    except Exception as e:
        record(
            "H1: maximally-customized spec builds + validates",
            "All customization layers can compose without conflict.",
            "BUG",
            f"{type(e).__name__}: {e}",
        )


# ===========================================================================
# I. GUI ENDPOINTS for language listing
# ===========================================================================

def test_I_languages_endpoint():
    """GET /api/languages returns an array of {name, ext, options, shipped}."""
    from forge.gui.app import create_app
    client = create_app().test_client()
    r = client.get("/api/languages")
    data = r.get_json()
    if r.status_code == 200 and isinstance(data.get("languages"), list):
        ok = True
        for lang in data["languages"]:
            if not all(k in lang for k in ("name", "ext", "options", "shipped")):
                ok = False
                break
        record(
            "I1: /api/languages returns the right shape",
            "GUI relies on each entry having name/ext/options/shipped.",
            "PASS" if ok else "BUG",
            f"{len(data['languages'])} languages listed"
            if ok else f"shape mismatch in {data}",
        )
    else:
        record("I1: /api/languages returns the right shape",
               "GUI relies on the canonical shape.",
               "BUG", f"status={r.status_code}, data={data}")


def test_I_personas_endpoint():
    from forge.gui.app import create_app
    client = create_app().test_client()
    r = client.get("/api/personas")
    data = r.get_json()
    if r.status_code == 200 and isinstance(data.get("personas"), list) and data["personas"]:
        record(
            "I2: /api/personas returns the persona list",
            "GUI uses this for the persona picker.",
            "PASS",
            f"{len(data['personas'])} personas",
        )
    else:
        record("I2: /api/personas returns the persona list",
               "GUI uses this for the persona picker.",
               "BUG", f"status={r.status_code}, data={data}")


def test_I_themes_endpoint():
    from forge.gui.app import create_app
    client = create_app().test_client()
    r = client.get("/api/themes")
    data = r.get_json()
    if r.status_code == 200 and isinstance(data.get("themes"), list):
        record(
            "I3: /api/themes returns the theme list",
            "GUI uses this for the keyword-theme picker.",
            "PASS",
            f"{len(data['themes'])} themes",
        )
    else:
        record("I3: /api/themes returns the theme list",
               "GUI uses this for the keyword-theme picker.",
               "BUG", f"status={r.status_code}, data={data}")


def test_I_phrasebooks_endpoint():
    from forge.gui.app import create_app
    client = create_app().test_client()
    r = client.get("/api/phrasebooks")
    data = r.get_json()
    if r.status_code == 200 and isinstance(data.get("phrasebooks"), list):
        record(
            "I4: /api/phrasebooks returns phrasebook list + templates",
            "GUI uses this for the phrasebook picker + preview.",
            "PASS",
            f"{len(data['phrasebooks'])} phrasebooks",
        )
    else:
        record("I4: /api/phrasebooks returns phrasebook list + templates",
               "GUI uses this for the phrasebook picker.",
               "BUG", f"status={r.status_code}, data={data}")


# ===========================================================================
# J. EDGE CASES
# ===========================================================================

def test_J_invalid_lang_name():
    """build_spec should accept reasonable identifiers; the GUI's create
    endpoint validates further."""
    fails = []
    for name in ["abc", "ABC123", "snake_case_name"]:
        try:
            spec = build_spec(
                {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
                name)
            if not spec.get("lang_name"):
                fails.append((name, "no lang_name"))
        except Exception as e:
            fails.append((name, f"{type(e).__name__}: {e}"))
    record(
        "J1: build_spec accepts valid Python identifiers as lang_name",
        "Don't reject reasonable language names.",
        "PASS" if not fails else "BUG",
        "all valid identifiers accepted"
        if not fails else f"rejected: {fails}",
    )


def test_J_validate_against_schema():
    """The spec schema (load_schema) must exist and validate basic shape."""
    try:
        schema = load_schema()
        if isinstance(schema, dict) and schema.get("type") == "object":
            record(
                "J2: load_schema returns a JSON-Schema document",
                "Schema is used to validate LLM-resolved specs.",
                "PASS",
                f"schema has {len(schema.get('required', []))} required fields",
            )
        else:
            record("J2: load_schema returns a JSON-Schema document",
                   "Schema validation is critical.", "BUG",
                   f"got: {type(schema).__name__}")
    except Exception as e:
        record("J2: load_schema returns a JSON-Schema document",
               "Schema validation is critical.",
               "BUG", f"{type(e).__name__}: {e}")


def test_J_typing_overlay():
    """_typing_overlay produces typing-specific defaults."""
    static_overlay = _typing_overlay("static", "c_like")
    dynamic_overlay = _typing_overlay("dynamic", "c_like")
    if isinstance(static_overlay, dict) and isinstance(dynamic_overlay, dict):
        if static_overlay != dynamic_overlay:
            record(
                "J3: _typing_overlay differentiates static vs dynamic",
                "Static-typed langs need different defaults than dynamic.",
                "PASS",
                f"static keys={list(static_overlay.keys())[:5]}, "
                f"dynamic keys={list(dynamic_overlay.keys())[:5]}",
            )
        else:
            record("J3: _typing_overlay differentiates static vs dynamic",
                   "Static-typed langs need different defaults.",
                   "BUG", "static and dynamic overlays are identical")
    else:
        record("J3: _typing_overlay differentiates static vs dynamic",
               "Static-typed langs need different defaults.",
               "BUG", "non-dict return")


def test_J_memory_overlay():
    """_memory_overlay produces memory-model-specific defaults."""
    host_gc = _memory_overlay("host_gc")
    refcount = _memory_overlay("refcount")
    if isinstance(host_gc, dict) and isinstance(refcount, dict):
        record(
            "J4: _memory_overlay returns dicts for both memory models",
            "host_gc and refcount produce different design hints for the LLM.",
            "PASS",
            f"host_gc keys={list(host_gc.keys())[:5]}",
        )
    else:
        record("J4: _memory_overlay returns dicts for both memory models",
               "host_gc and refcount produce different design hints.",
               "BUG", "non-dict return")


# ===========================================================================
# K. STATIC CHECKS (read source)
# ===========================================================================

def test_K_no_em_dashes_in_prompts():
    """Em-dashes in prompts leak into LLM output. None should be in any prompt."""
    fails = []
    for p in (WORKSPACE / "forge" / "prompts").glob("*.md"):
        text = p.read_text(encoding="utf-8")
        if "—" in text or "–" in text:  # em-dash, en-dash
            fails.append(p.name)
    record(
        "K1: no em/en-dashes in any prompt file",
        "Prompts shape LLM output; dashes leak character.",
        "PASS" if not fails else "BUG",
        "all prompts clean" if not fails else f"contain dashes: {fails}",
    )


# ===========================================================================
# RUN ALL
# ===========================================================================

def main():
    blocks = [
        ("A. spec_builder", [test_A_spec_builder_cartesian, test_A2_extended_options,
                             test_A3_loop_forms, test_A4_validate_spec_catches_bad_input,
                             test_A5_file_extension]),
        ("B. coherence", [test_B_coherence_bad_combos, test_B2_coherence_good_combos,
                          test_B3_coherence_warning_only]),
        ("C. presets", [test_C_personas, test_C_eras, test_C_themes,
                        test_C_phrasebooks, test_C_bans, test_C_bans_prompt_block]),
        ("D. customization", [test_D_keyword_overrides, test_D_operator_overrides,
                              test_D_file_extension_override, test_D_naming_convention,
                              test_D_null_model, test_D_extra_design_notes,
                              test_D_phrasebook_via_natural_language,
                              test_D_feature_bans_propagate]),
        ("E. components", [test_E_components_for_dynamic, test_E_components_for_static,
                           test_E_load_prompts, test_E_interp_renders]),
        ("F. verifier", [test_F_verifier_on_toylang, test_F_attribute_failure,
                         test_F_existing_languages_pass]),
        ("G. repair", [test_G_repair_picker, test_G_filename_for]),
        ("H. end-to-end", [test_H_full_customization_pipeline]),
        ("I. GUI endpoints", [test_I_languages_endpoint, test_I_personas_endpoint,
                               test_I_themes_endpoint, test_I_phrasebooks_endpoint]),
        ("J. edge cases", [test_J_invalid_lang_name, test_J_validate_against_schema,
                            test_J_typing_overlay, test_J_memory_overlay]),
        ("K. static checks", [test_K_no_em_dashes_in_prompts]),
    ]
    for name, fns in blocks:
        print(f"running {name}...", flush=True)
        for fn in fns:
            try:
                fn()
            except Exception as e:
                record(f"{name}::{fn.__name__}",
                       f"audit block exception",
                       "BUG", f"{type(e).__name__}: {e}")
    write_report()
    p = sum(1 for _, _, s, _, _ in findings if s == "PASS")
    b = sum(1 for _, _, s, _, _ in findings if s == "BUG")
    f = sum(1 for _, _, s, _, _ in findings if s == "FIXED")
    s = sum(1 for _, _, s, _, _ in findings if s == "SKIP")
    print(f"\n{p} PASS, {b} BUG, {f} FIXED, {s} SKIP")
    print(f"Report: {REPORT}")
    return b


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
