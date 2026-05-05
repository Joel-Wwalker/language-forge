"""Pin the component-tag-prefix discipline (Phase 1 carryover C1).

`generate_all` attributes each LLM call to a component using
`COMPONENT_TAG_PREFIXES` (in `forge/orchestrator/generator.py`). Every
component name in `COMPONENTS_STATIC` must have at least one prefix
entry, and every prefix entry must map to a real component. A future
component using a non-conforming tag silently gets 0 LLM calls
attributed in the telemetry summary; this test makes that an
explicit failure rather than a silent corruption.
"""
from __future__ import annotations

import re
from pathlib import Path

from forge.orchestrator.generator import (
    COMPONENTS_DYNAMIC,
    COMPONENTS_STATIC,
    COMPONENT_TAG_PREFIXES,
)


def test_every_component_has_a_tag_prefix_entry():
    """COMPONENTS_STATIC is the most complete component list (it
    includes typechecker which COMPONENTS_DYNAMIC omits). Every
    component name must appear in COMPONENT_TAG_PREFIXES."""
    missing = [c for c in COMPONENTS_STATIC if c not in COMPONENT_TAG_PREFIXES]
    assert not missing, (
        f"components {missing!r} have no entry in COMPONENT_TAG_PREFIXES; "
        f"their LLM calls will be silently attributed to nothing in "
        f"`generation_summary.json`. Add a prefix entry."
    )


def test_no_orphan_prefix_entries():
    """Reverse direction: every key in COMPONENT_TAG_PREFIXES must be
    a real component listed in COMPONENTS_STATIC. An orphan entry is
    dead weight at best and a hint of a renamed-but-not-cleaned-up
    component at worst."""
    valid = set(COMPONENTS_STATIC) | set(COMPONENTS_DYNAMIC)
    orphans = [k for k in COMPONENT_TAG_PREFIXES if k not in valid]
    assert not orphans, (
        f"COMPONENT_TAG_PREFIXES has orphan entries {orphans!r} that "
        f"don't match any component name. Remove or rename."
    )


def test_prefix_values_are_nonempty_tuples_of_strings():
    """Defensive: catch typos like a single-string value (which would
    iterate per-character and match almost anything)."""
    for comp, prefixes in COMPONENT_TAG_PREFIXES.items():
        assert isinstance(prefixes, tuple), (
            f"{comp!r} prefixes is {type(prefixes).__name__}, expected tuple. "
            f"A non-tuple would iterate per-character if it's a str."
        )
        assert len(prefixes) >= 1, f"{comp!r} has no prefix entries"
        for p in prefixes:
            assert isinstance(p, str) and p, (
                f"{comp!r} has invalid prefix entry {p!r}"
            )
            assert p.startswith("gen-"), (
                f"{comp!r} prefix {p!r} should start with 'gen-' to "
                f"match the convention used by `_generate_*` helpers"
            )


def test_actual_emitted_tags_are_covered_by_prefixes():
    """Walk the generator source and find every `tag=...` literal
    used in `client.call_*` calls. Every one must be matched by at
    least one prefix in COMPONENT_TAG_PREFIXES.

    This is the crucial check: it catches a future contributor who
    adds a new `tag="gen-something"` literal without registering it.
    Without this test, that contributor's component would silently
    drop its LLM call attribution."""
    src = (Path(__file__).resolve().parents[1] /
           "forge" / "orchestrator" / "generator.py").read_text(encoding="utf-8")

    # Find tag="..." or tag=f"..." inside call_code/call_json/call_chat calls.
    tag_literals: set[str] = set()
    # Plain string literal: tag="..."
    for m in re.finditer(r'tag="(gen-[a-z0-9_-]+)"', src):
        tag_literals.add(m.group(1))
    # f-string with a non-trivial static suffix and a substitution:
    # `tag=f"gen-tests-{name}"` — extract `gen-tests-`. The pattern
    # requires at least one character after `gen-` so we don't match
    # the bare `gen-{name}` convention pattern (where `{name}` IS the
    # component name, so it expands to a registered prefix at runtime).
    for m in re.finditer(r'tag=f"(gen-[a-z0-9_-]+)\{', src):
        tag_literals.add(m.group(1))

    # repair-* tags are emitted by repair.py, not generator.py: they
    # have a separate convention (component is in the tag suffix, not
    # the prefix). Out of scope for this discipline contract.
    tag_literals = {t for t in tag_literals if not t.startswith("repair-")}

    all_prefixes = tuple(p for prefixes in COMPONENT_TAG_PREFIXES.values()
                         for p in prefixes)
    uncovered = [t for t in tag_literals
                 if not any(t.startswith(p) for p in all_prefixes)]
    assert not uncovered, (
        f"these emitted tags don't match any registered prefix: {uncovered!r}\n"
        f"either add a matching prefix to COMPONENT_TAG_PREFIXES or "
        f"rename the tag literal in generator.py to use the conventional form"
    )
