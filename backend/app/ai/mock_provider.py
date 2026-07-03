"""Scripted LLM provider for tests, CI, and demo mode (LLM_PROVIDER=mock).

A script is a list of turns; each turn is a list of LLMEvents to emit. Every
chat() call consumes the next turn and records what it was asked, so tests can
assert on the exact messages/tools the agent sent.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from app.ai.provider import Done, LLMConfig, LLMEvent, TextDelta


@dataclass
class RecordedCall:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None


@dataclass
class MockProvider:
    config: LLMConfig = field(default_factory=lambda: LLMConfig(provider="mock"))
    script: list[list[LLMEvent]] = field(default_factory=list)
    calls: list[RecordedCall] = field(default_factory=list)

    def queue_turn(self, events: list[LLMEvent]) -> None:
        self.script.append(events)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[LLMEvent]:
        self.calls.append(RecordedCall(messages=messages, tools=tools))
        if self.script:
            events = self.script.pop(0)
        else:
            events = [
                TextDelta("The mist thickens. (mock DM: no scripted response left)"),
                Done(),
            ]
        emitted_done = False
        for event in events:
            if isinstance(event, Done):
                emitted_done = True
            yield event
        if not emitted_done:
            yield Done()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Deterministic pseudo-embeddings: stable across runs, dimension 64.
        out = []
        for text in texts:
            seed = sum(ord(c) for c in text) or 1
            vec = [((seed * (i + 3) * 2654435761) % 1000) / 1000 - 0.5 for i in range(64)]
            out.append(vec)
        return out
