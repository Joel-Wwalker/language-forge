"""Tests for the showcase programs and the run-on-all endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest

from forge.gui.app import create_app
from forge.gui.samples import SAMPLES, get_sample
from forge.orchestrator.generator import _SAMPLE_REQUIREMENTS


WORKSPACE = Path(__file__).resolve().parents[1]
TOYLANG_DIR = WORKSPACE / "generated" / "toylang"


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------------
# New showcase samples
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["mandelbrot", "prime_sieve", "palindrome", "ascii_tree"])
def test_showcase_sample_in_library(name):
    """Each showcase sample is registered in SAMPLES and has both flavors."""
    assert name in SAMPLES
    c_like = get_sample(name, "c_like")
    py_like = get_sample(name, "python_like")
    assert c_like and py_like
    # c_like uses braces and semicolons somewhere; python_like uses neither.
    assert ";" in c_like
    assert "{" in c_like
    assert ";" not in py_like
    assert "{" not in py_like


@pytest.mark.parametrize("name", ["mandelbrot", "prime_sieve", "palindrome", "ascii_tree"])
def test_showcase_sample_has_requirements(name):
    """Every showcase sample has its stdlib requirements declared."""
    assert name in _SAMPLE_REQUIREMENTS
    assert "print" in _SAMPLE_REQUIREMENTS[name]


def test_showcase_samples_shipped_to_toylang():
    """toylang has a complete runtime so it should ship every showcase sample."""
    examples = TOYLANG_DIR / "examples"
    for name in ("mandelbrot", "prime_sieve", "palindrome", "ascii_tree"):
        assert (examples / f"{name}.toy").exists(), f"{name} not shipped to toylang"


# ---------------------------------------------------------------------------
# /api/run-all
# ---------------------------------------------------------------------------

def test_run_all_endpoint_returns_per_language_results(client):
    """A trivial program should compile and run on every healthy language."""
    src = 'print("hi");\n'
    r = client.post("/api/run-all", json={"source": src})
    assert r.status_code == 200
    payload = r.get_json()
    assert "results" in payload
    # toylang must succeed (it's the hand-written reference).
    toy = payload["results"].get("toylang")
    assert toy is not None
    assert toy["ok"] is True
    assert "hi" in toy["stdout"]


def test_run_all_endpoint_rejects_empty_source(client):
    r = client.post("/api/run-all", json={"source": ""})
    assert r.status_code == 400


def test_run_all_endpoint_per_language_stage(client):
    """Each result has a stage field. Successful runs have stage='ok'."""
    r = client.post("/api/run-all", json={"source": 'print(1);\n'})
    payload = r.get_json()
    for lang, res in payload["results"].items():
        assert "ok" in res
        assert "stage" in res
        if res["ok"]:
            assert res["stage"] == "ok"


def test_run_all_endpoint_handles_compile_failure(client):
    """An unparseable source returns ok=False with a stage marker per language."""
    r = client.post("/api/run-all", json={"source": "this is not valid in any language at all"})
    assert r.status_code == 200
    payload = r.get_json()
    # Most languages should have failed to compile; none should crash the endpoint.
    for lang, res in payload["results"].items():
        assert "stage" in res
        if not res["ok"]:
            assert res["stage"] in ("compile", "run", "timeout", "error")


def test_run_all_respects_lang_filter(client):
    """When `langs` is supplied, only those are run."""
    r = client.post("/api/run-all", json={"source": 'print(1);\n', "langs": ["toylang"]})
    payload = r.get_json()
    assert list(payload["results"].keys()) == ["toylang"]
