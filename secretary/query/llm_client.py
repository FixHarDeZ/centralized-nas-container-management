import os
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI


_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

_anthropic_client: AsyncAnthropic | None = None
_openrouter_client: AsyncOpenAI | None = None


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


def _get_openrouter() -> AsyncOpenAI:
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = AsyncOpenAI(
            base_url=os.environ["OPENROUTER_BASE_URL"],
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
    return _openrouter_client


async def get_llm_response(system: str, user: str) -> str:
    if _PROVIDER == "anthropic":
        client = _get_anthropic()
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        msg = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    if _PROVIDER == "openrouter":
        client = _get_openrouter()
        model = os.environ["OPENROUTER_MODEL"]
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if not resp.choices:
            error_detail = getattr(resp, "error", None) or "null choices"
            raise RuntimeError(f"OpenRouter returned no choices: {error_detail}")
        return resp.choices[0].message.content or ""

    raise ValueError(f"Unknown LLM_PROVIDER: {_PROVIDER!r}")
