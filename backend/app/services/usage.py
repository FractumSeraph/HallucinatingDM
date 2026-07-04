"""Per-campaign LLM token usage — aggregated from the per-turn traces that
run_turn already records (AiTurn.token_usage_json), joined through scenes."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiTurn, Scene


async def campaign_usage(db: AsyncSession, campaign_id: str) -> dict[str, int]:
    """Total prompt/completion tokens (and turn count) spent by a campaign."""
    rows = (
        await db.execute(
            select(AiTurn.token_usage_json)
            .join(Scene, Scene.id == AiTurn.scene_id)
            .where(Scene.campaign_id == campaign_id)
        )
    ).scalars()
    prompt = completion = turns = 0
    for usage in rows:
        turns += 1
        prompt += int((usage or {}).get("prompt_tokens", 0))
        completion += int((usage or {}).get("completion_tokens", 0))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "turns": turns,
    }


def campaign_token_cap(campaign: Any) -> int | None:
    """The campaign's total-token cap, if the DM set one (>0)."""
    cap = ((getattr(campaign, "settings_json", None) or {}).get("llm") or {}).get("token_cap")
    try:
        cap = int(cap)
    except (TypeError, ValueError):
        return None
    return cap if cap > 0 else None
