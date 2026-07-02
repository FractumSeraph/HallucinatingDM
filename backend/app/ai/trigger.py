"""Bridges player messages to the AI DM. Real agent loop lands in Phase 4."""

from app.models import Message, Scene


async def maybe_trigger_ai_turn(scene: Scene, message: Message) -> None:
    if scene.dm_mode not in ("ai", "copilot", "assist"):
        return
    if message.author_type not in ("player", "dm"):
        return
    if message.kind == "ooc":
        return
    # Phase 4 wires this to the agent loop.
