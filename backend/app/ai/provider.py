"""Provider-agnostic LLM client.

Everything speaks the OpenAI chat-completions dialect (Ollama >=0.3 /v1,
OpenAI, LM Studio, vLLM, OpenRouter, Anthropic-compatible gateways), so the
only real implementation is a thin adapter over the openai SDK pointed at a
configurable base_url. A scripted MockProvider ships for tests/demo mode.
"""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger("landl.llm")


@dataclass
class TextDelta:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Done:
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)


LLMEvent = TextDelta | ToolCall | Done


@dataclass
class LLMConfig:
    provider: str = "openai_compat"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    model: str = "qwen3.6:35b-a3b"
    toolcall_mode: str = "auto"  # native | prompted | auto
    embedding_base_url: str = "http://localhost:11434/v1"
    embedding_api_key: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    temperature: float = 0.8
    max_tokens: int = 1024


class LLMProvider(Protocol):
    config: LLMConfig

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LLMEvent]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenAICompatProvider:
    def __init__(self, config: LLMConfig):
        from openai import AsyncOpenAI

        self.config = config
        self._client = AsyncOpenAI(base_url=config.base_url, api_key=config.api_key or "none")
        self._embed_client = AsyncOpenAI(
            base_url=config.embedding_base_url,
            api_key=config.embedding_api_key or "none",
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LLMEvent]:
        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.config.temperature,
            "max_tokens": max_tokens or self.config.max_tokens,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools

        stream = await self._client.chat.completions.create(**kwargs)

        # Accumulate streamed tool-call fragments by index.
        pending: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        usage: dict[str, int] = {}

        async for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = {
                    "prompt_tokens": chunk.usage.prompt_tokens or 0,
                    "completion_tokens": chunk.usage.completion_tokens or 0,
                }
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if delta and delta.content:
                yield TextDelta(delta.content)
            if delta and delta.tool_calls:
                for tc in delta.tool_calls:
                    slot = pending.setdefault(
                        tc.index, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.id:
                        slot["id"] = tc.id
                    if tc.function and tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        slot["arguments"] += tc.function.arguments
            if choice.finish_reason:
                finish_reason = choice.finish_reason

        for index in sorted(pending):
            slot = pending[index]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"].strip() else {}
            except json.JSONDecodeError:
                from app.ai.toolcall_fallback import repair_json

                args = repair_json(slot["arguments"]) or {}
            yield ToolCall(
                id=slot["id"] or f"call_{index}", name=slot["name"], arguments=args
            )

        yield Done(finish_reason=finish_reason, usage=usage)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # nomic-embed-text expects task prefixes; harmless for other models
        # to receive raw text, so only documents get prefixed by callers.
        resp = await self._embed_client.embeddings.create(
            model=self.config.embedding_model, input=texts
        )
        return [item.embedding for item in resp.data]


_provider: LLMProvider | None = None


async def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        from app.services.settings_service import load_llm_config

        config = await load_llm_config()
        if config.provider == "mock":
            from app.ai.mock_provider import MockProvider

            _provider = MockProvider(config)
        else:
            _provider = OpenAICompatProvider(config)
    return _provider


def set_provider(provider: LLMProvider | None) -> None:
    """Swap the provider (admin settings change, tests)."""
    global _provider
    _provider = provider
