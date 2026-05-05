"""Regression test for `_json` NameError in claude_cli call_json.

Bug: an earlier change added `schema_str = _json.dumps(schema, indent=2)`
to `call_json`, but `_json` was only imported as a LOCAL alias inside
`call_chat()`. When the resolver (or any JSON-mode caller using the
claude CLI provider) hit `call_json`, it crashed with:

    NameError: name '_json' is not defined

This broke ANY language generation on the claude_cli provider path
(the resolver makes the first call_json call). The fix: use the
module-level `import json` already present at the top of the file.

The test exercises call_json with a stubbed `_invoke` so we don't need
the actual claude CLI installed. We give the stub a valid JSON response
and confirm call_json returns the parsed dict without NameError.
"""
from __future__ import annotations

import json

import pytest


def test_call_json_does_not_raise_nameerror_on_schema_stringification():
    """Direct regression test: call_json must not crash with NameError
    when stringifying the schema for the system message."""
    from forge.orchestrator.llm_client_claude_cli import ClaudeCLIClient

    # Skip the constructor's CLI-detection by instantiating directly
    # and overriding `_invoke` to avoid spawning a subprocess.
    client = ClaudeCLIClient.__new__(ClaudeCLIClient)
    client.binary = "claude"
    client.model = "claude-3-5-sonnet-20241022"
    client.max_tokens = 4096
    client.log_dir = None

    # Stub _invoke to return a valid JSON object (the lang resolver
    # gets a spec back as a JSON object).
    def _stub_invoke(prompt, system=None):
        return '```json\n{"lang_name": "test"}\n```'
    client._invoke = _stub_invoke

    schema = {
        "type": "object",
        "required": ["lang_name"],
        "properties": {"lang_name": {"type": "string"}},
    }
    # Before the fix, this raised NameError before any call to _invoke.
    # After the fix, it returns the parsed dict.
    result = client.call_json("hello", schema, max_retries=0)
    assert result == {"lang_name": "test"}


def test_call_json_includes_schema_in_system_message():
    """The fix preserves the schema-in-system-message behavior. Verify
    the stringified schema reaches the system message (so the LLM sees
    enum values and field names verbatim)."""
    from forge.orchestrator.llm_client_claude_cli import ClaudeCLIClient

    client = ClaudeCLIClient.__new__(ClaudeCLIClient)
    client.binary = "claude"
    client.model = "claude-3-5-sonnet-20241022"
    client.max_tokens = 4096
    client.log_dir = None

    captured_system = []
    def _stub_invoke(prompt, system=None):
        captured_system.append(system)
        return '```json\n{"x": 1}\n```'
    client._invoke = _stub_invoke

    schema = {
        "type": "object",
        "required": ["x"],
        "properties": {"x": {"type": "integer", "enum": [1, 2, 3]}},
    }
    client.call_json("test", schema, max_retries=0)

    assert captured_system, "system message should have been captured"
    sys_msg = captured_system[0]
    # The schema's enum values must be visible in the system message
    # (so the LLM can't claim it didn't know).
    assert '"enum"' in sys_msg
    assert '1' in sys_msg and '2' in sys_msg and '3' in sys_msg


def test_module_does_not_reference_undefined_json_alias():
    """Hard guard: scan the module for any `_json.` reference outside
    the local-import scope of call_chat. Any future re-introduction
    of the bug fails this test before the user hits it.

    Match `_json.` and `_json,` and `_json )` etc. via a word-boundary
    regex so we don't accidentally flag `call_json` (substring match)."""
    import re
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] /
           "forge" / "orchestrator" / "llm_client_claude_cli.py").read_text(encoding="utf-8")
    lines = src.splitlines()
    in_call_chat = False
    call_chat_indent = None
    # Pattern: `_json` as a whole token (not part of `call_json` etc.)
    bad = re.compile(r"(?<![A-Za-z0-9_])_json(?![A-Za-z0-9_])")
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("def call_chat"):
            in_call_chat = True
            call_chat_indent = len(line) - len(stripped)
            continue
        if in_call_chat:
            if stripped.startswith("def ") and (len(line) - len(stripped)) <= call_chat_indent:
                in_call_chat = False
            elif line.strip() and not line.startswith(" "):
                in_call_chat = False
        if in_call_chat:
            continue
        # Skip comment-only lines (explaining-the-bug docstring text
        # references `_json` for context but isn't an actual reference).
        if stripped.startswith("#"):
            continue
        if bad.search(line) and "import json as _json" not in line:
            pytest.fail(
                f"Line {i}: `_json` referenced outside call_chat scope.\n"
                f"  {line.rstrip()}\n"
                f"Use the module-level `json` import instead."
            )
