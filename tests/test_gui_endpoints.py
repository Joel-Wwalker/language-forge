"""Tests for the Flask GUI endpoints that don't need an LLM call.

These exercise the REST surface (routes, status codes, payload shapes) so a
regression in the GUI app surfaces immediately, without burning API tokens.
"""
from __future__ import annotations

import json
import zipfile
import io
from pathlib import Path

import pytest

from forge.gui.app import create_app


WORKSPACE = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# ----------------------- discovery / list endpoints --------------------------

def test_list_languages_returns_array(client):
    r = client.get("/api/languages")
    assert r.status_code == 200
    payload = r.get_json()
    assert "languages" in payload
    assert isinstance(payload["languages"], list)
    # toylang is the hand-written reference, must always be present
    assert any(l["name"] == "toylang" for l in payload["languages"])


def test_list_personas_has_known_entries(client):
    r = client.get("/api/personas")
    assert r.status_code == 200
    keys = {p["key"] for p in r.get_json()["personas"]}
    assert {"dijkstra", "wadler", "matz"}.issubset(keys)


def test_list_eras(client):
    r = client.get("/api/eras")
    assert r.status_code == 200
    keys = {e["key"] for e in r.get_json()["eras"]}
    assert keys == {"1960s", "1970s", "1980s", "2000s", "2020s"}


def test_list_themes(client):
    r = client.get("/api/themes")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["themes"]
    for t in payload["themes"]:
        assert "key" in t and "preview" in t


def test_list_bans_includes_no_loops(client):
    r = client.get("/api/bans")
    assert r.status_code == 200
    keys = {b["key"] for b in r.get_json()["bans"]}
    assert "no_loops" in keys
    assert "no_mutation" in keys


def test_list_samples(client):
    r = client.get("/api/samples")
    assert r.status_code == 200
    keys = {s["key"] for s in r.get_json()["samples"]}
    assert "fibonacci" in keys
    assert "fizzbuzz" in keys


def test_providers_endpoint_shape(client):
    r = client.get("/api/providers")
    assert r.status_code == 200
    payload = r.get_json()
    assert "default" in payload
    assert "available" in payload
    assert isinstance(payload["available"], dict)
    assert "api" in payload["available"]
    assert "claude_cli" in payload["available"]


# ----------------------- per-language endpoints ------------------------------

def test_spec_endpoint_returns_toylang(client):
    r = client.get("/api/spec/toylang")
    assert r.status_code == 200
    spec = r.get_json()
    assert spec["lang_name"] == "toylang"
    assert spec["options"]["syntax"] == "c_like"


def test_spec_endpoint_404_on_unknown(client):
    r = client.get("/api/spec/nonexistentlang")
    assert r.status_code == 404


def test_verify_endpoint_runs_canonicals(client):
    r = client.post("/api/verify/toylang")
    assert r.status_code == 200
    report = r.get_json()
    assert report["all_passed"] is True
    assert len(report["tests"]) >= 8
    passing = [t for t in report["tests"] if t["status"] == "pass"]
    assert len(passing) == len(report["tests"])


def test_verify_endpoint_404_on_unknown(client):
    r = client.post("/api/verify/nope")
    assert r.status_code == 404


def test_run_endpoint_executes_program(client):
    r = client.post("/api/run", json={
        "lang": "toylang",
        "source": 'print("hi from test");\n',
    })
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["ok"] is True
    assert "hi from test" in payload["stdout"]


def test_run_endpoint_404_on_unknown_lang(client):
    r = client.post("/api/run", json={"lang": "nope", "source": ""})
    assert r.status_code == 404


def test_example_endpoint_returns_canonical(client):
    r = client.get("/api/example/toylang/hello_world")
    assert r.status_code == 200
    body = r.get_json()
    assert "Hello, World!" in body["source"]


def test_example_endpoint_returns_shipped_curated(client):
    """Curated samples shipped to a language's examples/ are reachable."""
    r = client.get("/api/example/toylang/fibonacci")
    assert r.status_code == 200
    body = r.get_json()
    # `fibonacci` is shipped as an example; we should get the actual file.
    assert "fib" in body["source"].lower()


def test_example_endpoint_404_for_unshipped_curated(client):
    """If a curated sample isn't shipped to this language (compile-check
    failed), the endpoint must NOT silently return the global curated source.
    That was the bug behind the user's 'compile failed' report."""
    # toylang has a clean fibonacci, but pick a name guaranteed not to exist.
    r = client.get("/api/example/toylang/bogus_sample_name_xyz")
    assert r.status_code == 404


def test_languages_endpoint_includes_shipped_list(client):
    """Library cards / Playground need the shipped list to filter examples."""
    r = client.get("/api/languages")
    payload = r.get_json()
    toylang = next((l for l in payload["languages"] if l["name"] == "toylang"), None)
    assert toylang is not None
    assert isinstance(toylang.get("shipped"), list)
    # toylang ships the canonical 8 plus the curated samples.
    shipped = set(toylang["shipped"])
    assert "hello_world" in shipped
    assert "fizzbuzz" in shipped or "fibonacci" in shipped    # at least one curated


def test_standalone_repl_serves_html(client):
    r = client.get("/api/standalone/toylang")
    assert r.status_code == 200
    assert r.mimetype == "text/html"
    body = r.get_data(as_text=True)
    assert "Pyodide" in body
    assert "toylang" in body


def test_standalone_repl_download_sets_attachment(client):
    r = client.get("/api/standalone/toylang?download=1")
    assert r.status_code == 200
    cd = r.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert "toylang.repl.html" in cd


def test_standalone_repl_404_on_unknown(client):
    r = client.get("/api/standalone/notreal")
    assert r.status_code == 404


def test_download_zip_serves_zip(client):
    r = client.get("/api/download/toylang")
    assert r.status_code == 200
    assert r.mimetype == "application/zip"
    cd = r.headers.get("Content-Disposition", "")
    assert "attachment" in cd

    # Inspect the zip
    zf = zipfile.ZipFile(io.BytesIO(r.get_data()))
    names = zf.namelist()
    # Wrapped in a top-level dir named after the language
    assert all(n.startswith("toylang/") for n in names)
    # Has the essentials
    assert "toylang/pyproject.toml" in names
    assert "toylang/LICENSE" in names
    assert "toylang/INSTALL.md" in names
    assert "toylang/README.md" in names
    assert "toylang/compile.py" in names
    # Excludes the things we said we'd exclude
    assert not any(".forge_log" in n for n in names)
    assert not any("_playground" in n for n in names)
    assert not any(n.endswith(".out.py") for n in names)
    assert not any("__pycache__" in n for n in names)


def test_download_zip_404_on_unknown(client):
    r = client.get("/api/download/notreal")
    assert r.status_code == 404


def test_delete_protects_toylang(client):
    """toylang is the hand-written reference; the GUI must refuse to delete it."""
    r = client.delete("/api/language/toylang")
    assert r.status_code == 400
    payload = r.get_json()
    assert "protected" in payload["error"].lower()


def test_delete_rejects_path_traversal(client):
    r = client.delete("/api/language/..%2Fforge")
    # Either 400 (rejected by isidentifier) or 404 — never 200
    assert r.status_code in (400, 404)


def test_delete_404_on_unknown(client):
    r = client.delete("/api/language/notreallyalang")
    assert r.status_code == 404


# ----------------------- /api/create validation ------------------------------

def test_create_rejects_bad_name(client):
    r = client.post("/api/create", json={
        "syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
        "name": "not a valid name",
    })
    assert r.status_code == 400


def test_create_rejects_bad_customization(client):
    r = client.post("/api/create", json={
        "syntax": "c_like", "typing": "dynamic", "memory": "host_gc",
        "name": "demo",
        "customization": {"file_extension": "way-too-long-extension-name"},
    })
    assert r.status_code == 400
