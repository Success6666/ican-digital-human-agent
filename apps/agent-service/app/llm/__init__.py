"""LLM ports and the optional OpenAI-compatible adapter."""

from .client import LlmClient, OpenAICompatibleLlm

__all__ = ["LlmClient", "OpenAICompatibleLlm"]
