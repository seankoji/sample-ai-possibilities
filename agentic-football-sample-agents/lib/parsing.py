"""Response parsing utilities for AI soccer agents."""

import re

from json_tolerant import parse_json_tolerant

VALID_COMMANDS = {
    "MOVE_TO", "PASS", "SHOOT", "SLIDE_TACKLE", "PRESS_BALL", "INTERCEPT", "MARK",
    "FOLLOW_PLAYER", "GK_DISTRIBUTE", "SET_STANCE", "CLEAR_OVERRIDE", "RESET",
}


def parse_commands(text: str, team_id: int, my_player_id: int, on_recovered=None) -> list[dict]:
    """Extract commands from LLM response, forcing the given player ID on all commands.

    A model that writes Python-flavoured JSON (``True`` instead of ``true``, a trailing
    comma, a markdown fence) still has its commands used — see lib/json_tolerant.py for
    what is recovered and what is deliberately left alone. Pass ``on_recovered(raw)`` if
    you want to log how often that happens; the commands themselves are used exactly as
    if the model had emitted valid JSON.
    """
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        commands = _loads(match.group(), on_recovered)
        if isinstance(commands, list):
            return _tag_commands(commands, team_id, my_player_id)

    parsed = _loads(text, on_recovered)
    if isinstance(parsed, list):
        return _tag_commands(parsed, team_id, my_player_id)
    if isinstance(parsed, dict) and "commandType" in parsed:
        parsed["teamId"] = team_id
        parsed["playerId"] = my_player_id
        return [parsed]

    return []


def _loads(candidate: str, on_recovered):
    """Parse one candidate payload; None when it does not parse even after normalisation."""
    result = parse_json_tolerant(candidate)
    if result is None:
        return None
    value, recovered = result
    if recovered and on_recovered is not None:
        on_recovered(candidate)
    return value


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _tag_commands(commands: list, team_id: int, my_player_id: int) -> list[dict]:
    """Add teamId and playerId to each command, filtering to valid ones."""
    result = []
    for cmd in commands:
        if not isinstance(cmd, dict):
            continue
        cmd["teamId"] = team_id
        cmd["playerId"] = my_player_id
        raw_cmd_type = cmd.get("commandType")
        if not isinstance(raw_cmd_type, str):
            continue
        cmd_type = raw_cmd_type.strip().upper()
        if cmd_type not in VALID_COMMANDS:
            continue
        cmd["commandType"] = cmd_type

        params = dict(cmd.get("parameters", {})) if isinstance(cmd.get("parameters"), dict) else {}

        # Type casting & normalization helpers
        if "duration" in cmd:
            try:
                cmd["duration"] = int(cmd["duration"])
            except (ValueError, TypeError):
                cmd["duration"] = 0

        # MOVE_TO
        if cmd_type == "MOVE_TO":
            if "target_x" in params:
                try:
                    params["target_x"] = float(params["target_x"])
                except (ValueError, TypeError):
                    pass
            if "target_y" in params:
                try:
                    params["target_y"] = float(params["target_y"])
                except (ValueError, TypeError):
                    pass
            if isinstance(params.get("target_x"), (int, float)):
                params["target_x"] = _clamp(params["target_x"], -55, 55)
            if isinstance(params.get("target_y"), (int, float)):
                params["target_y"] = _clamp(params["target_y"], -35, 35)
            if "sprint" in params and not isinstance(params["sprint"], bool):
                params["sprint"] = str(params["sprint"]).strip().lower() in ("true", "1")

        # SET_STANCE
        if cmd_type == "SET_STANCE":
            if "stance" in params:
                try:
                    params["stance"] = int(params["stance"])
                except (ValueError, TypeError):
                    params["stance"] = 0
            if params.get("stance") not in (0, 1, 2):
                params["stance"] = 0

        # SHOOT
        if cmd_type == "SHOOT":
            aim = str(params.get("aim_location", "CENTER")).strip().upper()
            if aim not in ("TL", "TR", "BL", "BR", "CENTER"):
                aim = "CENTER"
            params["aim_location"] = aim
            if "power" in params:
                try:
                    params["power"] = float(params["power"])
                except (ValueError, TypeError):
                    params["power"] = 0.8
            if not isinstance(params.get("power"), (int, float)) or not (0.0 <= params["power"] <= 1.0):
                params["power"] = 0.8

        # PRESS_BALL
        if cmd_type == "PRESS_BALL":
            if "intensity" in params:
                try:
                    params["intensity"] = float(params["intensity"])
                except (ValueError, TypeError):
                    params["intensity"] = 0.7
            if not isinstance(params.get("intensity"), (int, float)) or not (0.0 <= params["intensity"] <= 1.0):
                params["intensity"] = 0.7

        # PASS / MARK / FOLLOW_PLAYER / GK_DISTRIBUTE / SLIDE_TACKLE
        if cmd_type in ("PASS", "MARK", "FOLLOW_PLAYER", "GK_DISTRIBUTE", "SLIDE_TACKLE"):
            if "target_player_id" in params and params["target_player_id"] is not None:
                try:
                    params["target_player_id"] = int(params["target_player_id"])
                except (ValueError, TypeError):
                    params["target_player_id"] = None

            if params.get("target_player_id") is None:
                if cmd_type in ("PASS", "GK_DISTRIBUTE"):
                    params["target_player_id"] = 1 if my_player_id == 0 else (3 if my_player_id != 3 else 4)
                else:
                    params["target_player_id"] = 0

            if cmd_type == "PASS":
                pass_t = str(params.get("type", "GROUND")).strip().upper()
                if pass_t not in ("GROUND", "AERIAL", "THROUGH"):
                    pass_t = "GROUND"
                params["type"] = pass_t

            if cmd_type == "GK_DISTRIBUTE":
                method = str(params.get("method", "THROW")).strip().upper()
                if method not in ("THROW", "KICK"):
                    method = "THROW"
                params["method"] = method

            if cmd_type == "MARK":
                tightness = str(params.get("tightness", "LOOSE")).strip().upper()
                if tightness not in ("LOOSE", "TIGHT"):
                    tightness = "LOOSE"
                params["tightness"] = tightness

        cmd["parameters"] = params
        result.append(cmd)
    return result
