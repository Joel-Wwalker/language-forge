"""Stage 2: Design Resolver.

LLM call. Takes the base spec produced by the spec builder and:
  - Fills in any auto/null fields the spec_builder couldn't decide.
  - Adds `design_notes` explaining each non-trivial choice (especially for
    incoherent combos like static + python_like).
  - Returns a structured spec validated against the schema.

The LLM is constrained via tool-use (`call_json`) to produce a JSON object
matching the language_spec.schema.json. On schema validation failure the
client retries once with the schema error appended (handled in llm_client).
"""
from __future__ import annotations

import json
from pathlib import Path

from .llm_client import LLMClient
from .personas import persona_block
from .spec_builder import load_schema, validate_spec


_PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "resolver.md"


def resolve(base_spec: dict, *, client: LLMClient) -> dict:
    schema = load_schema()
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.replace("{{BASE_SPEC}}", json.dumps(base_spec, indent=2))

    cust = base_spec.get("customization") or {}

    # Designer persona block (S10): prepended so it frames the whole task.
    pblock = persona_block(cust.get("persona"))
    if pblock:
        prompt = pblock + "\n\n---\n\n" + prompt

    # Hostile constraints (S10): surfaced as a high-priority ask.
    hc = cust.get("hostile_constraints")
    if hc:
        prompt += (
            "\n\n## User constraints (free-form, HIGH PRIORITY)\n\n"
            f"{hc}\n\n"
            "Honor every constraint where physically possible. For any "
            "constraint you cannot honor, add a `design_notes` entry "
            "explaining why and what you did instead."
        )

    resolved = client.call_json(prompt, schema, tag="resolver")
    # Customization fields are user-side: re-attach if the LLM stripped them.
    if cust and "customization" not in resolved:
        resolved["customization"] = cust
    elif cust:
        # Merge: LLM's customization wins on overlap, but our passthrough
        # fields (persona/era/etc.) must persist.
        merged = dict(cust)
        merged.update(resolved.get("customization") or {})
        resolved["customization"] = merged
    validate_spec(resolved)
    return resolved
