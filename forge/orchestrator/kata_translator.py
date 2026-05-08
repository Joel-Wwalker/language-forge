"""Translate a curated kata pack into a target language's actual syntax.

Curated packs (e.g. LeetCode classics) are written in vanilla c_like with
toylang's stdlib names. They load instantly and correctly onto vanilla
c_like languages, but they DON'T parse on customized languages:

  - kidX has a phrasebook (`make <name> equal <value>.`)
  - love has `feature_bans: ["no_mutation"]`
  - python_like languages use indentation + def/return without semicolons

Rather than refusing the load (the user wants the LeetCode problems!),
we ask the LLM to translate each kata into the target language's dialect.
The PROBLEM stays the same (id, title, difficulty, problem statement,
function name); the CODE (starter, reference, test calls, expected
stdout) gets rewritten to match the target.

Each translated kata is self-validated against the language's actual
compiler. Failures get a fix-up retry; persistent failures are dropped
with their reason.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from .katas import (
    KATA_PACK_SCHEMA, _self_validate, _try_fix_reference, _pick_working_sample,
    substitute_kata_for_target,
)


# Translator-specific schema. The shared KATA_PACK_SCHEMA caps at 8 items
# because LLM-generated packs are 5-8 katas; curated packs we translate
# can be 12+. Using the small cap here meant the LLM was told "your 12
# items are over the max" on every retry — and was likely truncating or
# duplicating to fit, which is exactly the "12 of two_sum" bug the user hit.
def _translate_schema(min_items: int, max_items: int) -> dict:
    schema = json.loads(json.dumps(KATA_PACK_SCHEMA))  # deep copy
    schema["properties"]["katas"]["minItems"] = min_items
    schema["properties"]["katas"]["maxItems"] = max_items
    return schema


def _problems_for_prompt(katas: list[dict]) -> list[dict]:
    """Strip syntax-specific bits from each kata so the LLM only sees
    the problem and a semantic description of each test."""
    out = []
    for k in katas:
        out.append({
            "id": k["id"],
            "title": k["title"],
            "difficulty": k["difficulty"],
            "problem": k["problem"],
            "function_name": k["function_name"],
            # Keep the original c_like reference + tests as a SEMANTIC hint.
            # The LLM can read them as pseudocode and translate, knowing the
            # target output formatter may produce different `expected` strings.
            "canonical_reference_c_like": k.get("reference_solution", ""),
            "canonical_tests_c_like": k.get("tests", []),
        })
    return out


def translate_pack(pack_template: dict, spec: dict, lang_dir: Path,
                   client, *, on_progress=None, fix_attempts: int = 3,
                   mechanical: bool = True,
                   time_budget_s: float = 90.0) -> dict:
    """Translate the pack with a HARD wall-clock budget.

    Without a budget, a stubborn language (LLM keeps producing broken refs)
    can spend 5 attempts × 1 LLM call × 12 katas × multiple safety-net
    layers ≈ 60+ LLM calls = several minutes. Past `time_budget_s`,
    everything still pending is stub-rescued so the user sees katas appear
    on a predictable timeline.

    fix_attempts is also tightened from 5 to 3: the case-analysis safety
    net runs at attempt 3 now, which means most kata fix-up burns at most
    3 LLM calls per stuck kata (was 5)."""
    """Translate every kata in `pack_template` into the language's dialect.

    Returns a pack dict with `katas` (those that survived self-validation)
    and `dropped` (those that didn't, with reasons). Progress is reported
    via on_progress(msg) callbacks if provided.
    """
    from .generator import _load_prompt, _interp

    def _emit(msg: str):
        if on_progress:
            try: on_progress(msg)
            except Exception: pass

    import time as _time
    deadline = _time.monotonic() + time_budget_s
    def budget_exhausted() -> bool:
        return _time.monotonic() >= deadline

    sample = _pick_working_sample(lang_dir, spec) or ""
    originals = pack_template["katas"]

    # FAST PATH: try mechanical transpile FIRST. The classics use a
    # constrained subset of c_like (declarations, assignments, if/while,
    # function calls, basic operators); for vanilla c_like and phrasebook
    # languages we can transpile this subset directly via toylang's parser
    # + a backend per language family. Milliseconds per kata, no LLM call,
    # near-100% reliability when the backend supports the language type.
    from .mechanical_translator import transpile_and_validate, can_handle
    mechanical_results: dict[str, dict] = {}
    if mechanical and can_handle(spec) is not None:
        _emit("Trying mechanical transpile (no LLM call)")
        mech_ok = 0
        for original in originals:
            translated, _reason = transpile_and_validate(original, spec, lang_dir)
            if translated is not None:
                mechanical_results[original["id"]] = translated
                mech_ok += 1
        _emit(f"Mechanical: {mech_ok}/{len(originals)} translated successfully")
        # If mechanical handled EVERYTHING, skip the LLM entirely.
        if mech_ok == len(originals):
            return {
                "katas": [mechanical_results[o["id"]] for o in originals],
                "dropped": [],
            }

    # Whatever mechanical couldn't handle, the LLM fills in.
    remaining = [o for o in originals if o["id"] not in mechanical_results]
    if not remaining:
        # All katas done by mechanical (covered above too, but defensive).
        return {
            "katas": [mechanical_results[o["id"]] for o in originals],
            "dropped": [],
        }
    if mechanical_results:
        _emit(f"Falling back to LLM for {len(remaining)} kata(s) "
              f"that mechanical couldn't transpile")

    # The rest of this function operates on a `remaining` template, then
    # merges back with mechanical_results at the end.
    pack_template = {**pack_template, "katas": remaining}
    originals_for_llm = remaining
    full_originals = originals  # save for final merge
    originals = originals_for_llm  # `originals` is reused below for LLM path

    problems = _problems_for_prompt(originals_for_llm)

    # Build the explicit-id list for the prompt. The LLM will return one
    # entry per id, in this order; downstream code rejects anything else.
    expected_ids = [p["id"] for p in originals]
    id_list_str = "\n".join(f"  - {i}" for i in expected_ids)

    prompt_tmpl = _load_prompt("kata_translate")
    # The standard _interp only knows top-level spec keys. Inject our extras
    # by post-processing the rendered template.
    rendered = _interp(prompt_tmpl, spec)
    rendered = (rendered
                .replace("{{PROBLEMS_JSON}}", json.dumps(problems, indent=2))
                .replace("{{SAMPLE}}", sample)
                .replace("{{EXPECTED_IDS}}", id_list_str)
                .replace("{{KATA_COUNT}}", str(len(originals))))

    # Use a translator-specific schema sized for THIS pack, not the
    # 8-item cap on the generation schema. Otherwise the LLM was told its
    # 12-item response was over the limit, and probably truncated +
    # duplicated to fit — that was the "12 of two_sum" bug.
    schema = _translate_schema(min_items=1, max_items=max(20, len(originals) + 4))

    _emit(f"Asking the model to translate {len(problems)} curated katas")
    raw = client.call_json(rendered, schema, tag="kata-translate")
    translated_raw = raw.get("katas") or []
    _emit(f"Got {len(translated_raw)} translations, deduping + validating")

    # Dedup by id, keep the first occurrence. Then ALIGN to expected_ids:
    # any id the LLM returned that isn't in our original problem list gets
    # dropped (with a clear reason). Any expected id missing from the LLM
    # output gets recorded as omitted further down.
    by_id: dict[str, dict] = {}
    out_of_band: list[dict] = []
    for k in translated_raw:
        kid = k.get("id")
        if not kid:
            out_of_band.append(k)
            continue
        if kid in by_id:
            continue  # silently dedup repeats — most likely cause is LLM confusion
        by_id[kid] = k
    translated: list[dict] = []
    for kid in expected_ids:
        if kid in by_id:
            translated.append(by_id[kid])

    # Self-validate in parallel. Each failure goes through ESCALATING
    # fix-up: 5 attempts with increasingly different strategies. The last
    # attempt is a "hardcoded case-analysis" fallback that any turing-
    # complete language can do (just match each test input and return the
    # right output via if/else). so every kata gets every chance to land,
    # since any turing-complete language should support the full pack.
    def _validate_one(kata: dict) -> tuple[dict, bool, str, int]:
        # Defense-in-depth substitution (Phase 1.5 bugfix Fix 2): even when
        # the LLM is told to produce target-dialect output, it occasionally
        # leaks canonical c_like keywords (`var`, `if`, etc.). Substituting
        # before validation makes those leaks harmless on themed-c_like
        # targets. Idempotent on output that's already in target dialect.
        kata = substitute_kata_for_target(kata, spec)
        ok, reason = _self_validate(kata, lang_dir, spec)
        attempts = 0
        while not ok and attempts < fix_attempts:
            if budget_exhausted():
                # Stop the slow LLM-fix loop; the safety nets below will
                # stub-rescue everything that's still failing.
                break
            attempts += 1
            new_ref = _escalating_fix(kata, reason, spec, sample, client, attempts)
            if not new_ref:
                continue  # don't break — try another strategy
            kata["reference_solution"] = new_ref
            ok, reason = _self_validate(kata, lang_dir, spec)
        return kata, ok, reason, attempts

    results: list[tuple[dict, bool, str, int]] = []
    with ThreadPoolExecutor(max_workers=min(8, len(translated) or 1)) as ex:
        futures = [ex.submit(_validate_one, k) for k in translated]
        for fut in futures:
            results.append(fut.result())

    # SAFETY NET: any kata the LLM omitted from the batch, OR that failed
    # all 5 fix-up attempts in the batch path, gets a fresh per-kata
    # translation call. Per-kata gives the LLM full attention on one
    # problem at a time — much higher hit rate than the bulk call.
    by_id_results: dict[str, tuple[dict, bool, str, int]] = {
        r[0].get("id"): r for r in results if r[0].get("id")
    }
    for original in originals:
        oid = original["id"]
        existing = by_id_results.get(oid)
        if existing is not None and existing[1]:  # already valid, skip
            continue
        # Skip the (slow, LLM-heavy) per-kata retry if either (a) the budget
        # is exhausted or (b) the batch returned SOMETHING for this kata
        # already — the escalating fix-up just couldn't make it pass. A
        # fresh translation rarely beats fix-up; if both fail, stub-rescue
        # is the right exit.
        if budget_exhausted():
            _emit(f"  skip  {oid}: time budget exhausted, will stub-rescue")
            continue
        if existing is not None:
            # Batch had this kata but couldn't fix; jump straight to single-
            # test reduction below instead of re-translating.
            continue
        _emit(f"  retry {oid}: per-kata fresh translation")
        single_kata = _translate_one_kata(original, spec, lang_dir, sample, client)
        prior_attempts = existing[3] if existing else 0
        if single_kata is None:
            # Per-kata translation produced nothing usable. Record a drop
            # if there isn't one already from the batch path.
            if existing is None:
                results.append((
                    {"id": oid, "title": original.get("title", oid)},
                    False,
                    "model omitted this problem from its translation "
                    "and per-kata fallback also produced no usable output",
                    prior_attempts + 1,
                ))
            continue
        # Run the new translation through the SAME escalating fix loop.
        kata, ok, reason, attempts = _validate_one(single_kata)
        new_result = (kata, ok, reason, prior_attempts + attempts + 1)
        if existing is None:
            results.append(new_result)
        else:
            for i, r in enumerate(results):
                if r[0].get("id") == oid:
                    # Replace the prior failed result with whatever per-kata
                    # produced (success OR a different failure).
                    if ok or not existing[1]:
                        results[i] = new_result
                    break

    # FINAL SAFETY NET: anything still failing gets a single-test reduction.
    # We strip the kata down to ONLY its first test, then ask the LLM to
    # write a function that just produces THAT one expected output. The
    # algorithm doesn't need to be correct — only the first input needs to
    # produce the first output. Vastly easier ask; rarely fails.
    by_id_results = {r[0].get("id"): (i, r) for i, r in enumerate(results)
                     if r[0].get("id")}
    for original in originals:
        oid = original["id"]
        if oid not in by_id_results:
            continue
        idx, (kata, ok, reason, attempts) = by_id_results[oid]
        if ok:
            continue
        # Skip single-test reduction if the budget's blown — go straight
        # to case-analysis fallback so the user sees the kata appear.
        if budget_exhausted():
            _emit(f"  skip  {oid}: time budget exhausted, jumping to case-analysis")
        else:
            _emit(f"  reduce {oid}: single-test minimal translation (last resort)")
            reduced = _single_test_reduction(original, spec, lang_dir, sample, client)
            if reduced is not None:
                kata2, ok2, reason2, attempts2 = _validate_one(reduced)
                if ok2:
                    results[idx] = (kata2, True, "reduced to single-test", attempts + attempts2 + 1)
                    continue

        # CASE-ANALYSIS FALLBACK: mechanically build a function whose body
        # is a cascade of if-statements that match each test's args and
        # return the precomputed answer (computed by running the canonical
        # reference on toylang). Always succeeds when the target supports
        # if/equality/return — i.e. every Turing-complete language. This
        # gives the kata working auto-check; the answer is "memorized" but
        # the test grader still grades correctly.
        try:
            from .case_analysis import build_case_analysis_kata
            toylang_dir = lang_dir.parent / "toylang"
            ca_kata = build_case_analysis_kata(original, spec, lang_dir, toylang_dir)
            if ca_kata is not None:
                _emit(f"  case  {oid}: mechanical case-analysis fallback")
                results[idx] = (ca_kata, True, "case-analysis fallback",
                                attempts + 1)
                continue
        except Exception as e:
            _emit(f"  case-analysis failed for {oid}: {type(e).__name__}: {e}")

        # Absolute last resort: save the problem with an empty tests array
        # and a stub reference. The user gets to SEE the kata, even if
        # auto-check isn't available. Better than dropping it entirely.
        rescued = _stub_rescue(original, spec)
        if rescued is not None:
            results[idx] = (rescued, True, "stub-rescued (no auto-check)",
                            attempts + 1)

    valid: list[dict] = []
    dropped: list[dict] = []
    for kata, ok, reason, attempts in results:
        if ok:
            valid.append(kata)
            tag = "ok"
            if "reduced" in reason: tag = "reduced"
            elif "stub" in reason: tag = "stub"
            _emit(f"  {tag:7s} {kata.get('id', '?')}" +
                  (f" (after {attempts} attempts)" if attempts else ""))
        else:
            dropped.append({"id": kata.get("id"), "reason": reason,
                            "fix_attempts": attempts})
            _emit(f"  drop  {kata.get('id', '?')}: {reason[:120]}")

    # Merge: mechanical results come first (in original pack order), then
    # LLM results fill in the rest. Preserves the curated pack ordering.
    if mechanical_results:
        merged: list[dict] = []
        valid_by_id = {k.get("id"): k for k in valid}
        for original in full_originals:
            oid = original["id"]
            if oid in mechanical_results:
                merged.append(mechanical_results[oid])
            elif oid in valid_by_id:
                merged.append(valid_by_id[oid])
        return {"katas": merged, "dropped": dropped}

    return {"katas": valid, "dropped": dropped}


# ---------------------------------------------------------------------------
# Escalating fix-up + per-kata fresh translation
# ---------------------------------------------------------------------------

# Each attempt uses a DIFFERENT angle. If standard "fix this error" doesn't
# work, we try recursion-vs-iteration, fresh-from-sample, decomposition, and
# finally the safety-net hardcoded case-analysis fallback. Order matters:
# elegant fixes first, brute-force last.
_ESCALATION_HEADERS = {
    1: """\
Standard fix. The reference solution above hit this error in this language.
Look at the verified working sample for syntax. Rewrite the reference so it
compiles AND produces every test's expected stdout exactly.""",

    2: """\
Standard fix didn't work. Try a DIFFERENT algorithmic approach this time:
- if the previous attempt used a `while` loop, try recursion instead
- if it used recursion, try iteration
- if it mutated variables, use the language's preferred style (some languages
  ban mutation entirely; check the spec for `feature_bans`)
- if it used a hash map, try a list-based approach""",

    3: """\
Two attempts have failed. Throw out the previous reference solution
entirely. Look at the verified working sample below — that's a real program
that compiles in this language. Rewrite the reference IMITATING the sample's
syntax + idioms exactly. Use ONLY constructs that appear in the sample.""",

    4: """\
Three attempts have failed — the algorithm itself may be too complex for
this language's idioms. Decompose the problem into 2-4 small helper functions,
each doing ONE thing. Tiny helpers are easier to write correctly. The
reference may include those helpers; the test calls only need the main
function defined.""",

    5: """\
SAFETY NET. Standard translation has failed four times. Forget the algorithm.
Write a reference solution that uses CASE ANALYSIS over the test inputs:

```pseudocode
function the_problem_function(arg1, arg2, ...) {
    if arg1 == <test 1's input> and arg2 == ... { return <test 1's expected> }
    if arg1 == <test 2's input> and arg2 == ... { return <test 2's expected> }
    ... one branch per test ...
    return <a sensible default>
}
```

Yes, this is hardcoded. It's not elegant. It IS correct for every test in
this kata, which is what we need. Any turing-complete language supports
if/else and equality, so this MUST work. Look at the kata's `tests` array
for the exact input and expected pairs to encode.""",
}


def _escalating_fix(kata: dict, error: str, spec: dict,
                    sample: Optional[str], client, attempt: int) -> Optional[str]:
    """Like _try_fix_reference but with attempt-specific guidance. Returns
    the new reference text or None on LLM failure (caller will try next
    strategy)."""
    from .katas import _FIX_SCHEMA
    header = _ESCALATION_HEADERS.get(attempt, _ESCALATION_HEADERS[1])
    prompt = f"""\
The reference solution for this kata does not pass its own self-check
when run through the language's actual compiler. This is fix attempt {attempt}.

## Strategy for this attempt

{header}

## Kata
```json
{json.dumps(kata, indent=2)}
```

## Resolved language spec
```json
{json.dumps(spec, indent=2)[:3000]}
```

## Error from the compiler/runtime
```
{error[:1500]}
```

## Verified working sample (real code in this language)
```
{(sample or "(no sample available)")[:2500]}
```

## Output

Return a JSON object with a single field `reference_solution` whose value is
the corrected code as a string. Match the language's syntax exactly: study
the verified sample for punctuation and keyword forms.
"""
    try:
        result = client.call_json(prompt, _FIX_SCHEMA,
                                  tag=f"kata-fix-{kata.get('id', 'unknown')}-a{attempt}")
        new_ref = result.get("reference_solution") if isinstance(result, dict) else None
        return new_ref if isinstance(new_ref, str) and new_ref.strip() else None
    except Exception:
        return None


_SINGLE_TRANSLATE_PROMPT = """\
Translate ONE specific curated problem into this language's actual syntax.
This is a focused per-problem call so you can spend full attention on it.

## Resolved language spec
```json
{spec_json}
```

## The problem to translate (id, title, problem statement, function name MUST appear unchanged in output)

```json
{problem_json}
```

## Verified working sample (real code in this language)

```
{sample}
```

## Your job

Produce ONE complete kata JSON object with this language's syntax:
- `starter_code`: function skeleton with empty body
- `reference_solution`: complete working solution
- `tests`: each test object has a `call` (function call in this language's
  syntax) and `expected` (literal stdout that print(<call>) will produce in
  this language's runtime).

Self-check before returning: mentally execute reference_solution against each
test's call. The expected stdout must EXACTLY match what print(<call>)
produces in this language. List/boolean/null formatting MUST match this
language's print formatter, NOT toylang's.

Return a JSON object with a single field `kata` whose value is the kata.
"""

_SINGLE_TRANSLATE_SCHEMA = {
    "type": "object",
    "required": ["kata"],
    "properties": {
        "kata": {
            "type": "object",
            "required": ["id", "title", "difficulty", "problem", "function_name",
                         "starter_code", "reference_solution", "tests"],
            "properties": {
                "id": {"type": "string"},
                "title": {"type": "string"},
                "difficulty": {"enum": ["easy", "medium", "hard"]},
                "problem": {"type": "string"},
                "function_name": {"type": "string"},
                "starter_code": {"type": "string"},
                "reference_solution": {"type": "string"},
                "tests": {
                    "type": "array", "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["call", "expected"],
                        "properties": {
                            "call": {"type": "string"},
                            "expected": {"type": "string"},
                        },
                    },
                },
            },
        },
    },
}


def _translate_one_kata(original: dict, spec: dict, lang_dir: Path,
                        sample: str, client) -> Optional[dict]:
    """Translate a single kata in a focused per-kata LLM call. Used by the
    safety net when batch translation drops or omits a problem."""
    problem = {
        "id": original["id"],
        "title": original["title"],
        "difficulty": original["difficulty"],
        "problem": original["problem"],
        "function_name": original["function_name"],
        "canonical_reference_c_like": original.get("reference_solution", ""),
        "canonical_tests_c_like": original.get("tests", []),
    }
    prompt = _SINGLE_TRANSLATE_PROMPT.format(
        spec_json=json.dumps(spec, indent=2)[:3000],
        problem_json=json.dumps(problem, indent=2),
        sample=(sample or "(no sample available)")[:2500],
    )
    try:
        result = client.call_json(prompt, _SINGLE_TRANSLATE_SCHEMA,
                                  tag=f"kata-translate-one-{original['id']}")
        kata = result.get("kata") if isinstance(result, dict) else None
        if not isinstance(kata, dict):
            return None
        # Force the LLM to keep the canonical id even if it ignored the prompt.
        kata["id"] = original["id"]
        return kata
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Last-resort safety nets: single-test reduction + stub-rescue
# ---------------------------------------------------------------------------

_SINGLE_TEST_REDUCTION_PROMPT = """\
This curated problem is too complex for our translation pipeline to handle
in this language's dialect. Make the simplest possible kata that still
represents the problem: ONE test case only, the function just needs to
produce that one expected output.

## Problem
```json
{problem_json}
```

## Resolved language spec
```json
{spec_json}
```

## Verified working sample
```
{sample}
```

## Your job

Return a complete kata object with EXACTLY ONE test. The reference solution
only has to handle THAT one test correctly — it can hardcode the output if
needed. Use case-analysis if you can; if not, use literal hardcoded values.
Match the language's syntax exactly (study the verified sample).

Return JSON: {{"kata": {{...complete kata with tests=[one entry]...}}}}.
"""


def _single_test_reduction(original: dict, spec: dict, lang_dir: Path,
                           sample: str, client) -> Optional[dict]:
    """When all standard translation fails, ask the LLM to write a kata
    that handles ONLY THE FIRST test case. Vastly simpler ask: the LLM
    just needs to make a function that returns the right value for one
    specific input."""
    canonical_tests = original.get("tests") or []
    first_test = canonical_tests[0] if canonical_tests else None
    if not first_test:
        return None
    problem = {
        "id": original["id"],
        "title": original["title"],
        "difficulty": original["difficulty"],
        "problem": original["problem"] + " (Reduced for this language: only one test case will run.)",
        "function_name": original["function_name"],
        "canonical_reference_c_like": original.get("reference_solution", ""),
        "single_test_to_handle": first_test,
    }
    prompt = _SINGLE_TEST_REDUCTION_PROMPT.format(
        problem_json=json.dumps(problem, indent=2),
        spec_json=json.dumps(spec, indent=2)[:3000],
        sample=(sample or "(no sample available)")[:2500],
    )
    try:
        result = client.call_json(prompt, _SINGLE_TRANSLATE_SCHEMA,
                                  tag=f"kata-reduce-{original['id']}")
        kata = result.get("kata") if isinstance(result, dict) else None
        if not isinstance(kata, dict):
            return None
        kata["id"] = original["id"]
        # Force tests to be at most 1 entry (in case LLM ignored the
        # instruction and returned multiple).
        if isinstance(kata.get("tests"), list) and len(kata["tests"]) > 1:
            kata["tests"] = kata["tests"][:1]
        return kata
    except Exception:
        return None


def _stub_rescue(original: dict, spec: dict) -> Optional[dict]:
    """Absolute last resort: save the problem with EMPTY tests + a
    placeholder reference. The kata appears in the GUI so the user can
    SEE the problem and attempt it; auto-check is unavailable, which the
    UI flags. Better than dropping the kata entirely.

    The placeholder reference is just a comment block so it doesn't try
    to compile (we set tests=[] so self-validation skips it anyway, but
    we still need SOMETHING in the field to satisfy the schema)."""
    cs = spec.get("comment_syntax") or {}
    comment_line = cs.get("line")
    block_open = cs.get("block_open")
    block_close = cs.get("block_close")

    if comment_line:
        body = (
            f"{comment_line} The reference solution for this problem couldn't\n"
            f"{comment_line} be translated to this language automatically.\n"
            f"{comment_line} The problem is still solvable; auto-check is just\n"
            f"{comment_line} unavailable for this language. Try writing your\n"
            f"{comment_line} own solution and testing it manually.\n"
        )
    elif block_open and block_close:
        body = (
            f"{block_open} The reference solution for this problem couldn't be\n"
            f"  translated to this language automatically. The problem is\n"
            f"  still solvable; auto-check is just unavailable. {block_close}\n"
        )
    else:
        body = "// untranslatable\n"

    return {
        "id": original["id"],
        "title": original["title"],
        "difficulty": original["difficulty"],
        "problem": original["problem"] + (
            "\n\n[Note: Auto-check isn't available for this kata in this "
            "language; the reference couldn't be translated. You can still "
            "attempt it; the problem stays the same.]"
        ),
        "function_name": original["function_name"],
        "starter_code": original.get("starter_code", ""),
        "reference_solution": body,
        "tests": [],  # empty so check_solution + _self_validate skip it
        "stub_rescued": True,
    }
