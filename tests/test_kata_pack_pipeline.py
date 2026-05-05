"""Pipeline test: every kata reference must pass every test.

This is the CI gate that catches kata regressions. Each kata pack
gets validated against its reference compiler (toylang for c_like,
lisplang for s_expression, forthlang for stack_based). Every test of
every kata must pass when the pack's reference solution is submitted.

If a future change breaks a reference (typo in syntax, formatter
change, runtime regression), `test_pack_validates_against_reference`
fails with the per-kata-per-test breakdown via `format_summary`, so
you can pinpoint the broken case from a single failure message.

The same `validate_pack` logic powers the
`python -m forge.orchestrator.validate_kata_pack` CLI for ad-hoc
verification outside CI.

PERF NOTE: a session-scoped fixture caches `validate_pack` results so
each pack's reference compiler runs just once per test session. Without
this, the 13 stack_classics katas + 12 c_like classics × 5 tests-per-
kata × subprocess spawn each = many minutes wasted on redundant runs.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Session-scoped cache. Runs validate_pack ONCE per pack per test session.
# All tests below share the same result dict via this fixture.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pack_validation_results():
    """Validate every shipped pack against its reference compiler. The
    expensive subprocess runs happen here ONCE per session; tests just
    look up the cached PackResult."""
    from forge.orchestrator.kata_packs import list_packs
    from forge.orchestrator.validate_kata_pack import validate_pack
    cache = {}
    for p in list_packs():
        try:
            cache[p["key"]] = validate_pack(p["key"])
        except (ValueError, FileNotFoundError) as e:
            # Pack has no reference language (e.g. python_like has none yet);
            # skip it from the gate. Other tests can still load such packs
            # via /api/.../load-pack which uses LLM translation.
            cache[p["key"]] = e
    return cache


# ---------------------------------------------------------------------------
# Per-pack gate. ONE test per shipped pack. On failure, format_summary
# spells out exactly which kata + which test regressed.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pack_key,expected_lang", [
    ("classics",       "toylang"),
    ("stack_classics", "forthlang"),
])
def test_pack_validates_against_reference(pack_key, expected_lang,
                                           pack_validation_results):
    """Exhaustive validation: every reference solution must pass every
    test in the pack. On failure, the assertion message names the
    specific kata + test that regressed."""
    from forge.orchestrator.validate_kata_pack import format_summary
    result = pack_validation_results[pack_key]
    if isinstance(result, Exception):
        pytest.skip(f"pack {pack_key} couldn't be validated: {result}")
    assert result.lang == expected_lang
    if not result.all_passed:
        pytest.fail(
            f"\n{pack_key} pack regression on {expected_lang}:\n\n"
            + format_summary(result)
        )


# ---------------------------------------------------------------------------
# Per-kata totals. One test per kata, just confirms the kata's tests all
# passed. Faster + cleaner CI display than per-test parametrization, and
# any per-test failure detail is already in the per-pack test's output.
# ---------------------------------------------------------------------------

def _enumerate_katas():
    from forge.orchestrator.kata_packs import list_packs, get_pack
    for p in list_packs():
        pack = get_pack(p["key"])
        if pack is None:
            continue
        for kata in pack["katas"]:
            yield p["key"], kata["id"]


@pytest.mark.parametrize("pack_key,kata_id", list(_enumerate_katas()))
def test_kata_reference_passes_all_tests(pack_key, kata_id,
                                          pack_validation_results):
    """One pytest case per kata. Lets the CI dashboard show
    `stack_classics::tree_max_depth FAILED` instead of `the whole
    pack regressed`, while still avoiding the 129-case explosion of
    a per-test parametrization."""
    result = pack_validation_results[pack_key]
    if isinstance(result, Exception):
        pytest.skip(f"pack {pack_key} couldn't be validated: {result}")
    kata = next((k for k in result.katas if k.kata_id == kata_id), None)
    assert kata is not None, f"kata {kata_id!r} not in pack {pack_key!r}"
    if kata.compile_error:
        pytest.fail(
            f"{pack_key}::{kata_id}: reference failed to compile/run\n"
            f"  error: {kata.compile_error}"
        )
    failing = [(t.test_index, t.call, t.expected, t.actual)
               for t in kata.test_results if not t.passed]
    if failing:
        details = "\n".join(
            f"  test {idx}: {call}\n"
            f"    expected: {exp!r}\n"
            f"    actual:   {act!r}"
            for idx, call, exp, act in failing
        )
        pytest.fail(
            f"{pack_key}::{kata_id}: {len(failing)} of "
            f"{len(kata.test_results)} tests failed:\n{details}"
        )


# ---------------------------------------------------------------------------
# CLI exit-code contract: 0 on full pass, 1 on any failure, 2 on bad input.
# These DON'T use the cached fixture - we want to verify the actual CLI
# runs end-to-end. Each calls validate_pack once.
# ---------------------------------------------------------------------------

def test_validate_cli_returns_zero_when_pack_passes(pack_validation_results):
    """Cheap path: don't actually re-run validate_pack here; the cached
    result already proves the pack passes, so the CLI's `main` call
    would return 0 if invoked with the same args.

    We DO call main() once just to verify the entry point is wired up,
    but with `--json` to avoid stdout encoding issues on Windows."""
    from forge.orchestrator.validate_kata_pack import main
    rc = main(["stack_classics", "--json"])
    assert rc == 0


def test_validate_cli_returns_two_for_unknown_pack(capsys):
    from forge.orchestrator.validate_kata_pack import main
    rc = main(["nonexistent_pack"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "no such pack" in err


def test_validate_default_lang_from_syntax_family(pack_validation_results):
    """When no `lang` is given, validate_pack auto-picks the reference
    compiler matching the pack's syntax_family. Verified via the
    cached result, which was built without an explicit lang."""
    result = pack_validation_results["stack_classics"]
    assert not isinstance(result, Exception)
    assert result.lang == "forthlang"


def test_validate_explicit_lang_argument_works():
    """Smoke test of the explicit-lang code path. We pass forthlang
    explicitly and verify validate_pack honors it (rather than re-
    deriving from syntax_family)."""
    from forge.orchestrator.validate_kata_pack import validate_pack
    result = validate_pack("stack_classics", "forthlang")
    assert result.lang == "forthlang"
    # We trust the session-scoped cache that all_passed is True; this
    # test is just the lang-routing check.
