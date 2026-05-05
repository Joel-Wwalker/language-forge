"""Regression tests from the second audit round.

After the s_expression-specific audit (test_s_expression_audit_fixes.py),
a broader audit found bugs in:
- JOBS dict (race condition, no lock)
- delete_lang (symlink path-traversal vulnerability)
- SSE stream (hangs on silent worker crash)
- _compile_and_run (tempfile leaks, brittle Windows cleanup)
- katas.json writes (concurrent corruption, NaN/Infinity slipping through)
- generate_all (stale __pycache__ from previous runs)

Plus performance fixes:
- Lark cache=True for the toylang reference parser
- Parallel _emit_examples compile checks
- Standalone REPL mtime-based caching
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]


# ---------- BUG: JOBS dict is now lock-protected ----------

def test_register_and_get_job_round_trip():
    from forge.gui.app import register_job, get_job
    from forge.gui.app import Job
    j = Job(opts={"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
            name="test_job_lock", provider=None)
    register_job(j)
    fetched = get_job(j.id)
    assert fetched is j


def test_jobs_concurrent_register_no_loss():
    """Stress test: 50 threads each register a job; afterward all 50
    must be findable via get_job(). Without the lock, dict resize during
    insertion could lose entries on some Python versions."""
    from forge.gui.app import register_job, get_job, Job

    jobs = []
    def make_one(i):
        j = Job(opts={"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
                name=f"stress_{i}", provider=None)
        register_job(j)
        jobs.append(j)

    threads = [threading.Thread(target=make_one, args=(i,)) for i in range(50)]
    for t in threads: t.start()
    for t in threads: t.join()

    assert len(jobs) == 50
    for j in jobs:
        assert get_job(j.id) is j


# ---------- BUG: delete_lang refuses to delete symlinks ----------

def test_delete_refuses_symlink(tmp_path, monkeypatch):
    """Even an attacker who places a symlink in generated/ pointing
    outside the project must NOT be able to delete the target via
    /api/language/<lang>. The 'is_relative_to' check alone is
    insufficient (resolved paths bypass it via the symlink target);
    we must explicitly refuse symlinks."""
    from forge.gui.app import create_app
    from forge.gui import app as app_module

    # Build a fake workspace under tmp_path with `generated/`
    fake_workspace = tmp_path
    gen = fake_workspace / "generated"
    gen.mkdir(parents=True)

    # Create a real "victim" directory OUTSIDE generated/ that we'll try
    # to protect: the test verifies that the API doesn't delete it.
    victim = fake_workspace / "victim_outside"
    victim.mkdir()
    (victim / "important.txt").write_text("don't delete me", encoding="utf-8")

    # Place a symlink inside generated/ pointing at the victim. On
    # Windows, symlink creation requires admin or developer mode; skip
    # the test if we can't create one.
    link = gen / "evil"
    try:
        link.symlink_to(victim, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")

    # Repoint the app module's WORKSPACE at the fake one for this test.
    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    app = create_app()
    client = app.test_client()
    r = client.delete("/api/language/evil")
    assert r.status_code == 400
    body = r.get_json()
    assert "symlink" in body.get("error", "").lower(), body

    # CRITICAL: the victim must still exist with its file intact.
    assert victim.exists()
    assert (victim / "important.txt").exists()


def test_delete_refuses_protected_lisplang():
    """lisplang is a hand-written reference; it must not be deletable
    via the API, same as toylang."""
    from forge.gui.app import create_app
    app = create_app()
    client = app.test_client()
    r = client.delete("/api/language/lisplang")
    assert r.status_code == 400
    assert "protected" in r.get_json().get("error", "").lower()


# ---------- BUG: atomic katas.json writes ----------

def test_atomic_write_json_replaces_existing(tmp_path):
    from forge.orchestrator.katas import atomic_write_json
    target = tmp_path / "katas.json"
    target.write_text("OLD CONTENT", encoding="utf-8")
    atomic_write_json(target, {"katas": [{"id": "x"}]})
    assert json.loads(target.read_text(encoding="utf-8")) == {"katas": [{"id": "x"}]}


def test_atomic_write_json_no_partial_on_crash(tmp_path):
    """If serialization fails (e.g. NaN floats), the original file must
    be unchanged. Without atomic write, the target could be truncated
    or partially overwritten."""
    from forge.orchestrator.katas import atomic_write_json
    target = tmp_path / "katas.json"
    target.write_text(json.dumps({"original": True}), encoding="utf-8")

    # NaN/Infinity fail allow_nan=False
    bad = {"katas": [{"score": float("nan")}]}
    with pytest.raises(ValueError):
        atomic_write_json(target, bad)
    # Original must still be present, untouched.
    assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
    # And no orphaned .tmp file left around.
    tmp_artifact = target.with_suffix(".json.tmp")
    assert not tmp_artifact.exists()


def test_atomic_write_json_serializes_paths_via_default(tmp_path):
    """default=str catches Path objects. Without it, the call would
    raise TypeError after wiping the target."""
    from forge.orchestrator.katas import atomic_write_json
    target = tmp_path / "katas.json"
    p = Path("/some/path")
    atomic_write_json(target, {"path": p})
    data = json.loads(target.read_text(encoding="utf-8"))
    # Path serialized as string (POSIX-style on Unix, OS-native on Windows)
    assert isinstance(data["path"], str)


# ---------- BUG: generate_all clears stale __pycache__ ----------

def test_generate_all_clears_stale_pycache(tmp_path):
    """If a language directory has a leftover __pycache__ from a previous
    generation, generate_all must delete it. Otherwise Python's bytecode
    cache serves stale parser/codegen even after we overwrite the .py."""
    from forge.orchestrator.spec_builder import build_spec
    from forge.orchestrator.generator import generate_all

    # Pre-create a __pycache__ with a stale bytecode-ish file.
    target = tmp_path / "regenlang"
    target.mkdir()
    pycache = target / "__pycache__"
    pycache.mkdir()
    (pycache / "stale.pyc").write_bytes(b"# stale bytecode")
    assert pycache.exists()

    class FakeClient:
        log_dir = None
        def call_code(self, *a, **kw): return "# stub"
        def call_json(self, *a, **kw): return {"tests": []}
        def call_chat(self, *a, **kw): return "# stub"

    spec = build_spec({"syntax": "s_expression", "typing": "dynamic", "memory": "host_gc"},
                      "regenlang")
    generate_all(spec, output_root=tmp_path, client=FakeClient())

    # The stale __pycache__ must be gone (or recreated empty by import).
    # Either way, the stale .pyc file is gone.
    assert not (pycache / "stale.pyc").exists()


# ---------- PERF: Lark cache=True for toylang ----------

def test_toylang_parser_uses_lark_cache():
    """Verify the cache flag is set so subsequent subprocess spawns hit
    a pickled grammar instead of re-parsing the BNF every time."""
    src = (WORKSPACE_ROOT / "generated" / "toylang" / "parser.py").read_text(encoding="utf-8")
    assert "cache=True" in src, (
        "toylang's _PARSER should pass cache=True for fast subprocess spawn"
    )


def test_lisplang_parser_does_not_cache_earley():
    """Lisplang uses Earley because of if_stmt/if_expr ambiguity. Lark's
    cache=True is LALR-only; passing it would crash at import. Pin
    that lisplang DOES NOT have cache=True."""
    src = (WORKSPACE_ROOT / "generated" / "lisplang" / "parser.py").read_text(encoding="utf-8")
    # The earley parser definitely shouldn't have cache=True
    # (Lark raises ConfigurationError at import time if it does).
    if 'parser="earley"' in src:
        # Find the Lark(...) call and verify cache=True isn't in it.
        import re
        m = re.search(r"Lark\([^)]+\)", src, re.DOTALL)
        assert m is not None
        assert "cache=True" not in m.group(0), (
            "Earley parser cannot use cache=True (Lark ConfigurationError)"
        )


# ---------- PERF: standalone REPL caches by mtime ----------

def test_standalone_repl_returns_cached_when_unchanged(tmp_path, monkeypatch):
    """Second hit on /api/standalone/<lang> must NOT re-render when
    nothing changed. This is the single biggest "Try in browser" UX
    speedup for clicks-in-quick-succession."""
    from forge.gui.app import create_app
    from forge.gui import app as app_module

    # Repoint WORKSPACE to a fresh dir with lisplang as a symlink/copy.
    real_workspace = WORKSPACE_ROOT
    fake_workspace = tmp_path
    (fake_workspace / "generated").mkdir()

    # Symlink the existing lisplang into the fake workspace so we hit
    # a real, complete language.
    fake_lispdir = fake_workspace / "generated" / "lisplang"
    real_lispdir = real_workspace / "generated" / "lisplang"
    try:
        fake_lispdir.symlink_to(real_lispdir, target_is_directory=True)
    except (OSError, NotImplementedError):
        # Fallback: copy the relevant files
        import shutil as _sh
        _sh.copytree(real_lispdir, fake_lispdir,
                     ignore=_sh.ignore_patterns(".forge_log", "_playground", "__pycache__"))

    monkeypatch.setattr(app_module, "WORKSPACE", fake_workspace)

    app = create_app()
    client = app.test_client()

    # Clear any pre-existing repl.html
    repl = fake_lispdir / "repl.html"
    if repl.exists():
        repl.unlink()

    r1 = client.get("/api/standalone/lisplang")
    assert r1.status_code == 200
    first_mtime = repl.stat().st_mtime

    # Second hit should find repl.html newer than every source file →
    # not re-render. Confirm by checking mtime stays the same.
    import time
    time.sleep(0.05)   # ensure clock advances if a re-render happens
    r2 = client.get("/api/standalone/lisplang")
    assert r2.status_code == 200
    second_mtime = repl.stat().st_mtime
    assert first_mtime == second_mtime, (
        "second hit re-rendered repl.html unnecessarily (mtime changed)"
    )


# ---------- BUG: SSE stream emits synthetic done on silent worker crash ----------

def test_sse_stream_emits_done_when_worker_crashed():
    """If the worker thread dies without emitting 'done', the stream
    must still terminate the connection AND send a synthetic done frame
    so the GUI stops spinning."""
    from forge.gui.app import create_app, register_job, Job

    app = create_app()
    client = app.test_client()
    j = Job(opts={"syntax": "c_like", "typing": "dynamic", "memory": "host_gc"},
            name="crashed_job", provider=None)
    j.error = "simulated crash"
    j.done = True   # worker exited but never emit'd 'done'
    register_job(j)

    r = client.get(f"/api/stream/{j.id}", buffered=False)
    body = r.get_data(as_text=True)
    assert "kind" in body and "done" in body, body
    assert "simulated crash" in body or "exited" in body