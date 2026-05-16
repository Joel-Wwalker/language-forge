"""Structural variance — themed canonical-test bodies + themed examples.

Pins:
- `idiomatic_content(spec, ...)` returns a dict with sanitized
  `canonical_test_bodies` and optional `examples` on success.
- Returns `{}` on any failure (LLM exception, schema mismatch, both
  fields empty after sanitization).
- Cache key strips `lang_name`/`file_extension`/`lineage` and folds
  `IDIOMS_PROMPT_VERSION` — same pattern as creative.
- Bumping `IDIOMS_PROMPT_VERSION` invalidates entries from the prior
  version.
- The generator overlay validates each themed test body against the
  language's compiler + expected_output, accepting matches and
  silently rejecting mismatches (falling back to reference template).
- Example bodies that don't parse get dropped (no parse → no file
  written / file removed).
- The README's `## Examples` section enumerates the accepted themed
  examples; falls back to the generic paragraph when none landed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from forge.orchestrator.idioms import (
    idiomatic_content, clear_idioms_cache, _cache_key,
    IDIOMS_PROMPT_VERSION, CANONICAL_TEST_NAMES,
    _sanitize_examples, _sanitize_test_bodies,
)
from forge.orchestrator.spec_builder import build_spec
from forge.orchestrator.generator import (
    generate_all, _render_templated_readme,
)


WORKSPACE = Path(__file__).resolve().parents[1]


# A canned set of canonical test bodies that produce the same output
# as the reference templates for a vanilla c_like language. The
# test bodies are functionally equivalent to the reference ones so
# the per-body validation in the generator overlay accepts them.
#
# These bodies are constructed against the toylang reference, which
# uses `func` for function declarations, `var` for variables,
# semicolons for terminators, and braces for blocks. The c_like
# templated path inherits these.
_VALID_BODIES = {
    "hello_world": 'print("Hello, World!");\n',
    "arithmetic": 'print(1 + 2);\nprint(10 - 3);\nprint(4 * 5);\nprint(20 / 4);\n',
    "variables": 'var x = 10;\nvar y = 20;\nprint(x + y);\n',
    "conditionals": 'var x = 5;\nif (x > 3) { print("big"); } else { print("small"); }\n',
    "loops": 'var i = 0;\nwhile (i < 3) { print(i); i = i + 1; }\n',
    "functions": 'func add(a, b) { return a + b; }\nprint(add(2, 3));\n',
    "closures": 'func makeAdder(n) { func adder(x) { return x + n; } return adder; }\nvar add5 = makeAdder(5);\nprint(add5(10));\n',
    "strings": 'var s = "hi";\nprint(s + " there");\n',
}


_VALID_EXAMPLES = [
    {
        "name": "demo_one",
        "description": "A small themed example.",
        "body": 'print("example 1");\n',
    },
    {
        "name": "demo_two",
        "description": "Another themed example.",
        "body": 'var x = 42;\nprint(x);\n',
    },
]


class _StubIdiomsClient:
    """Stub LLM client returning canned idioms output."""
    log_dir = None
    model = "stub-idioms"
    telemetry = None

    def __init__(self, *, bodies=None, examples=None, raise_on_call=False):
        self.calls: list[str] = []
        if bodies is None:
            bodies = dict(_VALID_BODIES)
        self._bodies = bodies
        self._examples = examples if examples is not None else list(_VALID_EXAMPLES)
        self._raise = raise_on_call

    def call_json(self, prompt, schema, *, tag="json", **kw):
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, tag, time.monotonic() - 0.01,
                        200, 100, 1, True, None)
        self.calls.append(tag)
        if self._raise:
            raise RuntimeError("simulated LLM failure")
        out: dict = {}
        if self._bodies is not None:
            out["canonical_test_bodies"] = self._bodies
        if self._examples is not None:
            out["examples"] = self._examples
        return out

    def call_code(self, *a, **kw):
        return ""

    def call_chat(self, *a, **kw):
        return ""


@pytest.fixture
def fresh_idioms_cache(tmp_path):
    """Per-test isolated idioms cache directory."""
    cache_dir = tmp_path / "idioms_cache"
    yield cache_dir


def _make_spec(**overrides):
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        overrides.pop("lang_name", "idiom_test"),
    )
    for k, v in overrides.items():
        spec[k] = v
    return spec


# ---------------------------------------------------------------------------
# Sanitizer unit tests
# ---------------------------------------------------------------------------

def test_sanitize_test_bodies_keeps_well_formed():
    out = _sanitize_test_bodies(dict(_VALID_BODIES))
    assert set(out.keys()) == set(CANONICAL_TEST_NAMES)
    for v in out.values():
        assert v.endswith("\n")


def test_sanitize_test_bodies_drops_too_short():
    bodies = dict(_VALID_BODIES)
    bodies["arithmetic"] = "x"  # under 5 chars → drop
    out = _sanitize_test_bodies(bodies)
    assert "arithmetic" not in out
    assert "hello_world" in out  # others survive


def test_sanitize_test_bodies_drops_bogus_keys():
    bodies = dict(_VALID_BODIES)
    bodies["not_a_canonical_test"] = "print(1);\n"
    out = _sanitize_test_bodies(bodies)
    assert "not_a_canonical_test" not in out


def test_sanitize_examples_keeps_well_formed():
    out = _sanitize_examples(list(_VALID_EXAMPLES))
    assert len(out) == 2
    assert all("name" in e and "description" in e and "body" in e for e in out)


def test_sanitize_examples_rejects_path_traversal_names():
    """Example names must be valid Python identifiers (snake_case),
    so the LLM can't produce `examples/../escape.txt`."""
    bad = [
        {"name": "../escape", "description": "x", "body": "print(1);\n"},
        {"name": "with spaces", "description": "x", "body": "print(1);\n"},
        {"name": "UPPERCASE", "description": "x", "body": "print(1);\n"},
    ]
    out = _sanitize_examples(bad)
    assert out == []


def test_sanitize_examples_caps_at_six():
    many = [
        {"name": f"example_{i}", "description": "x", "body": "print(1);\n"}
        for i in range(10)
    ]
    out = _sanitize_examples(many)
    assert len(out) == 6


# ---------------------------------------------------------------------------
# idiomatic_content unit tests
# ---------------------------------------------------------------------------

def test_idiomatic_content_happy_path(fresh_idioms_cache):
    spec = _make_spec()
    client = _StubIdiomsClient()
    result = idiomatic_content(spec, client=client, cache_dir=fresh_idioms_cache)
    assert "canonical_test_bodies" in result
    assert "examples" in result
    assert len(result["canonical_test_bodies"]) == 8


def test_idiomatic_content_returns_empty_on_llm_exception(fresh_idioms_cache):
    spec = _make_spec()
    client = _StubIdiomsClient(raise_on_call=True)
    result = idiomatic_content(spec, client=client, cache_dir=fresh_idioms_cache)
    assert result == {}


def test_idiomatic_content_returns_empty_when_all_fields_drop(fresh_idioms_cache):
    spec = _make_spec()
    # Both fields produce nothing usable after sanitization.
    client = _StubIdiomsClient(bodies={}, examples=[])
    result = idiomatic_content(spec, client=client, cache_dir=fresh_idioms_cache)
    assert result == {}


def test_idiomatic_content_caches_by_content_hash(fresh_idioms_cache):
    """Two runs with the same spec hit the cache on the second call."""
    spec = _make_spec()
    c1 = _StubIdiomsClient()
    r1 = idiomatic_content(spec, client=c1, cache_dir=fresh_idioms_cache)
    c2 = _StubIdiomsClient()
    r2 = idiomatic_content(spec, client=c2, cache_dir=fresh_idioms_cache)
    assert r1 == r2
    assert c1.calls == ["gen-idioms"]
    # Second client never received the underlying gen-idioms call —
    # only the cache-hit telemetry shim.
    assert c2.calls == []


def test_idiomatic_content_cache_ignores_lang_name(fresh_idioms_cache):
    """Different lang_name on otherwise identical specs share a cache entry."""
    s1 = _make_spec(lang_name="lang_a")
    s2 = _make_spec(lang_name="lang_b")
    assert _cache_key(s1) == _cache_key(s2)


def test_prompt_version_invalidates_old_cache(fresh_idioms_cache, monkeypatch):
    """Bumping IDIOMS_PROMPT_VERSION should produce a different cache key."""
    spec = _make_spec()
    key_v1 = _cache_key(spec)
    monkeypatch.setattr("forge.orchestrator.idioms.IDIOMS_PROMPT_VERSION", 99)
    key_v99 = _cache_key(spec)
    assert key_v1 != key_v99


def test_prompt_version_constant_is_four():
    """Pin the version. Bump deliberately when the prompt changes
    semantically.
      v1 -> v2: themed body's actual stdout becomes new expected_output.
      v2 -> v3: structural-variance-channel Seam 2; added per-family
                worked-example blocks (2 reference tests per family)
                so the LLM has actually-parseable anchors instead of
                paradigm-shaped guesses.
      v3 -> v4: logic-family experiment Stage F; added logic_like
                worked-example block (countdown + factorial) plus the
                syntax-rules paragraph pinning facts/rules/queries,
                `:-` operator, `is/2` vs `=/2`, var-uppercase /
                atom-lowercase, and write/nl output. Prevents the LLM
                from emitting SWI features (cut, assert, op/3) that
                prologlang v1 rejects."""
    assert IDIOMS_PROMPT_VERSION == 4


def test_canonical_test_names_match_generator():
    """The list of canonical test names in idioms.py must stay in sync
    with generator.py's _CANONICAL_TESTS. If this drifts, the overlay
    silently skips tests that were generated."""
    from forge.orchestrator.generator import _CANONICAL_TESTS
    assert tuple(_CANONICAL_TESTS) == CANONICAL_TEST_NAMES


# ---------------------------------------------------------------------------
# End-to-end: generate_all with idioms enrichment
# ---------------------------------------------------------------------------

class _DualClient:
    """Combined creative+idioms stub for end-to-end generate_all tests.
    Returns canned readme_intro for `gen-creative` tag, canned bodies
    for `gen-idioms` tag."""
    log_dir = None
    model = "stub-dual"
    telemetry = None

    _DEFAULT_INTRO = (
        "Stub readme_intro for the end-to-end idioms test. This needs "
        "to be at least 40 words long so the creative validator doesn't "
        "drop it; padding with this sentence and adding more words to "
        "make sure we cross the threshold cleanly under the loose "
        "word-count window the creative module enforces."
    )

    def __init__(self, *, idioms_bodies=None, idioms_examples=None):
        self.calls: list[str] = []
        self._bodies = idioms_bodies if idioms_bodies is not None else dict(_VALID_BODIES)
        self._examples = idioms_examples if idioms_examples is not None else list(_VALID_EXAMPLES)

    def call_json(self, prompt, schema, *, tag="json", **kw):
        from forge.orchestrator.llm_client import _emit_telemetry
        _emit_telemetry(self, tag, time.monotonic() - 0.01,
                        200, 100, 1, True, None)
        self.calls.append(tag)
        if tag == "gen-creative":
            return {"readme_intro": self._DEFAULT_INTRO}
        if tag == "gen-idioms":
            out: dict = {}
            if self._bodies is not None:
                out["canonical_test_bodies"] = self._bodies
            if self._examples is not None:
                out["examples"] = self._examples
            return out
        return {}

    def call_code(self, *a, **kw):
        return ""

    def call_chat(self, *a, **kw):
        return ""


@pytest.mark.slow
def test_generate_all_calls_idioms_once_for_clike(tmp_path, fresh_idioms_cache, monkeypatch):
    """generate_all triggers exactly one gen-idioms call alongside
    gen-creative."""
    # Force the idioms module to use the per-test cache dir so we
    # don't pollute the real one.
    monkeypatch.setattr(
        "forge.orchestrator.idioms._DEFAULT_CACHE_DIR",
        fresh_idioms_cache,
    )
    # Also clear the creative cache so the creative call fires fresh.
    from forge.orchestrator.creative import clear_creative_cache
    clear_creative_cache()

    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "idioms_wiring",
    )
    client = _DualClient()
    generate_all(spec, output_root=tmp_path, client=client,
                 verify_after_generation=False)

    # Both creative and idioms should have fired exactly once.
    assert "gen-creative" in client.calls
    assert client.calls.count("gen-idioms") == 1, (
        f"expected exactly one gen-idioms call; got {client.calls}"
    )

    # At least some themed bodies should have been accepted (the
    # _VALID_BODIES are functionally equivalent to the reference
    # templates, so they produce identical output).
    saved = json.loads(
        (tmp_path / "idioms_wiring" / "resolved_spec.json").read_text(encoding="utf-8")
    )
    overlay = saved.get("idioms", {}).get("overlay_result", {})
    accepted = overlay.get("tests_accepted", [])
    # hello_world is the easiest to template-match across substitution
    # variants, so it should always be accepted here.
    assert "hello_world" in accepted, (
        f"expected hello_world themed body to validate cleanly; "
        f"accepted={accepted}, rejected={overlay.get('tests_rejected')}"
    )


def test_render_templated_readme_falls_back_when_no_idioms():
    """If `spec.idioms` is missing or has no examples_accepted, the
    README's ## Examples section uses the generic fallback paragraph."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "fallback_test",
    )
    out = _render_templated_readme(spec)
    assert "See `examples/` and `tests/` for working programs." in out


def test_render_templated_readme_enumerates_accepted_examples():
    """When spec.idioms has examples that passed parse-check (in
    overlay_result.examples_accepted), the README enumerates them
    under ## Examples with their descriptions."""
    spec = build_spec(
        {"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
        "enum_test",
    )
    spec["idioms"] = {
        "examples": [
            {"name": "treasure_map", "description": "Parses an X-marks-the-spot map.", "body": "..."},
            {"name": "compass_bearing", "description": "Computes bearings.", "body": "..."},
        ],
        "overlay_result": {
            "tests_accepted": [], "tests_rejected": [],
            "examples_accepted": ["treasure_map", "compass_bearing"],
            "examples_rejected": [],
        },
    }
    out = _render_templated_readme(spec)
    assert "treasure_map" in out
    assert "Parses an X-marks-the-spot map." in out
    assert "compass_bearing" in out
    assert "Computes bearings." in out
    # The generic fallback paragraph should NOT appear when themed
    # examples are present.
    assert "See `examples/` and `tests/` for working programs." not in out
