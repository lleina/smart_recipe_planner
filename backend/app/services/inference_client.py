"""
Model-agnostic inference client.

Returns an AsyncOpenAI client pointed at any OpenAI-compatible endpoint.
Supported backends (set via config):
  - Ollama:     base_url="http://localhost:11434/v1",  api_key="ollama"
  - vLLM:       base_url="http://localhost:8001/v1",   api_key="EMPTY"
  - LMDeploy:   base_url="http://localhost:23333/v1",  api_key="EMPTY"
  - LocalAI:    base_url="http://localhost:8080/v1",   api_key="localai"
  - TGI:        base_url="http://localhost:8080/v1",   api_key="EMPTY"

The api_key is required by the openai package but ignored by local servers;
any non-empty string works.

For Ollama thinking models (qwen3.5, qwen3, deepseek-r1, etc.) the OpenAI-
compatible /v1 endpoint does not honour the `think: false` parameter, causing
all tokens to be consumed by internal reasoning with an empty content field.
Use `ollama_chat()` instead, which calls the native /api/chat endpoint and
passes `think: false` to suppress reasoning mode entirely.
"""

import httpx
from openai import AsyncOpenAI


def get_client(base_url: str, api_key: str = "local") -> AsyncOpenAI:
    """
    Returns an AsyncOpenAI client configured for the given base URL.

    :param base_url: Full base URL of the OpenAI-compatible server,
                     e.g. "http://localhost:11434/v1"
    :param api_key:  API key string. Ignored by local servers but required
                     by the openai package. Default "local" works for all
                     self-hosted backends.
    :returns: Configured AsyncOpenAI client.
    """
    return AsyncOpenAI(base_url=base_url, api_key=api_key)


async def ollama_chat(
    base_url: str,
    model: str,
    messages: list[dict],
    max_tokens: int = 8192,
    temperature: float = 0.7,
    timeout: float = 120.0,
    think: bool = False,
) -> str:
    """
    Call Ollama's native /api/chat endpoint directly.

    Unlike the OpenAI-compatible /v1 endpoint, this honours the `think`
    parameter, allowing thinking mode to be disabled for structured output
    tasks (recipe ideation, re-ranking) where reasoning wastes all tokens.

    :param base_url:    Ollama base URL including /v1 suffix (stripped here),
                        e.g. "http://localhost:11434/v1" → "http://localhost:11434"
    :param model:       Model name as registered in Ollama, e.g. "qwen3.5:4b"
    :param messages:    List of {"role": …, "content": …} dicts.
    :param max_tokens:  Maximum tokens to generate (mapped to num_predict).
    :param temperature: Sampling temperature.
    :param timeout:     HTTP request timeout in seconds.
    :param think:       Whether to enable chain-of-thought reasoning.
                        False = no thinking, content populated immediately.
    :returns: The assistant message content string.
    :raises httpx.TimeoutException: If the request exceeds `timeout`.
    :raises ValueError: If the response contains no content.
    """
    # Strip /v1 suffix to get the Ollama server root
    ollama_root = base_url.rstrip("/")
    if ollama_root.endswith("/v1"):
        ollama_root = ollama_root[:-3]

    payload = {
        "model": model,
        "messages": messages,
        "think": think,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{ollama_root}/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

    content = data.get("message", {}).get("content", "") or ""
    if not content.strip():
        raise ValueError(f"Ollama returned empty content for model {model!r}")
    return content
