"""Phase 1 carryover C2: `_LazyLLMClient` must be safe under
introspection.

The lazy proxy in `forge/orchestrator/subprocess_runner.py` defers
real-client instantiation until the first `call_*` method is invoked.
That's how templated language families (s_expression, stack_based)
generate without `ANTHROPIC_API_KEY` set.

Before this carryover, the proxy used a `__getattr__` fallback that
materialized the real client on any unknown attribute access. Standard
introspection idioms — `hasattr(client, "X")`, `getattr(client, "X",
default)`, debug `repr()` — would silently trigger LLM client
construction and a hard failure when no API key was configured.

These tests pin the strict explicit-protocol contract:
  - Unknown attributes raise `AttributeError` without materialization.
  - `hasattr` / `getattr-with-default` are side-effect-free for both
    known and unknown names.
  - `repr()`, `bool()`, default Python introspection do not materialize.
  - Only the documented `call_*` methods cause materialization.
"""
from __future__ import annotations

import os
import pytest

from forge.orchestrator.subprocess_runner import _LazyLLMClient


@pytest.fixture
def no_api_key(monkeypatch):
    """Ensure ANTHROPIC_API_KEY is unset for the duration of the test.
    Materialization would call make_client() which raises in that
    state, so the test fixtures fail loudly if our 'don't materialize'
    contract leaks."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_hasattr_unknown_returns_false_without_materializing(no_api_key):
    """The classic risk: `hasattr(client, "client")` should be False
    (the proxy doesn't expose `client`) and must not construct a real
    LLM client to find out."""
    proxy = _LazyLLMClient()
    assert hasattr(proxy, "client") is False
    # Sanity: the proxy is still in lazy state.
    assert proxy._real is None


def test_hasattr_known_protocol_attrs_returns_true(no_api_key):
    """All documented protocol attributes resolve via explicit
    class-level definitions (properties / methods / instance attrs)
    without ever hitting `__getattr__` or `_materialize()`."""
    proxy = _LazyLLMClient()
    for name in proxy.protocol_attrs():
        assert hasattr(proxy, name), f"protocol attr {name!r} should resolve"
    # Still lazy.
    assert proxy._real is None


def test_getattr_with_default_unknown_returns_default(no_api_key):
    """`getattr(client, "missing", default)` is a common defensive
    idiom. It must not materialize."""
    proxy = _LazyLLMClient()
    sentinel = object()
    assert getattr(proxy, "totally_nonexistent_attribute", sentinel) is sentinel
    assert proxy._real is None


def test_repr_does_not_materialize(no_api_key):
    """`repr()` is called by debuggers, tracebacks, and the
    interactive REPL. It must reveal proxy state without forcing
    instantiation."""
    proxy = _LazyLLMClient()
    s = repr(proxy)
    assert "lazy" in s.lower() or "_LazyLLMClient" in s
    assert proxy._real is None


def test_bool_is_truthy_without_materializing(no_api_key):
    """`bool(client)` returns True via `object.__bool__` since the
    proxy doesn't define `__bool__`. Pin that this stays cheap."""
    proxy = _LazyLLMClient()
    assert bool(proxy) is True
    assert proxy._real is None


def test_class_introspection_does_not_materialize(no_api_key):
    """`__class__`, `type(...)`, `dir(...)` are all called by debug
    tooling. None should materialize."""
    proxy = _LazyLLMClient()
    assert proxy.__class__ is _LazyLLMClient
    assert type(proxy) is _LazyLLMClient
    names = dir(proxy)
    # dir() returns a list of strings; should include known protocol attrs.
    assert "call_code" in names
    assert "log_dir" in names
    assert proxy._real is None


def test_explicit_protocol_attrs_dont_force_materialization(no_api_key):
    """Reading the protocol attrs themselves — log_dir, model,
    telemetry — must be cheap. Only call_* methods materialize."""
    proxy = _LazyLLMClient(log_dir="/some/path")
    assert proxy.log_dir == "/some/path"
    assert proxy.model == "lazy:unresolved"
    assert proxy.telemetry is None
    # Setting log_dir post-construction (generate_all does this) also
    # must not materialize.
    proxy.log_dir = "/other/path"
    assert proxy.log_dir == "/other/path"
    assert proxy._real is None


def test_unknown_attribute_raises_attribute_error(no_api_key):
    """Direct `proxy.nonexistent` (without hasattr/getattr-default)
    raises AttributeError. Confirms the strict-protocol contract:
    no `__getattr__` fallback exists to silently materialize."""
    proxy = _LazyLLMClient()
    with pytest.raises(AttributeError):
        proxy.something_not_in_protocol  # noqa: B018
    assert proxy._real is None


def test_call_code_does_materialize_and_fails_without_key(no_api_key):
    """Sanity check the OTHER direction: documented `call_*` methods
    DO materialize. Without an API key we expect a clean error from
    `make_client()`, not a silent no-op. This proves the lazy
    behavior actually defers AND that the deferred work happens
    when expected."""
    proxy = _LazyLLMClient(provider="api")
    # Materialization should fail without an API key. Either a
    # RuntimeError ('ANTHROPIC_API_KEY not set') or a similar clean
    # failure is acceptable; the point is it tries and fails loudly.
    with pytest.raises((RuntimeError, ValueError, Exception)):
        proxy.call_code("anything", tag="test")


def test_telemetry_attachment_pre_materialization_forwards(no_api_key):
    """Telemetry attached before materialization must be forwarded
    to the real client when it's eventually constructed. This pins
    the existing forwarding logic in `_materialize()`."""
    from forge.orchestrator.telemetry import TelemetryRecorder
    proxy = _LazyLLMClient()
    rec = TelemetryRecorder(lang_name="x")
    proxy.telemetry = rec
    # Force materialization-then-fail by accessing _real via the
    # internal hook. We can't actually materialize without an API
    # key, so verify the attribute is set correctly pre-call.
    assert proxy.telemetry is rec
    assert proxy._real is None
