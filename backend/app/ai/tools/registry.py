"""Tool registry: Pydantic schemas → OpenAI tool JSON, validated dispatch.

Handlers are the same functions the REST API uses (services/bookkeeping.py),
so a human clicking a button and the AI calling a tool mutate state through
one audited code path.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, Scene

log = logging.getLogger("hallucinatingdm.tools")


@dataclass
class ToolContext:
    db: AsyncSession
    campaign: Campaign
    scene: Scene
    ai_turn_id: str | None = None
    actor: str = "ai"  # ai | dm
    # Filled by handlers that mutate state: [{"kind","id","field","old"}...]
    inverse_patches: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    # Optional short line shown to players as a chip ("Goblin takes 5 damage")
    public_note: str = ""

    def for_llm(self) -> dict[str, Any]:
        if self.ok:
            return {"ok": True, **self.data}
        return {"ok": False, "error": self.error}


Handler = Callable[[ToolContext, Any], Awaitable[ToolResult]]


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler
    mutating: bool = False
    # Gated tools require DM approval in copilot mode.
    gated: bool = False


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def resolve_name(self, name: str) -> str | None:
        """Exact match, else a forgiving fuzzy match for small-model typos."""
        if name in self._tools:
            return name
        lowered = name.lower().strip()
        if lowered in self._tools:
            return lowered
        from rapidfuzz import fuzz, process

        best = process.extractOne(
            lowered, list(self._tools), scorer=fuzz.ratio, score_cutoff=85
        )
        return best[0] if best else None

    def openai_schemas(self) -> list[dict[str, Any]]:
        out = []
        for spec in self._tools.values():
            schema = spec.args_model.model_json_schema()
            schema.pop("title", None)
            for prop in schema.get("properties", {}).values():
                prop.pop("title", None)
            out.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": schema,
                    },
                }
            )
        return out

    async def dispatch(
        self, ctx: ToolContext, name: str, arguments: dict[str, Any]
    ) -> ToolResult:
        resolved = self.resolve_name(name)
        if not resolved:
            return ToolResult(
                ok=False,
                error=f"Unknown tool '{name}'. Available: {', '.join(self._tools)}",
            )
        spec = self._tools[resolved]
        try:
            args = spec.args_model.model_validate(arguments)
        except ValidationError as e:
            issues = "; ".join(
                f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
            )
            return ToolResult(ok=False, error=f"Invalid arguments for {resolved}: {issues}")
        try:
            return await spec.handler(ctx, args)
        except Exception:
            log.exception("tool %s failed", resolved)
            return ToolResult(ok=False, error=f"Tool {resolved} failed internally")


registry = ToolRegistry()


def tool(
    name: str,
    description: str,
    args_model: type[BaseModel],
    mutating: bool = False,
    gated: bool = False,
) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        registry.register(
            ToolSpec(
                name=name,
                description=description,
                args_model=args_model,
                handler=fn,
                mutating=mutating,
                gated=gated,
            )
        )
        return fn

    return decorator
