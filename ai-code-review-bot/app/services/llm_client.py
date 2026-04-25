"""
LLM Client — model-agnostic abstraction layer.

Supports:
  - OpenAI (gpt-4o, gpt-4-turbo, etc.)
  - Anthropic (claude-3-5-sonnet, claude-opus, etc.)
  - Azure OpenAI
  - Ollama (local models)

To switch providers: change LLM_PROVIDER + LLM_MODEL in .env.
No application code changes required.
"""

import json
import logging
from typing import Any

from app.core.config import settings
from app.models.review import ReviewResult

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified LLM interface. All providers implement the same call signature."""

    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self.model = settings.LLM_MODEL
        self._client = self._build_client()

    def _build_client(self) -> Any:
        if self.provider == "openai":
            try:
                from openai import AsyncOpenAI
                return AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            except ImportError:
                raise RuntimeError("Install openai: pip install openai")

        elif self.provider == "anthropic":
            try:
                import anthropic
                return anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
            except ImportError:
                raise RuntimeError("Install anthropic: pip install anthropic")

        elif self.provider == "azure_openai":
            try:
                from openai import AsyncAzureOpenAI
                return AsyncAzureOpenAI(
                    api_key=settings.AZURE_OPENAI_API_KEY,
                    azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                    api_version="2024-02-01",
                )
            except ImportError:
                raise RuntimeError("Install openai: pip install openai")

        elif self.provider == "ollama":
            # Ollama exposes OpenAI-compatible API
            try:
                from openai import AsyncOpenAI
                return AsyncOpenAI(
                    base_url=f"{settings.OLLAMA_BASE_URL}/v1",
                    api_key="ollama",
                )
            except ImportError:
                raise RuntimeError("Install openai: pip install openai")

        else:
            raise ValueError(f"Unsupported LLM provider: {self.provider}")

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Send a completion request. Returns raw text response."""
        logger.debug(f"Sending request to {self.provider}/{self.model}")

        if self.provider == "anthropic":
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text

        else:
            # OpenAI-compatible (openai, azure_openai, ollama)
            model_name = settings.AZURE_OPENAI_DEPLOYMENT or self.model
            response = await self._client.chat.completions.create(
                model=model_name,
                max_tokens=settings.LLM_MAX_TOKENS,
                temperature=settings.LLM_TEMPERATURE,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
            return response.choices[0].message.content

    async def complete_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Complete and parse JSON response. Strips markdown fences if present."""
        raw = await self.complete(system_prompt, user_prompt)
        # Strip markdown code fences if model wraps output
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            # Remove first and last fence lines
            cleaned = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM JSON response: {e}\nRaw: {raw[:500]}")
            raise ValueError(f"LLM returned invalid JSON: {e}")


# Singleton instance
_llm_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
