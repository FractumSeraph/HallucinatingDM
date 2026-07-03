"""Bridges player messages to the AI DM agent loop."""

from app.models import Message, Scene


async def maybe_trigger_ai_turn(scene: Scene, message: Message) -> None:
    if scene.dm_mode not in ("ai", "copilot", "assist"):
        return
    if message.author_type not in ("player", "dm"):
        return
    if message.kind in ("ooc", "whisper"):
        return

    from app.ai.dm_agent import trigger_turn

    trigger_turn(scene.id)
