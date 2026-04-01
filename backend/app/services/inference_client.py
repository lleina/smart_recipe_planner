"""
Model-agnostic inference client for OpenAI-compatible LLM / VLM backends.

Two interfaces are provided:

``get_client(base_url, api_key)``
    Returns a standard ``AsyncOpenAI`` client. Use this for non-Ollama
    backends (vLLM, LMDeploy, LocalAI, TGI) that fully honour the OpenAI API.

``ollama_chat(base_url, model, messages, ...)``
    Calls Ollama's **native** ``/api/chat`` endpoint directly. This is
    required instead of the OpenAI-compatible ``/v1`` endpoint because:

    1. The ``think: false`` option is only honoured by the native endpoint.
       Without it, thinking models (qwen3, deepseek-r1) spend all tokens on
       internal reasoning and return an empty content field.
    2. Images are passed via the native ``images`` field (base64 list), which
       is more reliable than OpenAI-style ``image_url`` content blocks for
       local vision models.

Supported backends:
    Ollama:   ``base_url="http://localhost:11434/v1"``, ``api_key="ollama"``
    vLLM:     ``base_url="http://localhost:8001/v1"``,  ``api_key="EMPTY"``
    LMDeploy: ``base_url="http://localhost:23333/v1"``, ``api_key="EMPTY"``
    LocalAI:  ``base_url="http://localhost:8080/v1"``,  ``api_key="localai"``
    TGI:      ``base_url="http://localhost:8080/v1"``,  ``api_key="EMPTY"``
"""

import asyncio
import heapq
import itertools
from dataclasses import dataclass, field
from typing import Literal

import httpx
from openai import AsyncOpenAI


@dataclass(order=True)
class _QueuedOllamaCall:
    """Internal priority-queue item for serialized Ollama scheduling."""

    priority: int
    sequence: int
    token: object = field(compare=False)


_ollama_queue_condition = asyncio.Condition()
_ollama_queue: list[_QueuedOllamaCall] = []
_ollama_sequence = itertools.count()
_ollama_call_active = False


async def _acquire_ollama_turn(priority: Literal["high", "normal"]) -> None:
    """Block until this call reaches the front of the priority queue."""
    queue_priority = 0 if priority == "high" else 1
    request = _QueuedOllamaCall(
        priority=queue_priority,
        sequence=next(_ollama_sequence),
        token=object(),
    )

    global _ollama_call_active
    async with _ollama_queue_condition:
        heapq.heappush(_ollama_queue, request)
        while True:
            is_next = bool(_ollama_queue) and (_ollama_queue[0].token is request.token)
            if is_next and not _ollama_call_active:
                heapq.heappop(_ollama_queue)
                _ollama_call_active = True
                return
            await _ollama_queue_condition.wait()


async def _release_ollama_turn() -> None:
    """Release the active Ollama slot and wake queued callers."""
    global _ollama_call_active
    async with _ollama_queue_condition:
        _ollama_call_active = False
        _ollama_queue_condition.notify_all()


def get_client(base_url: str, api_key: str = "local") -> AsyncOpenAI:
    """Return an ``AsyncOpenAI`` client configured for the given base URL.

    The ``api_key`` is required by the ``openai`` package but is ignored by
    all self-hosted backends — any non-empty string works.

    Args:
        base_url: Full base URL of the OpenAI-compatible server,
            e.g. ``"http://localhost:11434/v1"``.
        api_key: API key string (required by openai SDK; ignored locally).

    Returns:
        An ``AsyncOpenAI`` client ready for chat completions and embeddings.
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
    priority: Literal["high", "normal"] = "normal",
) -> str:
    """Call Ollama's native ``/api/chat`` endpoint and return the response text.

    Unlike the OpenAI-compatible ``/v1/chat/completions`` endpoint, the native
    endpoint honours the ``think`` parameter, allowing reasoning mode to be
    disabled for structured-output tasks (recipe ideation, re-ranking) where
    thinking tokens produce no useful content.

    Args:
        base_url: Ollama endpoint URL — may include a ``/v1`` suffix (stripped
            internally), e.g. ``"http://localhost:11434/v1"``.
        model: Model name as registered in Ollama, e.g. ``"qwen3:4b"``.
        messages: List of ``{"role": ..., "content": ...}`` message dicts.
            For vision requests, include ``"images": [<base64_str>, ...]``.
        max_tokens: Maximum tokens to generate (mapped to ``num_predict``).
        temperature: Sampling temperature (higher = more creative).
        timeout: HTTP request timeout in seconds.
        think: Whether to enable chain-of-thought reasoning. ``False``
            suppresses thinking and populates ``content`` immediately.
        priority: Scheduler priority for local contention. ``"high"`` jumps
            ahead of queued ``"normal"`` calls.

    Returns:
        The assistant's response content string.

    Raises:
        httpx.TimeoutException: If the request exceeds ``timeout`` seconds.
        httpx.HTTPStatusError: If Ollama returns a non-2xx HTTP status.
        ValueError: If the response contains an empty or missing content field.
    """
    # Strip the /v1 suffix if present — the native /api/chat lives at the root.
    ollama_root = base_url.rstrip("/")
    if ollama_root.endswith("/v1"):
        ollama_root = ollama_root[:-3]

    request_payload = {
        "model": model,
        "messages": messages,
        "think": think,
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": temperature,
        },
    }

    await _acquire_ollama_turn(priority)
    try:
        async with httpx.AsyncClient(timeout=timeout) as http_client:
            response = await http_client.post(
                f"{ollama_root}/api/chat", json=request_payload
            )
            response.raise_for_status()
            response_data = response.json()
    finally:
        await _release_ollama_turn()

    assistant_content: str = response_data.get("message", {}).get("content", "") or ""
    if not assistant_content.strip():
        raise ValueError(
            f"Ollama returned empty content for model {model!r}. "
            "The model may be warming up or thinking mode may be suppressing output."
        )
    return assistant_content
