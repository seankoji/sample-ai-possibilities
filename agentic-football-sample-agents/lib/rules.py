"""Deterministic tactical guardrails applied to parsed LLM commands."""

from __future__ import annotations
from dataclasses import dataclass

from state import (
    _player_idx,
    _is_my_team,
    _possession_idx,
    get_goal_positions,
    get_possession_info,
    dist,
    is_nearest_to_ball,
    is_attacking_third,
    shot_blockers,
    ball_side,
    get_score_diff,
    is_lane_blocked,
    get_far_post_aim,
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
            or not (0 <= target <= 9)
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

    game_time = float(game_state.get("gameTime", 0) or 0)
    score_diff = get_score_diff(game_state, team_id)
    is_chasing = (score_diff < 0 and game_time > 150.0)
    is_defending_lead = (score_diff >= 2)

    sanitized: list[dict] = []

    for cmd in commands:
        # Rule 1: Schema validation
        if not _validate_schema(cmd, my_player_id):
            continue

        cmd_type = cmd["commandType"]
        params = dict(cmd.get("parameters", {}))
        duration = cmd.get("duration", 0)

        # Rule 2: Anti-swarm & pressing
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
            else:
                # Nearest player allowed to press — elevate intensity if chasing deficit
                if is_chasing and cmd_type == "PRESS_BALL":
                    params["intensity"] = min(1.0, max(float(params.get("intensity", 0.7)), 0.9))

        # Rule 2b: INTERCEPT guardrail — only viable when ball is free and close
        if cmd_type == "INTERCEPT":
            ball_is_free = (_possession_idx(ball) is None)
            dist_to_ball = dist(my_pos, ball_pos)
            if not ball_is_free or dist_to_ball > 15.0:
                # Ball not free or too far - move toward it instead
                cmd_type = "MOVE_TO"
                params = {
                    "target_x": ball_pos.get("x", 0),
                    "target_y": ball_pos.get("y", 0),
                    "sprint": (dist_to_ball > 10.0)
                }
                duration = 0

        # Rule 3: Shot discipline & Dynamic Far-Post Aiming
        if cmd_type == "SHOOT":
            # Dynamic far-post corner relative to opponent GK
            opp_gk = next((p for p in opponents if _player_idx(p) == 0), None)
            if opp_gk:
                opp_gk_y = opp_gk.get("position", {}).get("y", 0.0)
                current_aim = params.get("aim_location", "CENTER")
                prefer_top = ("T" in current_aim or current_aim == "CENTER")
                params["aim_location"] = get_far_post_aim(opp_gk_y, prefer_top=prefer_top)

            if rules.shoot_gate:
                in_att_third = is_attacking_third(my_pos.get("x", 0), team_id)
                dist_opp_goal = abs(my_pos.get("x", 0) - opp_goal_x)
                blockers = shot_blockers(my_pos, opp_goal_x, opponents)
                effective_max_blockers = rules.max_shot_blockers
                # Relax blocker threshold when chasing deficit or within 18m of goal
                if is_chasing or dist_opp_goal <= 18.0:
                    effective_max_blockers = max(effective_max_blockers, 3)

                is_point_blank = (dist_opp_goal <= 14.0) and (abs(my_pos.get("y", 0)) <= 12.0)
                allowed_to_shoot = is_point_blank or (in_att_third and (dist_opp_goal <= 28.0) and (blockers < effective_max_blockers))
                if not allowed_to_shoot:
                    outfield_teammates = [
                        p
                        for p in my_team
                        if _player_idx(p) != my_player_id and _player_idx(p) != 0
                    ]
                    if outfield_teammates:
                        unblocked = [
                            p for p in outfield_teammates
                            if not is_lane_blocked(my_pos, p.get("position", {}), opponents, clearance=2.5)
                        ]
                        candidate_list = unblocked if unblocked else outfield_teammates
                        best_tm = min(
                            candidate_list,
                            key=lambda p: abs(
                                p.get("position", {}).get("x", 0) - opp_goal_x
                            ),
                        )
                        cmd_type = "PASS"
                        pass_t = "GROUND" if unblocked else "AERIAL"
                        params = {
                            "target_player_id": _player_idx(best_tm),
                            "type": pass_t,
                        }
                        duration = 0
                    else:
                        continue

        # Passing lane clearance & re-routing
        if cmd_type == "PASS":
            target_pid = params.get("target_player_id")
            target_tm = next((p for p in my_team if _player_idx(p) == target_pid), None)
            pass_type = params.get("type", "GROUND")
            if target_tm and pass_type in ("GROUND", "THROUGH"):
                target_pos = target_tm.get("position", {})
                if is_lane_blocked(my_pos, target_pos, opponents, clearance=2.5):
                    alt_teammates = [
                        p for p in my_team
                        if _player_idx(p) not in (0, my_player_id, target_pid)
                    ]
                    unblocked_alts = [
                        p for p in alt_teammates
                        if not is_lane_blocked(my_pos, p.get("position", {}), opponents, clearance=2.5)
                    ]
                    if unblocked_alts:
                        best_alt = min(
                            unblocked_alts,
                            key=lambda p: abs(p.get("position", {}).get("x", 0) - opp_goal_x),
                        )
                        params["target_player_id"] = _player_idx(best_alt)
                    else:
                        params["type"] = "AERIAL"

        # GK possession enforcement: GK with ball must GK_DISTRIBUTE to wider/open wing player (IDs 2 vs 3)
        if rules.box_only or my_player_id == 0:
            poss_id, _, _ = get_possession_info(ball, players, team_id)
            if poss_id == my_player_id:
                if cmd_type != "GK_DISTRIBUTE":
                    cmd_type = "GK_DISTRIBUTE"
                    params = {"method": params.get("method", "THROW")}
                    duration = 0
                target_pid = params.get("target_player_id")
                # When target is not a valid open wing player (2 or 3)
                p2 = next((p for p in my_team if _player_idx(p) == 2), None)
                p3 = next((p for p in my_team if _player_idx(p) == 3), None)
                if p2 and p3:
                    p2_pos = p2.get("position", {})
                    p3_pos = p3.get("position", {})
                    p2_opp_dist = min([dist(p2_pos, opp.get("position", {})) for opp in opponents], default=99.0)
                    p3_opp_dist = min([dist(p3_pos, opp.get("position", {})) for opp in opponents], default=99.0)
                    p2_lane_blocked = is_lane_blocked(my_pos, p2_pos, opponents, clearance=2.5)
                    p3_lane_blocked = is_lane_blocked(my_pos, p3_pos, opponents, clearance=2.5)

                    if p2_lane_blocked and not p3_lane_blocked:
                        chosen_id = 3
                    elif p3_lane_blocked and not p2_lane_blocked:
                        chosen_id = 2
                    elif p2_opp_dist > p3_opp_dist + 2.0:
                        chosen_id = 2
                    elif p3_opp_dist > p2_opp_dist + 2.0:
                        chosen_id = 3
                    else:
                        chosen_id = 2 if abs(p2_pos.get("y", 0)) >= abs(p3_pos.get("y", 0)) else 3
                elif p2:
                    chosen_id = 2
                elif p3:
                    chosen_id = 3
                else:
                    outfield = [p for p in my_team if _player_idx(p) not in (0, my_player_id)]
                    chosen_id = _player_idx(outfield[0]) if outfield else 1
                params["target_player_id"] = chosen_id

        # Rule 4: Role boundaries
        if cmd_type == "MOVE_TO":
            tx = float(params.get("target_x", 0.0))
            ty = float(params.get("target_y", 0.0))
            if rules.own_half_only:
                if is_chasing:
                    # Relax CB boundary when chasing deficit in second half
                    max_adv = opp_goal_x * 0.4
                    if team_id == 0:
                        tx = max(-55.0, min(max_adv, tx))
                    else:
                        tx = min(55.0, max(max_adv, tx))
                else:
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

        # Rule 5: Stamina & opposite-flank & defending lead checks
        if low_stamina or is_defending_lead:
            if cmd_type == "MOVE_TO":
                params["sprint"] = False
            elif low_stamina and cmd_type == "PRESS_BALL":
                continue

        if is_defending_lead and cmd_type == "MARK":
            params["tightness"] = "TIGHT"

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
        # Rule 5: Wall Anti-Collision, Outfield Compactness & CB Anti-Goal Clamp
        # 1. CB / DEF is strictly prohibited from dropping deeper than x = -36.0 (Team 0) / 36.0 (Team 1) -> NEVER stands in goal!
        # 2. Outfield attackers and midfielders bounded to |x| <= 38.0, |y| <= 12.0
        # 3. Only GK is allowed inside the goal area (|x| > 36.0).
        if cmd_type == "MOVE_TO":
            tx = float(params.get("target_x", 0.0))
            ty = float(params.get("target_y", 0.0))
            if my_player_id == 0:
                params["target_x"] = max(-52.0, min(52.0, tx))
                params["target_y"] = max(-20.0, min(20.0, ty))
            elif my_player_id == 1 or getattr(rules, "own_half_only", False):
                if team_id == 0:
                    max_x = 15.0 if is_chasing else 0.0
                    params["target_x"] = max(-36.0, min(max_x, tx))
                else:
                    min_x = -15.0 if is_chasing else 0.0
                    params["target_x"] = max(min_x, min(36.0, tx))
                params["target_y"] = max(-8.0, min(8.0, ty))
            else:
                params["target_x"] = max(-35.0, min(35.0, tx))
                params["target_y"] = max(-8.0, min(8.0, ty))

        # Rule 5b: Anti-Goal Line MARK guard — don't follow opponents into our own net
        if cmd_type == "MARK" and getattr(rules, "own_half_only", False):
            target_pid = params.get("target_player_id")
            target_opp = next((p for p in opponents if _player_idx(p) == target_pid), None)
            if target_opp:
                opp_x = target_opp.get("position", {}).get("x", 0)
                is_in_our_box = (opp_x < -36.0) if team_id == 0 else (opp_x > 36.0)
                if is_in_our_box:
                    # Hold the 25% pitch line instead of standing on top of GK in goal
                    cmd_type = "MOVE_TO"
                    params = {"target_x": my_goal_x * 0.50, "target_y": max(-6.0, min(6.0, target_opp.get("position", {}).get("y", 0))), "sprint": False}
                    duration = 0

        # Rule 4: Stamina preservation — no sprint below stamina 30
        if cmd_type == "MOVE_TO" and params.get("sprint", False):
            min_sprint = getattr(rules, "min_sprint_stamina", 30) if rules else 30
            if stam < min_sprint:
                params["sprint"] = False

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
