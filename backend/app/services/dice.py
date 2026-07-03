"""Server-authoritative dice.

The only source of randomness in the game. Supports expressions like:
  d20, 2d6+3, 1d8+2d6-1, 4d6kh3 (keep highest), 2d20kl1 (keep lowest)
Every individual die face is returned so players can verify rolls.
"""

import re
import secrets
from dataclasses import dataclass, field

MAX_DICE = 100
MAX_SIDES = 1000

_TERM_RE = re.compile(
    r"(?P<sign>[+-])?\s*(?:(?P<count>\d*)d(?P<sides>\d+)(?:k(?P<keep_dir>[hl])(?P<keep>\d+))?|(?P<flat>\d+))\s*",
    re.IGNORECASE,
)


class DiceError(ValueError):
    pass


@dataclass
class DiceResult:
    expression: str
    rolls: list[int] = field(default_factory=list)  # every die actually rolled, in order
    kept: list[int] = field(default_factory=list)  # dice counted toward the total
    modifier: int = 0
    total: int = 0

    def as_dict(self) -> dict:
        return {
            "expression": self.expression,
            "rolls": self.rolls,
            "kept": self.kept,
            "modifier": self.modifier,
            "total": self.total,
        }


def roll(expression: str) -> DiceResult:
    expr = expression.strip().lower()
    if not expr:
        raise DiceError("Empty dice expression")

    result = DiceResult(expression=expr)
    pos = 0
    first = True
    while pos < len(expr):
        m = _TERM_RE.match(expr, pos)
        if not m or m.end() == pos:
            raise DiceError(f"Can't parse dice expression at '{expr[pos:]}'")
        sign = -1 if m.group("sign") == "-" else 1
        if m.group("sign") is None and not first:
            raise DiceError(f"Missing +/- before '{expr[pos:]}'")

        if m.group("flat") is not None:
            result.modifier += sign * int(m.group("flat"))
        else:
            count = int(m.group("count") or 1)
            sides = int(m.group("sides"))
            if not (1 <= count <= MAX_DICE):
                raise DiceError(f"Dice count must be 1-{MAX_DICE}")
            if not (2 <= sides <= MAX_SIDES):
                raise DiceError(f"Dice sides must be 2-{MAX_SIDES}")
            faces = [secrets.randbelow(sides) + 1 for _ in range(count)]
            result.rolls.extend(faces)

            kept = faces
            if m.group("keep"):
                keep_n = int(m.group("keep"))
                if not (1 <= keep_n <= count):
                    raise DiceError("Keep count out of range")
                ordered = sorted(faces, reverse=m.group("keep_dir") == "h")
                kept = ordered[:keep_n]
            result.kept.extend(kept)
            result.total += sign * sum(kept)

        pos = m.end()
        first = False

    result.total += result.modifier
    # Store the compact canonical form ("2d6 + 3" -> "2d6+3") once parsing succeeded.
    result.expression = re.sub(r"\s+", "", expr)
    return result


def roll_d20(advantage: str = "none") -> tuple[int, list[int]]:
    """A single d20 honoring advantage/disadvantage. Returns (chosen, all_faces)."""
    if advantage not in ("none", "adv", "dis"):
        raise DiceError("advantage must be none|adv|dis")
    if advantage == "none":
        face = secrets.randbelow(20) + 1
        return face, [face]
    faces = [secrets.randbelow(20) + 1, secrets.randbelow(20) + 1]
    chosen = max(faces) if advantage == "adv" else min(faces)
    return chosen, faces
