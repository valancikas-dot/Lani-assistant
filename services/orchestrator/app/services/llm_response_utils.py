from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast


def extract_openai_message_text(response: Any) -> str:
    """Extract assistant text from an OpenAI chat completion response."""
    choices = getattr(response, "choices", None)
    if not choices:
        return ""

    first_choice = choices[0]
    message = getattr(first_choice, "message", None)
    content = getattr(message, "content", "") if message is not None else ""
    if isinstance(content, str):
        return content.strip()
    return ""


def extract_anthropic_text(response: Any) -> str:
    """Extract first available text block from an Anthropic messages response."""
    content = cast(Sequence[Any], getattr(response, "content", ()) or ())
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""