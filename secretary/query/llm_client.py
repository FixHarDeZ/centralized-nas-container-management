import os
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

import nous_auth

_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

_anthropic_client: AsyncAnthropic | None = None
_openrouter_client: AsyncOpenAI | None = None
_nous_client: AsyncOpenAI | None = None
_nous_token: str = ""


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


async def _get_nous() -> AsyncOpenAI:
    global _nous_client, _nous_token
    token = await nous_auth.token_manager.get_access_token()
    if _nous_client is None or token != _nous_token:
        _nous_client = AsyncOpenAI(
            base_url="https://inference-api.nousresearch.com/v1",
            api_key=token,
        )
        _nous_token = token
    return _nous_client


def _text_from_openai(resp, provider: str) -> str:
    if not resp.choices:
        raise RuntimeError(f"{provider} returned no choices")
    return resp.choices[0].message.content or ""


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

    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    if _PROVIDER == "openrouter":
        client = _get_openrouter()
        model = os.environ["OPENROUTER_MODEL"]
        resp = await client.chat.completions.create(model=model, messages=messages)
        return _text_from_openai(resp, "OpenRouter")

    if _PROVIDER == "nous":
        client = await _get_nous()
        model = os.getenv("NOUS_MODEL", "Hermes-4-70B")
        resp = await client.chat.completions.create(model=model, messages=messages)
        return _text_from_openai(resp, "Nous")

    raise ValueError(f"Unknown LLM_PROVIDER: {_PROVIDER!r}")
