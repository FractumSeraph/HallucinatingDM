"""AI character-build suggestions: concept in, validated wizard payload out.

The LLM proposes JSON; the server validates it against the SRD via the same
character builder the wizard uses, with repair round-trips for bad output.
Derived values (HP, AC, slots) are always computed by code.
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.provider import TextDelta, get_provider
from app.ai.toolcall_fallback import repair_json
from app.models import SrdEntry
from app.services.character_builder import BuildError, CharacterBuild, build_character

log = logging.getLogger("hallucinatingdm.chargen")

MAX_ATTEMPTS = 3

PROMPT = """You design D&D 5E characters. Given a player's concept, output ONLY a JSON object (no markdown fences, no commentary) with exactly these fields:

{{
  "name": "<character name>",
  "race": "<race slug from the list>",
  "subrace": "<subrace name from the list, or empty string>",
  "klass": "<class slug from the list>",
  "background": "acolyte",
  "alignment": "<one of the nine alignments or empty>",
  "method": "standard",
  "base_scores": {{"str": _, "dex": _, "con": _, "int": _, "wis": _, "cha": _}},
  "skill_choices": [<exactly the number of skills the class allows, from its list>],
  "personality": "<1-2 sentences>",
  "backstory": "<2-3 sentences with a hook the DM can use>"
}}

base_scores must be exactly the standard array 15, 14, 13, 12, 10, 8 (each used once), assigned to fit the concept (prime ability highest).

AVAILABLE RACES (slug: subraces): {races}
AVAILABLE CLASSES (slug: pick N skills from list): {classes}

PLAYER CONCEPT: {concept}"""


async def suggest_build(
    db: AsyncSession, campaign_id: str, user_id: str, concept: str
) -> tuple[dict | None, str]:
    """Returns (build payload dict, error). Validates without persisting."""
    races = list(
        (await db.execute(select(SrdEntry).where(SrdEntry.kind == "race"))).scalars()
    )
    classes = list(
        (await db.execute(select(SrdEntry).where(SrdEntry.kind == "class"))).scalars()
    )
    race_desc = "; ".join(
        f"{r.slug}: [{', '.join(s['name'] for s in (r.data_json.get('subraces') or []))}]"
        for r in races
    )
    class_desc = "; ".join(
        f"{c.slug}: pick {((c.data_json.get('proficiencies') or {}).get('skills') or {}).get('choose', 0)} "
        f"from [{', '.join(((c.data_json.get('proficiencies') or {}).get('skills') or {}).get('from', []))}]"
        for c in classes
    )

    provider = await get_provider()
    messages = [
        {
            "role": "user",
            "content": PROMPT.format(races=race_desc, classes=class_desc, concept=concept),
        }
    ]

    last_error = "no attempts made"
    for _attempt in range(MAX_ATTEMPTS):
        raw = ""
        async for event in provider.chat(messages, temperature=0.7, max_tokens=700):
            if isinstance(event, TextDelta):
                raw += event.text
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`\n")
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = repair_json(raw)
        if parsed is None:
            last_error = "Response was not valid JSON"
        else:
            try:
                build = CharacterBuild.model_validate(parsed)
                # dry-run the real builder for full SRD validation
                await build_character(db, campaign_id, user_id, build)
                await db.rollback()
                return build.model_dump(), ""
            except (BuildError, ValueError) as exc:
                last_error = str(exc)
        messages.append({"role": "assistant", "content": raw[:2000]})
        messages.append(
            {
                "role": "user",
                "content": f"That build was invalid: {last_error}. "
                "Output ONLY the corrected JSON object.",
            }
        )
    return None, last_error


def compact_json(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"))
