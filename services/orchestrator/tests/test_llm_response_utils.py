from __future__ import annotations

from types import SimpleNamespace

from app.services.llm_response_utils import extract_anthropic_text, extract_openai_message_text


def test_extract_openai_message_text_strips_content() -> None:
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="  Hello world  "))]
    )

    assert extract_openai_message_text(response) == "Hello world"


def test_extract_openai_message_text_handles_missing_content() -> None:
    response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])

    assert extract_openai_message_text(response) == ""


def test_extract_anthropic_text_skips_non_text_blocks() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use"),
            SimpleNamespace(text="  Anthropic reply  "),
        ]
    )

    assert extract_anthropic_text(response) == "Anthropic reply"


def test_extract_anthropic_text_handles_empty_content() -> None:
    response = SimpleNamespace(content=[])

    assert extract_anthropic_text(response) == ""


def test_extract_anthropic_text_returns_first_non_empty_text_block() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(text="   "),
            SimpleNamespace(text="First useful block"),
            SimpleNamespace(text="Second block"),
        ]
    )

    assert extract_anthropic_text(response) == "First useful block"


def test_extract_openai_message_text_handles_missing_choices() -> None:
    response = SimpleNamespace(choices=[])

    assert extract_openai_message_text(response) == ""