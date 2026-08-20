"""Deterministic tactical guardrails applied to parsed LLM commands."""

from __future__ import annotations
from dataclasses import dataclass

from state import (
    _player_idx,
    _is_my_team,
    get_goal_positions,
    get_possession_info,
    dist,
    is_nearest_to_ball,
    is_attacking_third,
    shot_blockers,
    ball_side,
)


@dataclass
class RoleRules:
    label: str  # "GK" | "CB" | "LM" | "RM" | "ST"
    own_half_only: bool = False  # CB: clamp MOVE_TO targets to own half
    box_only: bool = False  # GK: clamp MOVE_TO targets to box region (within ~15 of own goal x, |y| <= 20)
    may_press: bool = True
    shoot_gate: bool = True  # require attacking third AND blockers < max_shot_blockers
    max_shot_blockers: int = 2  # shot gate threshold (coaching postures adjust this)
    home_y: float | None = None  # LM → -15, RM → +15 (wide home flank)


def _validate_schema(cmd: dict, my_player_id: int) -> bool:
    """Validate schema and parameter ranges of a single command."""
    if not isinstance(cmd, dict):
        return False
    cmd_type = cmd.get("commandType")
    if not isinstance(cmd_type, str):
        return False
    params = cmd.get("parameters")
    if not isinstance(params, dict):
        return False

    if cmd_type == "SHOOT":
        aim = params.get("aim_location")
        if aim not in {"TL", "TR", "BL", "BR", "CENTER"}:
            return False
        power = params.get("power")
        if not isinstance(power, (int, float)) or not (0.0 <= power <= 1.0):
            return False
        return True

    if cmd_type in ("PASS", "GK_DISTRIBUTE"):
        target = params.get("target_player_id")
        if (
            not isinstance(target, int)
            or isinstance(target, bool)
            or not (0 <= target <= 4)
            or target == my_player_id
        ):
            return False
        if cmd_type == "PASS":
            pass_type = params.get("type", "GROUND")
            if pass_type not in {"GROUND", "AERIAL", "THROUGH"}:
                return False
        elif cmd_type == "GK_DISTRIBUTE":
            method = params.get("method", "THROW")
            if method not in {"THROW", "KICK"}:
                return False
        return True

    if cmd_type in ("MARK", "FOLLOW_PLAYER", "SLIDE_TACKLE"):
        target = params.get("target_player_id")
        if (
            not isinstance(target, int)
            or isinstance(target, bool)
            or not (0 <= target <= 4)
            or target == my_player_id
        ):
            return False
        if cmd_type == "MARK":
            tightness = params.get("tightness", "LOOSE")
            if tightness not in {"LOOSE", "TIGHT"}:
                return False
        return True

    if cmd_type == "PRESS_BALL":
        intensity = params.get("intensity")
        if not isinstance(intensity, (int, float)) or not (0.0 <= intensity <= 1.0):
            return False
        return True

    if cmd_type == "MOVE_TO":
        tx = params.get("target_x")
        ty = params.get("target_y")
        if not isinstance(tx, (int, float)) or not isinstance(ty, (int, float)):
            return False
        return True

    if cmd_type == "SET_STANCE":
        stance = params.get("stance")
        if (
            not isinstance(stance, int)
            or isinstance(stance, bool)
            or stance not in {0, 1, 2}
        ):
            return False
        return True

    if cmd_type in ("INTERCEPT", "CLEAR_OVERRIDE", "RESET"):
        return True

    return False


def sanitize_commands(
    commands: list[dict],
    game_state: dict,
    team_id: int,
    my_player_id: int,
    rules: RoleRules,
) -> list[dict]:
    """Filter/mutate commands per tactical rules. May return [] (caller falls back)."""
    players = game_state.get("players", [])
    my_team = [p for p in players if _is_my_team(p, team_id)]
    opponents = [p for p in players if not _is_my_team(p, team_id)]
    me = next((p for p in my_team if _player_idx(p) == my_player_id), None)
    ball = game_state.get("ball", {})
    ball_pos = ball.get("position", {"x": 0, "y": 0})
    my_pos = me.get("position", {"x": 0, "y": 0}) if me else {"x": 0, "y": 0}
    my_goal_x, opp_goal_x = get_goal_positions(team_id)

    stam_raw = me.get("stamina", 100) if me else 100
    stam = stam_raw * 100 if stam_raw <= 1.0 else stam_raw
    low_stamina = stam < 30

    sanitized: list[dict] = []

    for cmd in commands:
        # Rule 1: Schema validation
        if not _validate_schema(cmd, my_player_id):
            continue

        cmd_type = cmd["commandType"]
        params = dict(cmd.get("parameters", {}))
        duration = cmd.get("duration", 0)

        # Rule 2: Anti-swarm
        if cmd_type in ("PRESS_BALL", "SLIDE_TACKLE"):
            if not rules.may_press or not is_nearest_to_ball(
                my_pos, my_player_id, my_team, ball_pos
            ):
                opps_in_my_half = [
                    p
                    for p in opponents
                    if (
                        p.get("position", {}).get("x", 0) <= 0
                        if team_id == 0
                        else p.get("position", {}).get("x", 0) >= 0
                    )
                ]
                if opps_in_my_half:
                    target_opp = min(
                        opps_in_my_half,
                        key=lambda p: dist(p.get("position", {}), my_pos),
                    )
                    opp_x = target_opp.get("position", {}).get("x", 0)
                    in_own_third = (
                        (opp_x < -55.0 / 3.0) if team_id == 0 else (opp_x > 55.0 / 3.0)
                    )
                    tightness = "TIGHT" if in_own_third else "LOOSE"
                    cmd_type = "MARK"
                    params = {
                        "target_player_id": _player_idx(target_opp),
                        "tightness": tightness,
                    }
                    duration = 3
                else:
                    # Fallback to MOVE_TO home coordinate
                    home_y = rules.home_y if rules.home_y is not None else 0.0
                    if rules.own_half_only:
                        home_x = my_goal_x * 0.55
                    elif rules.box_only:
                        home_x = my_goal_x * 0.9
                    elif rules.label == "ST":
                        home_x = opp_goal_x * 0.35
                    else:
                        home_x = ball_pos.get("x", 0) * 0.3
                    cmd_type = "MOVE_TO"
                    params = {"target_x": home_x, "target_y": home_y, "sprint": False}
                    duration = 0

        # Rule 3: Shot discipline
        if cmd_type == "SHOOT" and rules.shoot_gate:
            in_att_third = is_attacking_third(my_pos.get("x", 0), team_id)
            blockers = shot_blockers(my_pos, opp_goal_x, opponents)
            if not (in_att_third and blockers < rules.max_shot_blockers):
                outfield_teammates = [
                    p
                    for p in my_team
                    if _player_idx(p) != my_player_id and _player_idx(p) != 0
                ]
                if outfield_teammates:
                    best_tm = min(
                        outfield_teammates,
                        key=lambda p: abs(
                            p.get("position", {}).get("x", 0) - opp_goal_x
                        ),
                    )
                    cmd_type = "PASS"
                    params = {
                        "target_player_id": _player_idx(best_tm),
                        "type": "GROUND",
                    }
                    duration = 0
                else:
                    continue

        # GK possession enforcement: GK with ball must GK_DISTRIBUTE
        if rules.box_only or my_player_id == 0:
            poss_id, _, _ = get_possession_info(ball, players, team_id)
            if poss_id == my_player_id and cmd_type != "GK_DISTRIBUTE":
                cmd_type = "GK_DISTRIBUTE"
                params = {"target_player_id": 1, "method": "THROW"}
                duration = 0

        # Rule 4: Role boundaries
        if cmd_type == "MOVE_TO":
            tx = float(params.get("target_x", 0.0))
            ty = float(params.get("target_y", 0.0))
            if rules.own_half_only:
                if team_id == 0:
                    tx = min(tx, 0.0)
                else:
                    tx = max(tx, 0.0)
            if rules.box_only:
                if team_id == 0:
                    tx = max(-55.0, min(-40.0, tx))
                else:
                    tx = min(55.0, max(40.0, tx))
                ty = max(-20.0, min(20.0, ty))
            params["target_x"] = tx
            params["target_y"] = ty

        # Rule 5: Stamina & opposite-flank checks
        if low_stamina:
            if cmd_type == "MOVE_TO":
                params["sprint"] = False
            elif cmd_type == "PRESS_BALL":
                continue

        if rules.home_y is not None and cmd_type == "PRESS_BALL":
            bside = ball_side(ball_pos.get("y", 0))
            is_opposite = (rules.home_y < 0 and bside == "right") or (
                rules.home_y > 0 and bside == "left"
            )
            if is_opposite:
                cmd_type = "MOVE_TO"
                params = {
                    "target_x": ball_pos.get("x", 0) * 0.3,
                    "target_y": rules.home_y,
                    "sprint": False,
                }
                duration = 0

        sanitized.append(
            {
                "commandType": cmd_type,
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": params,
                "duration": duration,
            }
        )

    return sanitized
