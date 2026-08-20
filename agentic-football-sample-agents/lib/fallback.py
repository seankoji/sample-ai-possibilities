"""Fallback command factory for AI soccer position agents.

Each position defines a FallbackConfig, and build_fallback() returns a
fallback_commands(game_state, team_id, my_player_id) function.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from state import (
    get_goal_positions,
    get_possession_info,
    dist,
    _player_idx,
    _is_my_team,
    _possession_idx,
    get_score_diff,
    is_lane_blocked,
    get_far_post_aim,
)


@dataclass
class FallbackConfig:
    """Per-position fallback behaviour."""

    # What to do when we have the ball
    possession_action: str = "PASS"
    """One of: GK_DISTRIBUTE, PASS, SHOOT_OR_PASS, SHOOT_OR_ADVANCE."""

    # Default position when nothing else applies
    default_x_factor: float = 0.0
    """Multiplied by my_goal_x or opp_goal_x (see default_x_ref)."""
    default_x_ref: str = "my_goal"
    """'my_goal' or 'opp_goal' — which goal x to multiply."""
    default_y: float | str = 0
    """Fixed y, or 'track_ball' to follow ball y * 0.5 (clamped ±10)."""

    # Pressing
    press_distance: float = 20.0
    press_intensity: float = 0.7
    press_duration: int = 3

    # Shoot threshold (distance to opp goal)
    shoot_threshold: float = 25.0
    shoot_aim: str = "TR"
    shoot_power: float = 0.9

    # Advance with ball (for forwards)
    advance_x_factor: float = 0.6
    advance_y: float = 0.0
    advance_sprint: bool = True

    # Run into space when teammate has ball
    support_x_factor: float = 0.5
    support_y: float = 0.0
    support_sprint: bool = True

    # DEF-specific: mark opponents near our goal
    mark_threshold: float = 0.0
    """If > 0, mark the opponent closest to our goal when within this distance."""
    mark_tightness: str = "TIGHT"

    # Pass target filter (player IDs to exclude from pass targets)
    pass_exclude_ids: list[int] = field(default_factory=list)

    # GK: prefer these targets (LM/RM)
    distribute_wide_ids: list[int] = field(default_factory=list)

    # CB: own third + opponent within 5 → long AERIAL PASS to wide flank
    clear_when_pressured: bool = False

    # Diamond phase-ordered decision tree
    phase_logic: bool = False

    # Default stance when player not found
    default_stance: int = 0

    # Last-resort command — used when BOTH the LLM and fallback function crash.
    # Only commandType, playerId, parameters, and duration are used.
    last_resort_command_type: str = "SET_STANCE"
    last_resort_params: dict = field(default_factory=lambda: {"stance": 0})
    last_resort_duration: int = 0


# ---------------------------------------------------------------------------
# Pre-built configs for each position
# ---------------------------------------------------------------------------

GK_CONFIG = FallbackConfig(
    possession_action="GK_DISTRIBUTE",
    default_x_factor=0.9, default_x_ref="my_goal", default_y="track_ball",
    default_stance=2,
    last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2},
    phase_logic=True
)

DEF_CONFIG = FallbackConfig(
    possession_action="PASS",
    pass_exclude_ids=[0],  # don't pass back to GK
    default_x_factor=0.50, default_x_ref="my_goal", default_y=0,
    mark_threshold=30.0, mark_tightness="TIGHT",
    phase_logic=True,
    default_stance=2,
    last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2},
)

MID_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_PASS",
    default_x_factor=0.5, default_x_ref="ball_x", default_y="track_ball_30",
    press_distance=20.0, press_intensity=0.6,
    shoot_threshold=25.0, shoot_aim="TR", shoot_power=0.8,
    phase_logic=True,
    default_stance=0,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.5},
    last_resort_duration=3,
)

FWD1_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_ADVANCE",
    advance_x_factor=0.6, advance_y=-8, advance_sprint=True,
    support_x_factor=0.5, support_y=-10, support_sprint=True,
    default_x_factor=0.4, default_x_ref="opp_goal", default_y=-8,
    press_distance=20.0, press_intensity=0.7,
    shoot_aim="TR", shoot_power=0.9,
    phase_logic=True,
    default_stance=1,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.6},
    last_resort_duration=3,
)

FWD2_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_ADVANCE",
    advance_x_factor=0.6, advance_y=8, advance_sprint=True,
    support_x_factor=0.5, support_y=10, support_sprint=True,
    default_x_factor=0.4, default_x_ref="opp_goal", default_y=8,
    press_distance=20.0, press_intensity=0.7,
    shoot_aim="BL", shoot_power=0.9,
    phase_logic=True,
    default_stance=1,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.6},
    last_resort_duration=3,
)

# ---------------------------------------------------------------------------
# Diamond Formation Configs (1-2-1)
# ---------------------------------------------------------------------------

GK_DIAMOND_CONFIG = FallbackConfig(
    possession_action="GK_DISTRIBUTE",
    distribute_wide_ids=[2, 3],      # LM/RM — never central
    default_x_factor=0.96, default_x_ref="my_goal", default_y="track_ball",
    default_stance=2,
    last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2},
)

CB_CONFIG = FallbackConfig(
    possession_action="PASS",
    pass_exclude_ids=[0],
    default_x_factor=0.50, default_x_ref="my_goal", default_y=0,
    support_x_factor=-0.50, support_y=0, support_sprint=False,
    mark_threshold=30.0, mark_tightness="TIGHT",
    clear_when_pressured=True, phase_logic=True,
    press_distance=8.0, press_intensity=0.5,
    default_stance=2,
    last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2},
)

LM_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_PASS",
    default_x_factor=0.45, default_x_ref="opp_goal", default_y=-8.0,
    press_distance=6.5, press_intensity=0.55,
    shoot_threshold=14.0, shoot_aim="TL", shoot_power=0.90,
    support_x_factor=0.45, support_y=-8.0, support_sprint=False,
    phase_logic=True, default_stance=0,
    last_resort_command_type="MOVE_TO", last_resort_params={"target_x": 0, "target_y": -8.0, "sprint": False},
    last_resort_duration=0,
)

RM_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_PASS",
    default_x_factor=0.45, default_x_ref="opp_goal", default_y=8.0,
    press_distance=6.5, press_intensity=0.55,
    shoot_threshold=14.0, shoot_aim="TR", shoot_power=0.90,
    support_x_factor=0.45, support_y=8.0, support_sprint=False,
    phase_logic=True, default_stance=0,
    last_resort_command_type="MOVE_TO", last_resort_params={"target_x": 0, "target_y": 8.0, "sprint": False},
    last_resort_duration=0,
)

ST_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_ADVANCE",
    shoot_threshold=18.0, shoot_aim="TR", shoot_power=0.95,
    advance_x_factor=0.48, advance_y=0.0, advance_sprint=False,   # middle of box: no sprint
    support_x_factor=0.48, support_y=0.0, support_sprint=False,
    default_x_factor=0.48, default_x_ref="opp_goal", default_y=0.0,
    press_distance=6.5, press_intensity=0.6,
    phase_logic=True, default_stance=0,
    last_resort_command_type="MOVE_TO", last_resort_params={"target_x": 0, "target_y": 0, "sprint": False},
    last_resort_duration=0,
)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_last_resort(cfg: FallbackConfig, player_id: int) -> dict:
    """Build the last-resort command dict from a FallbackConfig.

    This command is only used when BOTH the LLM and the fallback function crash.
    """
    return {
        "commandType": cfg.last_resort_command_type,
        "playerId": player_id,
        "parameters": dict(cfg.last_resort_params),
        "duration": cfg.last_resort_duration,
    }


def build_fallback(cfg: FallbackConfig) -> Callable[[dict, int, int], list[dict]]:
    """Return a fallback_commands(game_state, team_id, my_player_id) function."""

    def fallback_commands(game_state: dict, team_id: int, my_player_id: int) -> list[dict]:
        ball = game_state.get("ball", {})
        ball_pos = ball.get("position", {"x": 0, "y": 0})
        players = game_state.get("players", [])
        possession_id = _possession_idx(ball)
        my_goal_x, opp_goal_x = get_goal_positions(team_id)

        me = next(
            (p for p in players if _player_idx(p) == my_player_id and _is_my_team(p, team_id)),
            None,
        )
        if not me:
            return [_cmd("SET_STANCE", my_player_id, team_id, {"stance": cfg.default_stance})]

        pos = me.get("position", {"x": 0, "y": 0})

        game_time = float(game_state.get("gameTime", 0) or 0)
        score_diff = get_score_diff(game_state, team_id)
        is_chasing = (score_diff < 0 and game_time > 150.0)
        is_defending_lead = (score_diff >= 2)

        press_dist = cfg.press_distance * 1.3 if is_chasing else cfg.press_distance
        press_intensity = min(1.0, max(cfg.press_intensity, 0.9)) if is_chasing else (
            min(cfg.press_intensity, 0.6) if is_defending_lead else cfg.press_intensity
        )
        support_sprint = False if is_defending_lead else cfg.support_sprint
        mark_tightness = "TIGHT" if is_defending_lead else cfg.mark_tightness

        if cfg.phase_logic:
            # 1. I have the ball
            if possession_id == my_player_id:
                return _on_ball(cfg, game_state, players, team_id, my_player_id, pos, my_goal_x, opp_goal_x)

            _, _, we_have_ball = get_possession_info(ball, players, team_id)

            # 2. Teammate has ball → support MOVE_TO
            if we_have_ball:
                return [_cmd("MOVE_TO", my_player_id, team_id,
                             {"target_x": opp_goal_x * cfg.support_x_factor,
                              "target_y": cfg.support_y, "sprint": support_sprint})]

            # 3. Opponent has ball / loose ball
            from state import is_nearest_to_ball
            my_team = [p for p in players if _is_my_team(p, team_id)]
            opponents = [p for p in players if not _is_my_team(p, team_id)]
            if is_nearest_to_ball(pos, my_player_id, my_team, ball_pos) and dist(pos, ball_pos) < press_dist:
                return [_cmd("PRESS_BALL", my_player_id, team_id,
                             {"intensity": press_intensity}, duration=cfg.press_duration)]

            if cfg.mark_threshold > 0:
                if opponents:
                    dangerous = min(opponents, key=lambda p: abs(p.get("position", {}).get("x", 0) - my_goal_x))
                    if abs(dangerous.get("position", {}).get("x", 0) - my_goal_x) < cfg.mark_threshold:
                        return [_cmd("MARK", my_player_id, team_id,
                                     {"target_player_id": _player_idx(dangerous),
                                      "tightness": mark_tightness}, duration=3)]

            # Corridor interception for off-ball midfielders/defenders when opponent is setting up a pass
            if possession_id is not None:
                opp_carrier = next((p for p in opponents if _player_idx(p) == possession_id), None)
                if opp_carrier:
                    fwd_opps = [
                        p for p in opponents
                        if _player_idx(p) != 0 and abs(p.get("position", {}).get("x", 0) - my_goal_x) < abs(opp_carrier.get("position", {}).get("x", 0) - my_goal_x) - 2.0
                    ]
                    if fwd_opps:
                        target_receiver = min(fwd_opps, key=lambda p: abs(p.get("position", {}).get("x", 0) - my_goal_x))
                        c_pos = opp_carrier.get("position", {})
                        r_pos = target_receiver.get("position", {})
                        corridor_x = (c_pos.get("x", 0) + r_pos.get("x", 0)) * 0.5
                        corridor_y = (c_pos.get("y", 0) + r_pos.get("y", 0)) * 0.5
                        if dist(pos, {"x": corridor_x, "y": corridor_y}) < 20.0:
                            return [_cmd("MOVE_TO", my_player_id, team_id,
                                         {"target_x": corridor_x, "target_y": corridor_y, "sprint": False})]

            # Default position
            tx, ty = _default_pos(cfg, my_goal_x, opp_goal_x, ball_pos)
            return [_cmd("MOVE_TO", my_player_id, team_id,
                          {"target_x": tx, "target_y": ty, "sprint": False})]

        # --- Standard (legacy) logic when phase_logic=False ---

        # --- We have the ball ---
        if possession_id == my_player_id:
            return _on_ball(cfg, game_state, players, team_id, my_player_id, pos, my_goal_x, opp_goal_x)

        # --- DEF: mark dangerous opponent ---
        if cfg.mark_threshold > 0:
            opponents = [p for p in players if not _is_my_team(p, team_id)]
            if opponents:
                dangerous = min(opponents, key=lambda p: abs(p.get("position", {}).get("x", 0) - my_goal_x))
                if abs(dangerous.get("position", {}).get("x", 0) - my_goal_x) < cfg.mark_threshold:
                    return [_cmd("MARK", my_player_id, team_id,
                                 {"target_player_id": _player_idx(dangerous),
                                  "tightness": mark_tightness}, duration=3)]

        # --- Teammate has ball → support run (forwards) ---
        if cfg.possession_action in ("SHOOT_OR_ADVANCE",):
            _, _, we_have_ball = get_possession_info(ball, players, team_id)
            if we_have_ball:
                return [_cmd("MOVE_TO", my_player_id, team_id,
                             {"target_x": opp_goal_x * cfg.support_x_factor,
                              "target_y": cfg.support_y, "sprint": support_sprint})]

        # --- Press if close to ball and opponent has it ---
        _, _, we_have_ball = get_possession_info(ball, players, team_id)
        if not we_have_ball and dist(pos, ball_pos) < press_dist:
            return [_cmd("PRESS_BALL", my_player_id, team_id,
                         {"intensity": press_intensity}, duration=cfg.press_duration)]

        # --- Default position ---
        tx, ty = _default_pos(cfg, my_goal_x, opp_goal_x, ball_pos)
        return [_cmd("MOVE_TO", my_player_id, team_id,
                      {"target_x": tx, "target_y": ty, "sprint": False})]

    return fallback_commands


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmd(cmd_type: str, pid: int, tid: int, params: dict, duration: int = 0) -> dict:
    return {"commandType": cmd_type, "playerId": pid, "teamId": tid,
            "parameters": params, "duration": duration}


def _on_ball(cfg, game_state, players, team_id, my_player_id, pos, my_goal_x, opp_goal_x):
    """Handle possession for all position types."""
    opponents = [p for p in players if not _is_my_team(p, team_id)]
    opp_gk = next((p for p in opponents if _player_idx(p) == 0), None)
    shoot_aim = get_far_post_aim(opp_gk.get("position", {}).get("y", 0.0), prefer_top=("T" in cfg.shoot_aim)) if opp_gk else cfg.shoot_aim

    if cfg.possession_action == "GK_DISTRIBUTE":
        if cfg.distribute_wide_ids:
            wide_teammates = [
                p for p in players
                if _is_my_team(p, team_id) and _player_idx(p) in cfg.distribute_wide_ids and _player_idx(p) != my_player_id
            ]
            if wide_teammates:
                unblocked = [
                    p for p in wide_teammates
                    if not is_lane_blocked(pos, p.get("position", {}), opponents, clearance=2.5)
                ]
                pool = unblocked if unblocked else wide_teammates
                def _openness(p):
                    p_pos = p.get("position", {})
                    d_opp = min([dist(p_pos, opp.get("position", {})) for opp in opponents], default=99.0)
                    return (d_opp, abs(p_pos.get("y", 0)))
                target = max(pool, key=_openness)
                return [_cmd("GK_DISTRIBUTE", my_player_id, team_id,
                             {"target_player_id": _player_idx(target), "method": "THROW"})]
        teammates = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) != my_player_id]
        if teammates:
            nearest = min(teammates, key=lambda p: dist(p.get("position", {}), pos))
            return [_cmd("GK_DISTRIBUTE", my_player_id, team_id,
                         {"target_player_id": _player_idx(nearest), "method": "THROW"})]
        return [_cmd("GK_DISTRIBUTE", my_player_id, team_id,
                     {"target_player_id": 1, "method": "THROW"})]

    if cfg.clear_when_pressured:
        in_own_third = (pos.get("x", 0) < -55.0 / 3.0) if team_id == 0 else (pos.get("x", 0) > 55.0 / 3.0)
        pressured = any(dist(p.get("position", {}), pos) < 5.0 for p in opponents)
        if in_own_third and pressured:
            wide_targets = [
                p for p in players
                if _is_my_team(p, team_id) and _player_idx(p) in (2, 3) and _player_idx(p) != my_player_id
            ]
            if not wide_targets:
                wide_targets = [
                    p for p in players
                    if _is_my_team(p, team_id) and _player_idx(p) not in (0, my_player_id)
                ]
            if wide_targets:
                target = min(wide_targets, key=lambda p: abs(p.get("position", {}).get("x", 0) - opp_goal_x))
                return [_cmd("PASS", my_player_id, team_id,
                             {"target_player_id": _player_idx(target), "type": "AERIAL"})]

    # THROUGH pass check: when opponents have >= 3 outfield players ahead of the ball and ST is behind last line
    outfield_opps = [p for p in opponents if _player_idx(p) != 0]
    opps_ahead = [
        p for p in outfield_opps
        if abs(p.get("position", {}).get("x", 0) - opp_goal_x) > abs(pos.get("x", 0) - opp_goal_x)
    ]
    st = next((p for p in players if _is_my_team(p, team_id) and _player_idx(p) == 4), None)
    if st and len(opps_ahead) >= 3 and my_player_id != 4:
        min_opp_dist = min([abs(p.get("position", {}).get("x", 0) - opp_goal_x) for p in outfield_opps], default=99.0)
        st_dist = abs(st.get("position", {}).get("x", 0) - opp_goal_x)
        if st_dist <= min_opp_dist + 3.0:
            return [_cmd("PASS", my_player_id, team_id, {"target_player_id": 4, "type": "THROUGH"})]

    if cfg.possession_action == "PASS":
        exclude = set(cfg.pass_exclude_ids) | {my_player_id}
        teammates = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) not in exclude]
        if teammates:
            unblocked = [
                p for p in teammates
                if not is_lane_blocked(pos, p.get("position", {}), opponents, clearance=2.5)
            ]
            pool = unblocked if unblocked else teammates
            target = min(pool, key=lambda p: dist(p.get("position", {}), pos))
            pass_t = "GROUND" if unblocked else "AERIAL"
            return [_cmd("PASS", my_player_id, team_id,
                         {"target_player_id": _player_idx(target), "type": pass_t})]
        return [_cmd("PASS", my_player_id, team_id,
                     {"target_player_id": 2, "type": "GROUND"})]

    if cfg.possession_action == "SHOOT_OR_PASS":
        if abs(pos.get("x", 0) - opp_goal_x) < cfg.shoot_threshold:
            return [_cmd("SHOOT", my_player_id, team_id,
                         {"aim_location": shoot_aim, "power": cfg.shoot_power})]
        forwards = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) in (3, 4)]
        if forwards:
            unblocked = [
                p for p in forwards
                if not is_lane_blocked(pos, p.get("position", {}), opponents, clearance=2.5)
            ]
            pool = unblocked if unblocked else forwards
            target = min(pool, key=lambda p: abs(p.get("position", {}).get("x", 0) - opp_goal_x))
            pass_t = "GROUND" if unblocked else "AERIAL"
            return [_cmd("PASS", my_player_id, team_id,
                         {"target_player_id": _player_idx(target), "type": pass_t})]
        return [_cmd("PASS", my_player_id, team_id,
                     {"target_player_id": 3, "type": "GROUND"})]

    if cfg.possession_action == "SHOOT_OR_ADVANCE":
        is_in_box = (abs(pos.get("x", 0) - opp_goal_x) <= 22.0) and (abs(pos.get("y", 0)) <= 16.0)
        if is_in_box or abs(pos.get("x", 0) - opp_goal_x) < cfg.shoot_threshold:
            return [_cmd("SHOOT", my_player_id, team_id,
                         {"aim_location": shoot_aim, "power": 0.95})]
        
        # Check if marked or defender in front
        d_opp = min([dist(pos, p.get("position", {})) for p in opponents], default=99.0)
        def _in_front(opp_pos):
            dx = (opp_pos.get("x", 0) - pos.get("x", 0)) * (1 if team_id == 0 else -1)
            dy = abs(opp_pos.get("y", 0) - pos.get("y", 0))
            return (0.0 < dx < 12.0) and (dy < 7.0)
        defender_in_front = any(_in_front(p.get("position", {})) for p in opponents)

        if d_opp < 8.5 or defender_in_front:
            # Pass to open teammate instead of running into defenders
            teammates = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) not in (0, my_player_id)]
            if teammates:
                unblocked = [
                    p for p in teammates
                    if not is_lane_blocked(pos, p.get("position", {}), opponents, clearance=2.5)
                ]
                pool = unblocked if unblocked else teammates
                target = max(pool, key=lambda p: min([dist(p.get("position", {}), o.get("position", {})) for o in opponents], default=99.0))
                pass_t = "GROUND" if unblocked else "AERIAL"
                return [_cmd("PASS", my_player_id, team_id,
                             {"target_player_id": _player_idx(target), "type": pass_t})]

        return [_cmd("MOVE_TO", my_player_id, team_id,
                     {"target_x": opp_goal_x * cfg.advance_x_factor,
                      "target_y": cfg.advance_y, "sprint": cfg.advance_sprint})]

    # Shouldn't reach here
    return [_cmd("SET_STANCE", my_player_id, team_id, {"stance": 0})]


def _default_pos(cfg, my_goal_x, opp_goal_x, ball_pos):
    """Calculate default x,y from config."""
    if cfg.default_x_ref == "my_goal":
        tx = my_goal_x * cfg.default_x_factor
    elif cfg.default_x_ref == "opp_goal":
        tx = opp_goal_x * cfg.default_x_factor
    elif cfg.default_x_ref == "ball_x":
        tx = ball_pos.get("x", 0) * cfg.default_x_factor
    else:
        tx = 0

    if cfg.default_y == "track_ball":
        ty = max(-10, min(10, ball_pos.get("y", 0) * 0.5))
    elif cfg.default_y == "track_ball_30":
        ty = ball_pos.get("y", 0) * 0.3
    else:
        ty = cfg.default_y

    return tx, ty
