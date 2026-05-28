import os
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI


_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

_anthropic_client: AsyncAnthropic | None = None
_openai_client: AsyncOpenAI | None = None


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


def _get_openai(base_url: str, api_key: str) -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    return _openai_client


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
        client = _get_openai(
            base_url=os.environ["OPENROUTER_BASE_URL"],
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
        model = os.environ["OPENROUTER_MODEL"]
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    if _PROVIDER == "norus":
        client = _get_openai(
            base_url=os.environ["NORUS_BASE_URL"],
            api_key=os.environ["NORUS_API_KEY"],
        )
        model = os.environ["NORUS_MODEL"]
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    raise ValueError(f"Unknown LLM_PROVIDER: {_PROVIDER!r}")
