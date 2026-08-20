"""Coaching instruction (teamChat) handling.

Extracts the latest coach instruction from the game state, classifies it into a
tactical posture (deterministic keyword match — no extra LLM call), keeps
match-scoped history, and modulates RoleRules so coaching actually changes
behavior instead of being vetoed by the rules layer.
"""

from __future__ import annotations
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rules import RoleRules

DEFENSIVE, BALANCED, ATTACKING, ALL_OUT = (
    "DEFENSIVE",
    "BALANCED",
    "ATTACKING",
    "ALL_OUT",
)

# Order matters: first match wins. DEFENSIVE is checked before ATTACKING so
# "hold position, wait for counter-attack" classifies DEFENSIVE.
_KEYWORDS = [
    (
        ALL_OUT,
        [
            "need a goal",
            "push forward",
            "all out",
            "everyone forward",
            "must score",
            "go for it",
        ],
    ),
    (
        DEFENSIVE,
        [
            "hold position",
            "stay back",
            "defend",
            "protect the lead",
            "slow the game",
            "possession",
            "keep shape",
            "drop deep",
            "park the bus",
        ],
    ),
    (
        ATTACKING,
        [
            "press higher",
            "win the ball back",
            "higher press",
            "push up",
            "attack",
            "take more shots",
            "counter",
        ],
    ),
    (BALANCED, ["balanced", "revert", "back to normal", "reset", "default"]),
]

# Module-level match state (AgentCore runtimes stay warm between ticks).
_match = {"last_time": 0.0, "posture": BALANCED, "instruction": None}


def _extract_latest(chat) -> str | None:
    """Pull the newest instruction text from teamChat (str or dict entries)."""
    if not isinstance(chat, list) or not chat:
        return None
    last = chat[-1]
    if isinstance(last, str):
        return last
    if isinstance(last, dict):
        for key in ("content", "message", "text", "instruction"):
            if isinstance(last.get(key), str):
                return last[key]
    return None


def classify(text: str) -> str:
    """Map an instruction to a posture via keyword match. First match wins."""
    t = text.lower()
    for posture, keywords in _KEYWORDS:
        if any(k in t for k in keywords):
            return posture
    return BALANCED


def apply_posture(rules: "RoleRules | None", posture: str) -> "RoleRules | None":
    """Return a posture-adjusted copy of RoleRules. None passes through."""
    if rules is None:
        return None
    if posture == ALL_OUT:
        return replace(rules, own_half_only=False, max_shot_blockers=3)
    if posture == DEFENSIVE:
        return replace(rules, max_shot_blockers=1)
    return rules  # BALANCED / ATTACKING: defaults (ATTACKING acts via the prompt line)


def update_coaching(
    game_state: dict, role_rules: "RoleRules | None"
) -> tuple[str, "RoleRules | None"]:
    """Call once per tick. Returns (prompt_line, effective_rules).

    prompt_line is "" when no coaching instruction has been received this match.
    """
    now = float(game_state.get("gameTime", 0) or 0)
    if now < _match["last_time"] - 5:  # clock went backwards → new match
        _match.update(posture=BALANCED, instruction=None)
    _match["last_time"] = now

    instruction = _extract_latest(game_state.get("teamChat"))
    if instruction and instruction != _match["instruction"]:
        _match["instruction"] = instruction
        _match["posture"] = classify(instruction)

    if not _match["instruction"]:
        return "", role_rules
    line = f'\nCOACH: "{_match["instruction"]}" → posture={_match["posture"]}. Obey this posture.'
    return line, apply_posture(role_rules, _match["posture"])
