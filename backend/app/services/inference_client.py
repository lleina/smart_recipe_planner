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
"""

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
