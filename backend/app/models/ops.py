from typing import Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import TimestampedBase


class AppSetting(TimestampedBase):
    """Admin-editable key/value settings; override env defaults (LLM config etc.).

    API keys are Fernet-encrypted with SECRET_KEY before storage.
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value_json: Mapped[dict[str, Any]] = mapped_column(default=dict)


class AiTurn(TimestampedBase):
    """One agentic AI-DM turn: full tool-call trace for debugging + audit."""

    __tablename__ = "ai_turns"

    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), index=True)
    status: Mapped[str] = mapped_column(String(10), default="running")
    # running | done | error | cancelled
    trigger_message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    steps_json: Mapped[list[Any]] = mapped_column(default=list)
    token_usage_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    model: Mapped[str] = mapped_column(String(120), default="")
    error: Mapped[str] = mapped_column(Text, default="")


class ToolCallLog(TimestampedBase):
    """Audit + idempotency + retcon support for every mutating tool call."""

    __tablename__ = "tool_call_log"
    __table_args__ = (UniqueConstraint("ai_turn_id", "call_id"),)

    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), index=True)
    ai_turn_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    message_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    call_id: Mapped[str] = mapped_column(String(64))
    tool: Mapped[str] = mapped_column(String(60))
    args_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # Prior values captured by mutating handlers; applied in reverse for retcon.
    inverse_patch_json: Mapped[list[Any]] = mapped_column(default=list)
    reverted: Mapped[bool] = mapped_column(default=False)
    approved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


class PendingApproval(TimestampedBase):
    """Copilot/assist-mode proposals awaiting the human DM (survive restarts)."""

    __tablename__ = "pending_approvals"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    scene_id: Mapped[str] = mapped_column(ForeignKey("scenes.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # draft_turn | tool_call
    payload_json: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    # pending | approved | rejected | expired
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


class Summary(TimestampedBase):
    """Rolling memory: scene summaries, session recaps, campaign summary."""

    __tablename__ = "summaries"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)
    scope: Mapped[str] = mapped_column(String(10))  # scene | session | campaign
    ref_id: Mapped[str | None] = mapped_column(String(32), nullable=True)  # scene id etc.
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(120), default="")
