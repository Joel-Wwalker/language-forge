# Audit suite

These are deep, end-to-end audits of two subsystems: the **kata system**
(LeetCode-style problem library + auto-grader) and the **language
generation pipeline** (spec → resolver → components → verifier → repair).

They aren't run as part of `pytest` because they cross many boundaries
(spec_builder, coherence, presets, customization, mechanical translator,
runtime patcher, GUI endpoints, persisted katas.json, every existing
`generated/<lang>/`). Instead, each is a standalone Python script that
walks every interesting code path it can reach, exercises it, and writes
a single human-readable report file with **intent + result + fix** for
each check.

## Files

| File | What it does |
|---|---|
| `test_kata_audit.py` | Audits the kata system: helpers field, run/submit modes, data model, cache, no_mutation routing, mechanical translator, runtime patcher, stub-rescue, edge cases, translator safety nets. |
| `test_lang_gen_audit.py` | Audits language generation: cartesian (syntax × typing × memory), every extended option, every preset (personas, eras, themes, phrasebooks, bans), customization layers, component pipeline, verifier on every existing language, repair picker, GUI endpoints. |
| `KATA_AUDIT_REPORT.txt` | Latest run's findings for the kata audit. |
| `LANG_GEN_AUDIT_REPORT.txt` | Latest run's findings for the language-generation audit. |

## Running

From the repo root:

```bash
python tests/audit/test_kata_audit.py
python tests/audit/test_lang_gen_audit.py
```

Each script prints a `<N> PASS, <M> BUG` summary and writes its full
report alongside itself. Exit code is 0 if no bugs were found.

## Output format

Each report has one entry per check:

```
[PASS] A1: _wrap_with_test_prints prepends helpers
------------------------------------------------------------------------------
Intent: Helpers must come BEFORE user code so they're in scope.
Result: helper() appears at byte 0, main() at 30
```

Status values:
- `PASS`  — the check confirms the intent.
- `BUG`   — the check found something wrong; details + fix follow.
- `FIXED` — was a `BUG` in a previous run, now confirmed fixed by the audit.
- `SKIP`  — the check couldn't run (missing dependency etc.).

## What these caught the first time around

- **Kata audit**: tag filter not refreshing on language switch (M1),
  cache not invalidating when source pack changes (M4), open kata
  pointing to stale data after force-reload (M5).
- **Language-gen audit**: `hardcombo`'s codegen `visit_assign_op` reading
  `children[2]` (was 2-child tree, IndexError); typechecker `paren` rule
  reading `children[0]` (the `(` token) instead of the expression at
  `children[1]`; `visit_paren` in codegen with the same off-by-one.
  Three one-line fixes turned hardcombo from 4/8 to 8/8 canonical tests.

These are the kinds of bugs that hide until you run a checklist that
specifically looks for them. The audits are the checklist.
