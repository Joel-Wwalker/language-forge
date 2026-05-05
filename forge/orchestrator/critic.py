"""AI language critic.

Roadmap §4.6. After a language generates, ask the LLM to review it as
a designer would: elegance, footguns, missing pieces, unintended
interactions. Save as `<lang>/REVIEW.md`.

Why this is in the project: most generated languages have real
problems (LLM hallucinations, contradicting axes, missing-by-omission
features). The user benefits from a candid second pass that names
what's wrong instead of celebrating what's there. Also gives each
language a piece of personality (it's reviewed; it has stakes).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .llm_client import LLMClient
from .generator import _load_prompt, _interp


def critique_language(spec: dict, lang_dir: Path,
                      client: LLMClient) -> Optional[str]:
    """Generate a Markdown review of the language. Writes to
    `<lang>/REVIEW.md` and returns the text. Returns None on LLM failure.

    The review uses `client.call_code` (not call_json) because the output
    is freeform Markdown, not structured. We tag the call so it shows up
    distinctly in the per-language `.forge_log/`.
    """
    prompt = _interp(_load_prompt("critic"), spec)
    try:
        review = client.call_code(prompt, tag="critic")
    except Exception as e:
        return None
    if not review or len(review.strip()) < 50:
        return None
    # Strip any leading/trailing fences the model might have added.
    review = review.strip()
    if review.startswith("```"):
        # Drop the first line (the opening fence) and any trailing fence.
        lines = review.splitlines()
        lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        review = "\n".join(lines).strip()
    review_path = lang_dir / "REVIEW.md"
    review_path.write_text(review + "\n", encoding="utf-8")
    return review
