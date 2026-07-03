"""The agentic AI-DM turn loop.

One turn: build context → stream the LLM → execute tool calls inline
(broadcasting results live) → feed results back → repeat until a text-only
response (or the round cap). Per-scene locks serialize turns; every turn's
full trace persists to ai_turns.
"""

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from typing import Any

import app.ai.tools.core_tools  # noqa: F401  — register tools
import app.ai.tools.world_tools  # noqa: F401  — register tools
from app.ai.context_builder import build_messages
from app.ai.provider import Done, TextDelta, ToolCall, get_provider
from app.ai.toolcall_fallback import extract_tool_calls, render_tool_catalog
from app.ai.tools.registry import ToolContext, ToolResult, registry
from app.db import get_sessionmaker
from app.models import AiTurn, Campaign, Scene, ToolCallLog
from app.realtime import events
from app.realtime.hub import hub
from app.services.messages import create_message, message_out

log = logging.getLogger("hallucinatingdm.agent")


def held_for_approval_result(approval_id: str) -> ToolResult:
    """Stand-in result the LLM receives while the DM decides on a gated call."""
    return ToolResult(
        ok=True,
        data={
            "held_for_dm_approval": True,
            "approval_id": approval_id,
            "note": "The human DM must approve this action; narrate as if pending.",
        },
        public_note="⏳ Waiting on the DM's approval…",
    )

MAX_TOOL_ROUNDS = 8
COALESCE_SECONDS = 1.0

_scene_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_pending_scenes: set[str] = set()


def trigger_turn(scene_id: str) -> None:
    """Schedule an AI turn; bursts of messages coalesce into one turn."""
    if scene_id in _pending_scenes:
        return
    _pending_scenes.add(scene_id)
    asyncio.get_running_loop().create_task(_run_when_free(scene_id))


async def _run_when_free(scene_id: str) -> None:
    try:
        await asyncio.sleep(COALESCE_SECONDS)
        async with _scene_locks[scene_id]:
            _pending_scenes.discard(scene_id)
            await run_turn(scene_id)
    except Exception:
        _pending_scenes.discard(scene_id)
        log.exception("AI turn crashed (scene=%s)", scene_id)


def _status(campaign_id: str, scene_id: str, status: str) -> None:
    hub.broadcast(
        campaign_id,
        events.make_event(events.AI_STATUS, campaign_id, {"status": status}, scene_id),
        scene_id=scene_id,
    )


async def run_turn(scene_id: str) -> None:
    provider = await get_provider()
    use_native = provider.config.toolcall_mode in ("native", "auto")
    prompted = provider.config.toolcall_mode == "prompted"

    async with get_sessionmaker()() as db:
        scene = await db.get(Scene, scene_id)
        if not scene or scene.status == "archived":
            return
        campaign = await db.get(Campaign, scene.campaign_id)
        assert campaign

        turn = AiTurn(scene_id=scene_id, status="running", model=provider.config.model)
        db.add(turn)
        await db.commit()

        ctx = ToolContext(db=db, campaign=campaign, scene=scene, ai_turn_id=turn.id)
        steps: list[dict[str, Any]] = []
        usage_total = {"prompt_tokens": 0, "completion_tokens": 0}

        try:
            _status(campaign.id, scene_id, "The DM considers the scene…")
            catalog = render_tool_catalog(registry.openai_schemas()) if prompted else None
            messages = await build_messages(db, campaign, scene, catalog)
            tools = registry.openai_schemas() if use_native else None

            # Assist mode: narration is drafted privately for the DM to approve.
            assist = scene.dm_mode == "assist"

            for round_no in range(MAX_TOOL_ROUNDS):
                stream_id = f"{turn.id}-{round_no}"
                buffer = ""
                started = False
                native_calls: list[ToolCall] = []
                finish = "stop"

                async for event in provider.chat(messages, tools=tools):
                    if isinstance(event, TextDelta):
                        if not started:
                            started = True
                            hub.broadcast(
                                campaign.id,
                                events.make_event(
                                    events.STREAM_START, campaign.id,
                                    {"stream_id": stream_id, "draft": assist}, scene_id,
                                ),
                                scene_id=scene_id,
                                dm_only=assist,
                            )
                        buffer += event.text
                        # In prompted mode, hold back once a tool fence opens.
                        visible_delta = event.text
                        if prompted and "```" in buffer:
                            visible_delta = ""
                        if visible_delta:
                            hub.broadcast(
                                campaign.id,
                                events.make_event(
                                    events.STREAM_DELTA, campaign.id,
                                    {"stream_id": stream_id, "delta": visible_delta},
                                    scene_id,
                                ),
                                scene_id=scene_id,
                                dm_only=assist,
                            )
                    elif isinstance(event, ToolCall):
                        native_calls.append(event)
                    elif isinstance(event, Done):
                        finish = event.finish_reason
                        for key in usage_total:
                            usage_total[key] += event.usage.get(key, 0)

                # Determine narration + tool calls for this round.
                if prompted:
                    narration, parsed_calls, parse_errors = extract_tool_calls(buffer)
                    calls = [
                        ToolCall(id=uuid.uuid4().hex[:8], name=c["name"], arguments=c["arguments"])
                        for c in parsed_calls
                    ]
                else:
                    narration = buffer.strip()
                    calls, parse_errors = native_calls, []

                # Leak scan: hold/flag narration that quotes secret notes verbatim.
                from app.services.safety import scan_for_secret_leaks

                leak = await scan_for_secret_leaks(db, campaign, scene, narration)

                # Persist this round's narration (if any) as a message. Assist
                # drafts (and leaky narration in copilot) stay DM-only until
                # approved; in autonomous mode leaks get a DM warning instead.
                hold_narration = assist or (leak and scene.dm_mode == "copilot")
                message_row = None
                if narration:
                    message_row = await create_message(
                        db, scene, author_type="ai", kind="narration",
                        content=narration, broadcast=False,
                        visibility="dm" if hold_narration else "all",
                    )
                    if hold_narration:
                        from app.services.approvals import hold_draft_turn

                        await hold_draft_turn(db, campaign, scene, message_row, leak=leak)
                    elif leak:
                        await create_message(
                            db, scene, author_type="system", kind="system",
                            content=f"⚠️ Possible secret leak in the last narration: {leak}",
                            visibility="dm",
                        )
                if started:
                    hub.broadcast(
                        campaign.id,
                        events.make_event(
                            events.STREAM_END, campaign.id,
                            {
                                "stream_id": stream_id,
                                "message": message_out(message_row) if message_row else None,
                            },
                            scene_id,
                        ),
                        scene_id=scene_id,
                        dm_only=hold_narration,
                    )
                elif message_row:
                    hub.broadcast(
                        campaign.id,
                        events.make_event(
                            events.MESSAGE_CREATED, campaign.id,
                            message_out(message_row), scene_id,
                        ),
                        scene_id=scene_id,
                        dm_only=hold_narration,
                    )

                steps.append(
                    {
                        "round": round_no,
                        "narration_chars": len(narration),
                        "tool_calls": [
                            {"name": c.name, "arguments": c.arguments} for c in calls
                        ],
                        "parse_errors": parse_errors,
                        "finish_reason": finish,
                    }
                )

                if parse_errors and not calls:
                    # One repair attempt: show the model its formatting mistake.
                    messages.append({"role": "assistant", "content": buffer})
                    messages.append(
                        {
                            "role": "user",
                            "content": "[system] Your tool block was malformed: "
                            + "; ".join(parse_errors)
                            + ' Re-emit ONLY a corrected ```tool_call block, nothing else.',
                        }
                    )
                    continue

                if not calls:
                    break  # text-only response → turn complete

                # Execute tool calls, appending results for the follow-up round.
                if use_native:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": narration or None,
                            "tool_calls": [
                                {
                                    "id": c.id,
                                    "type": "function",
                                    "function": {
                                        "name": c.name,
                                        "arguments": json.dumps(c.arguments),
                                    },
                                }
                                for c in calls
                            ],
                        }
                    )
                else:
                    messages.append({"role": "assistant", "content": buffer})

                for call in calls:
                    _status(campaign.id, scene_id, f"🎲 {call.name}…")

                    # Copilot: gated tools wait for DM approval. Assist: every
                    # mutating tool waits. Reads and dice always run.
                    spec_name = registry.resolve_name(call.name)
                    spec = registry.get(spec_name) if spec_name else None
                    hold = spec is not None and (
                        (scene.dm_mode == "copilot" and spec.gated)
                        or (scene.dm_mode == "assist" and spec.mutating and spec.name != "roll_dice")
                    )
                    if hold:
                        from app.services.approvals import hold_tool_call

                        approval = await hold_tool_call(db, campaign, scene, spec.name, call.arguments)
                        result = held_for_approval_result(approval.id)
                    else:
                        result = await registry.dispatch(ctx, call.name, call.arguments)
                    log_row = ToolCallLog(
                        scene_id=scene_id,
                        ai_turn_id=turn.id,
                        call_id=call.id,
                        tool=call.name,
                        args_json=call.arguments,
                        result_json=result.for_llm(),
                        inverse_patch_json=list(ctx.inverse_patches),
                    )
                    ctx.inverse_patches.clear()
                    db.add(log_row)
                    await db.commit()

                    hub.broadcast(
                        campaign.id,
                        events.make_event(
                            events.TOOL_ACTIVITY, campaign.id,
                            {
                                "tool": call.name,
                                "ok": result.ok,
                                "note": result.public_note,
                            },
                            scene_id,
                        ),
                        scene_id=scene_id,
                    )
                    if result.public_note:
                        await create_message(
                            db, scene, author_type="tool", kind="tool_result",
                            content=result.public_note,
                            payload={"tool": call.name, "ok": result.ok},
                        )

                    if use_native:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(result.for_llm()),
                            }
                        )
                    else:
                        messages.append(
                            {
                                "role": "user",
                                "content": f"[tool result for {call.name}] "
                                + json.dumps(result.for_llm()),
                            }
                        )
                _status(campaign.id, scene_id, "The DM weaves the outcome…")
            else:
                # Round cap hit: force one final text-only reply.
                messages.append(
                    {
                        "role": "user",
                        "content": "[system] Tool budget exhausted — respond with narration only.",
                    }
                )
                final = ""
                async for event in provider.chat(messages, tools=None):
                    if isinstance(event, TextDelta):
                        final += event.text
                if final.strip():
                    await create_message(
                        db, scene, author_type="ai", kind="narration", content=final.strip()
                    )

            turn.status = "done"
            turn.steps_json = steps
            turn.token_usage_json = usage_total
            await db.commit()

            from app.ai.memory import maybe_rollup

            try:
                await maybe_rollup(db, campaign, scene)
            except Exception:
                log.exception("rolling summary failed (scene=%s)", scene_id)
        except Exception as exc:
            log.exception("AI turn failed (scene=%s)", scene_id)
            turn.status = "error"
            turn.error = str(exc)[:2000]
            turn.steps_json = steps
            await db.commit()
            await create_message(
                db, scene, author_type="system", kind="system",
                content=f"⚠️ The AI DM hit a snag: {exc}", visibility="dm",
            )
        finally:
            _status(campaign.id, scene_id, "")
