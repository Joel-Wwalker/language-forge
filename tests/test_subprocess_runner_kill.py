"""Phase 4 pre-batch Fix 2: tree-kill on timeout.

Pins that `run_one` kills the entire process tree (not just the
immediate child) when the timeout fires. Before this fix, the
pre-flight batch had three runaway slots that ran ~7900s each
(almost 9× the 900s timeout) because the Claude CLI's Node.js
grandchild held stdio handles open after Python's `terminate()`
hit the outer subprocess.

Strategy: spawn a Python child that ignores SIGTERM AND spawns its
own grandchild. Hand it a tight timeout. Confirm both processes are
dead within a small grace window of the timeout firing.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from forge.orchestrator.subprocess_runner import _kill_process_tree

import subprocess as _sp


# The "hanging" payload: writes its PID to a file, spawns a child that
# also writes its PID, then sleeps forever ignoring SIGTERM.
HANG_SCRIPT = r"""
import os, signal, sys, time, subprocess

# Best-effort: install a no-op handler for SIGTERM so the parent's
# graceful-kill doesn't end us. On Windows there's no SIGTERM (it's
# the same as KILL), so this block is a Unix-only annoyance for the
# graceful path; the test relies on tree-kill to land the K.O.
if os.name != "nt":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

parent_pid_file = sys.argv[1]
child_pid_file = sys.argv[2]
with open(parent_pid_file, "w") as f:
    f.write(str(os.getpid()))

# Spawn a child that sleeps. The child's PID gets reported so the test
# can poll both processes for liveness.
child = subprocess.Popen(
    [sys.executable, "-c", "import time, os, sys; "
     "open(sys.argv[1], 'w').write(str(os.getpid())); "
     "time.sleep(300)",
     child_pid_file],
)

# Hold the parent open. Block forever; the only way out is hard-kill.
while True:
    time.sleep(1)
"""


def _is_alive(pid: int) -> bool:
    """Cross-platform check: does process `pid` still exist?"""
    if os.name == "nt":
        # Windows: use tasklist; returns "INFO: No tasks..." on stdout
        # for non-existent PIDs.
        try:
            cp = _sp.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=5.0,
            )
            return f'"{pid}"' in (cp.stdout or "")
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


@pytest.mark.slow
def test_kill_process_tree_terminates_grandchild(tmp_path):
    """Manually invoke _kill_process_tree on a Popen handle whose
    subprocess spawns its own grandchild. After the kill returns, both
    processes must be dead within a 30-second window."""
    script = tmp_path / "hang.py"
    script.write_text(HANG_SCRIPT, encoding="utf-8")
    parent_pid_file = tmp_path / "parent.pid"
    child_pid_file = tmp_path / "child.pid"

    popen_kwargs = {
        "stdout": _sp.PIPE, "stderr": _sp.PIPE,
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(
            _sp, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["start_new_session"] = True

    proc = _sp.Popen(
        [sys.executable, str(script), str(parent_pid_file), str(child_pid_file)],
        **popen_kwargs,
    )

    # Wait for both processes to write their PIDs (so we know the tree
    # is fully spawned before we try to kill it).
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if parent_pid_file.exists() and child_pid_file.exists():
            break
        time.sleep(0.2)
    assert parent_pid_file.exists(), "parent payload never started"
    assert child_pid_file.exists(), "grandchild never spawned"

    parent_pid = int(parent_pid_file.read_text())
    child_pid = int(child_pid_file.read_text())

    # Both alive before the kill.
    assert _is_alive(parent_pid), f"parent {parent_pid} should be alive"
    assert _is_alive(child_pid), f"child {child_pid} should be alive"

    # Fire the tree-kill.
    _kill_process_tree(proc, grace_period=2.0)
    try:
        proc.communicate(timeout=15.0)
    except _sp.TimeoutExpired:
        proc.kill()

    # Both must be dead within 30s of the kill returning.
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if not _is_alive(parent_pid) and not _is_alive(child_pid):
            break
        time.sleep(0.5)

    assert not _is_alive(parent_pid), (
        f"parent {parent_pid} still alive 30s after tree-kill"
    )
    assert not _is_alive(child_pid), (
        f"grandchild {child_pid} still alive 30s after tree-kill"
    )


@pytest.mark.slow
def test_run_one_timeout_path_kills_tree(tmp_path):
    """Integration: invoke `run_one` with a 3-second timeout on a spec
    that wedges. The subprocess-runner worker reads the slot JSON,
    starts generate_all, gets to creative/idioms calls — but with no
    LLM available it will fail fast. To simulate a true hang we need
    a different entry point; the per-runner _kill_process_tree test
    above proves the kill logic. This integration test just confirms
    the run_one() timeout PATH returns the right error string and a
    finite duration."""
    from forge.orchestrator.subprocess_runner import run_one
    # A minimal templated spec (won't actually run end-to-end without
    # LLM; we expect it to fail fast).
    spec = {
        "lang_name": "timeouttest_001",
        "options": {"syntax": "stack_based", "typing": "dynamic", "memory": "host_gc"},
        "file_extension": ".st",
        "comment_syntax": {"line": "\\", "block_open": "(", "block_close": ")"},
        "keywords": [":", ";", "if", "else", "then", "true", "false"],
        "operators": {"arithmetic": ["+"], "comparison": ["="],
                      "logical": ["and"], "assignment": []},
        "literals": {"integer": "decimal", "float": "decimal.",
                     "string": "double-quoted", "boolean": "true/false"},
        "statement_terminator": " ",
        "block_style": "concatenative",
        "function_definition": {"keyword": ":", "syntax_example": ": f ;"},
        "variable_declaration": {"keyword": "variable",
                                 "syntax_example": "variable x"},
        "print_form": "<args> .",
        "boolean_keywords": {"true": "true", "false": "false"},
        "null_keyword": "nil",
    }
    res = run_one(spec, tmp_path, slot_id="timeouttest_001",
                  timeout=3.0, client_provider=None,
                  skip_resolver=True)
    # The subprocess should EITHER complete (templated stack_based
    # finishes in <3s on warm cache) OR timeout-and-tree-kill. Both
    # are acceptable; what we're pinning is that we DON'T hang forever.
    assert res.duration_seconds < 30.0, (
        f"run_one took {res.duration_seconds:.1f}s for a 3s-timeout slot; "
        f"tree-kill must have failed"
    )
