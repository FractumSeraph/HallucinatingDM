"""Prompted tool calling for models without reliable native function calling.

The tool catalog is rendered into the system prompt and the model is told to
emit fenced blocks:

    ```tool_call
    {"name": "roll_dice", "arguments": {"expression": "1d20+5", ...}}
    ```

This module extracts those blocks from streamed text and repairs common JSON
mistakes small models make (trailing commas, single quotes, unquoted keys).
"""

import json
import re
from typing import Any

FENCE_RE = re.compile(r"```(?:tool_call|tool|json_tool)\s*\n(.*?)```", re.DOTALL)


def repair_json(raw: str) -> dict[str, Any] | None:
    """Parse JSON, tolerating the classic small-model mistakes."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fixed = raw
    # strip line comments
    fixed = re.sub(r"^\s*//.*$", "", fixed, flags=re.MULTILINE)
    # trailing commas before } or ]
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
    # single-quoted strings -> double-quoted (crude but effective)
    if '"' not in fixed and "'" in fixed:
        fixed = fixed.replace("'", '"')
    # unquoted keys: {name: -> {"name":
    fixed = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r'\1"\2":', fixed)
    # Python literals
    fixed = re.sub(r"\bTrue\b", "true", fixed)
    fixed = re.sub(r"\bFalse\b", "false", fixed)
    fixed = re.sub(r"\bNone\b", "null", fixed)
    try:
        parsed = json.loads(fixed)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def extract_tool_calls(text: str) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Split model text into (visible_narration, tool_calls, parse_errors)."""
    calls: list[dict[str, Any]] = []
    errors: list[str] = []

    def _consume(match: re.Match) -> str:
        parsed = repair_json(match.group(1))
        if parsed is None:
            errors.append(f"Unparseable tool block: {match.group(1)[:200]}")
        else:
            name = parsed.get("name") or parsed.get("tool")
            args = parsed.get("arguments") or parsed.get("args") or {}
            if not name:
                errors.append("Tool block missing 'name'")
            elif not isinstance(args, dict):
                errors.append(f"Tool '{name}' arguments must be an object")
            else:
                calls.append({"name": str(name), "arguments": args})
        return ""

    narration = FENCE_RE.sub(_consume, text).strip()
    return narration, calls, errors


def render_tool_catalog(tools: list[dict[str, Any]]) -> str:
    """Render OpenAI-format tool schemas as a compact prompt catalog."""
    lines = [
        "## Tools",
        "To use a tool, emit a fenced block exactly like this (one tool per block,",
        "at most one block per response, after any narration):",
        "```tool_call",
        '{"name": "<tool_name>", "arguments": {...}}',
        "```",
        "Available tools:",
    ]
    for tool in tools:
        fn = tool["function"]
        params = fn.get("parameters", {}).get("properties", {})
        required = set(fn.get("parameters", {}).get("required", []))
        args_desc = []
        for arg_name, spec in params.items():
            type_name = spec.get("type", "any")
            if "enum" in spec:
                type_name = "|".join(str(v) for v in spec["enum"])
            marker = "" if arg_name in required else "?"
            args_desc.append(f"{arg_name}{marker}: {type_name}")
        lines.append(f"- {fn['name']}({', '.join(args_desc)}) — {fn.get('description', '')}")
    return "\n".join(lines)
