from app.ai.toolcall_fallback import extract_tool_calls, repair_json


def test_clean_block():
    text = (
        "The goblin lunges!\n"
        '```tool_call\n{"name": "roll_dice", "arguments": {"expression": "1d20+4"}}\n```'
    )
    narration, calls, errors = extract_tool_calls(text)
    assert narration == "The goblin lunges!"
    assert calls == [{"name": "roll_dice", "arguments": {"expression": "1d20+4"}}]
    assert errors == []


def test_trailing_comma_and_single_quotes():
    text = "```tool_call\n{'name': 'update_hp', 'arguments': {'target': 'Mira', 'delta': -5,},}\n```"
    _, calls, errors = extract_tool_calls(text)
    assert errors == []
    assert calls[0]["name"] == "update_hp"
    assert calls[0]["arguments"]["delta"] == -5


def test_unquoted_keys_and_python_literals():
    raw = '{name: "award", arguments: {xp_each: 100, recipients: "party", flag: True, note: None}}'
    parsed = repair_json(raw)
    assert parsed is not None
    assert parsed["arguments"]["flag"] is True
    assert parsed["arguments"]["note"] is None


def test_alt_field_names_tool_and_args():
    text = '```tool\n{"tool": "lookup", "args": {"query": "grappled", "kind": "condition"}}\n```'
    _, calls, errors = extract_tool_calls(text)
    assert errors == []
    assert calls == [{"name": "lookup", "arguments": {"query": "grappled", "kind": "condition"}}]


def test_multiple_blocks_and_narration_between():
    text = (
        "First the attack.\n"
        '```tool_call\n{"name": "roll_dice", "arguments": {"kind": "attack"}}\n```\n'
        "And the damage.\n"
        '```tool_call\n{"name": "roll_dice", "arguments": {"kind": "damage", "expression": "1d6"}}\n```'
    )
    narration, calls, errors = extract_tool_calls(text)
    assert len(calls) == 2
    assert "First the attack." in narration and "And the damage." in narration
    assert errors == []


def test_garbage_block_reports_error():
    text = "```tool_call\nnot json at all {{{\n```"
    narration, calls, errors = extract_tool_calls(text)
    assert calls == []
    assert len(errors) == 1
    assert narration == ""


def test_plain_text_passthrough():
    narration, calls, errors = extract_tool_calls("Just narration, no tools.")
    assert narration == "Just narration, no tools."
    assert calls == [] and errors == []
