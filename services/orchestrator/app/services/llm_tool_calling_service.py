from __future__ import annotations

from typing import Any, Optional, cast


async def create_tool_choice(
    *,
    openai_api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    tool_choice: str = "auto",
    temperature: Optional[float] = None,
) -> Any:
    """Create an OpenAI chat completion configured for tool/function calling."""
    if not openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    import openai

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": cast(Any, messages),
        "tools": cast(Any, tools),
        "tool_choice": tool_choice,
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    return await client.chat.completions.create(**kwargs)