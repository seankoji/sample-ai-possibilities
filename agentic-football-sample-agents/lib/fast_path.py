"""Fast-path programmatic reactions for instant decision-making.

Handles obvious situations that don't require LLM inference:
- GK with ball → instant distribute
- Player with ball in shooting position → instant shoot
- Ball very close and free → instant intercept
- Opponent with ball very close → instant press

Reduces latency from 400-600ms (LLM) to <10ms (programmatic).
"""

from __future__ import annotations
from typing import TYPE_CHECKING
import math

if TYPE_CHECKING:
    from rules import RoleRules

from state import (
    _player_idx,
    _is_my_team,
    _possession_idx,
    get_goal_positions,
    get_possession_info,
    dist,
    is_attacking_third,
    shot_blockers,
    is_nearest_to_ball,
    get_score_diff,
    is_lane_blocked,
)


def fast_path_decision(
    game_state: dict,
    team_id: int,
    my_player_id: int,
    position_label: str,
    role_rules: RoleRules | None = None,
) -> list[dict] | None:
    """Return instant command if situation is obvious, else None (use LLM).
    
    Returns None to indicate "use LLM" for complex decisions.
    Returns list[dict] for instant programmatic reactions.
    """
    players = game_state.get("players", [])
    my_team = [p for p in players if _is_my_team(p, team_id)]
    opponents = [p for p in players if not _is_my_team(p, team_id)]
    me = next((p for p in my_team if _player_idx(p) == my_player_id), None)
    
    if not me:
        return None
    
    ball = game_state.get("ball", {})
    ball_pos = ball.get("position", {"x": 0, "y": 0})
    my_pos = me.get("position", {"x": 0, "y": 0})
    possession_id = _possession_idx(ball)
    my_goal_x, opp_goal_x = get_goal_positions(team_id)
    
    my_stamina = me.get("stamina", 100)
    can_sprint = (my_stamina >= 30)
    press_intensity = 0.85 if can_sprint else 0.45

    score_diff = get_score_diff(game_state, team_id)
    game_time = float(game_state.get("gameTime", 0) or 0)
    is_protecting_lead = (score_diff >= 2) or (score_diff >= 1 and game_time > 120.0)
    cb_anchor_x = my_goal_x * (0.75 if is_protecting_lead else 0.65)

    # Fast path 0: Kickoff formation positioning & compact defensive wall
    play_mode = str(game_state.get("playMode", "")).upper()
    if "KICK" in play_mode and "OFF" in play_mode:
        if position_label == "GK" or my_player_id == 0:
            return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": my_goal_x * 0.95, "target_y": 0.0, "sprint": False}, "duration": 0}]
        elif position_label in ("CB", "DEF"):
            return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": cb_anchor_x, "target_y": 0.0, "sprint": False}, "duration": 0}]
        elif position_label == "LM":
            target_x = my_goal_x * (0.35 if is_protecting_lead else 0.25)
            return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": target_x, "target_y": -15.0, "sprint": False}, "duration": 0}]
        elif position_label == "RM":
            target_x = my_goal_x * (0.35 if is_protecting_lead else 0.25)
            return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": target_x, "target_y": 15.0, "sprint": False}, "duration": 0}]
        elif position_label in ("ST", "FWD", "FWD1", "FWD2"):
            return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": 0.0, "target_y": 0.0, "sprint": False}, "duration": 0}]

    # Fast path 1: I have the ball
    if possession_id == my_player_id:
        return _fast_path_with_ball(
            my_player_id, team_id, position_label, me, my_team,
            opponents, ball_pos, my_pos, my_goal_x, opp_goal_x, can_sprint
        )
    
    # Fast path 2: Free Ball — ONLY the nearest outfield teammate chases. Others get into receiving pockets!
    if possession_id is None:
        dist_to_ball = dist(my_pos, ball_pos)
        i_am_nearest = is_nearest_to_ball(my_pos, my_player_id, my_team, ball_pos)
        if i_am_nearest and dist_to_ball < 8.0:
            return [{
                "commandType": "INTERCEPT",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {"aggressive": True},
                "duration": 2
            }]
        elif not i_am_nearest and my_player_id != 0:
            # Teammate is chasing and will get there first — stand on box corners/middle to receive the pass!
            if position_label in ("CB", "DEF"):
                return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": cb_anchor_x, "target_y": 0.0, "sprint": False}, "duration": 0}]
            elif position_label == "LM":
                return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": opp_goal_x * 0.50, "target_y": -13.0, "sprint": False}, "duration": 0}]
            elif position_label == "RM":
                return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": opp_goal_x * 0.50, "target_y": 13.0, "sprint": False}, "duration": 0}]
            elif position_label in ("ST", "FWD", "FWD1", "FWD2"):
                target_y = 0.0 if position_label in ("ST", "FWD") else (-6.0 if position_label == "FWD1" else 6.0)
                return [{"commandType": "MOVE_TO", "playerId": my_player_id, "teamId": team_id, "parameters": {"target_x": opp_goal_x * 0.58, "target_y": target_y, "sprint": can_sprint}, "duration": 0}]

    # Fast path 3: Teammate has ball → Receiving on Box Corners / Opposition Half on GK (<5ms)
    _, _, we_have_ball = get_possession_info(ball, players, team_id)
    if we_have_ball and possession_id != my_player_id:
        in_attack = is_attacking_third(ball_pos.get("x", 0), team_id)
        gk_has_ball = (possession_id == 0)
        
        if position_label == "GK" or my_player_id == 0:
            # Sweeper Keeper: Step up to box edge when team attacks, goal line when defending
            gk_x = my_goal_x * (0.72 if in_attack else 0.95)
            return [{
                "commandType": "MOVE_TO",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {"target_x": gk_x, "target_y": ball_pos.get("y", 0) * 0.25, "sprint": False},
                "duration": 0
            }]
        elif position_label in ("CB", "DEF"):
            # Rest-Defense Anchor: Hold compact shape in own half
            cb_x = my_goal_x * (0.55 if in_attack else (0.75 if is_protecting_lead else 0.65))
            return [{
                "commandType": "MOVE_TO",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {
                    "target_x": cb_x,
                    "target_y": 0.0,
                    "sprint": False
                },
                "duration": 0
            }]
        elif position_label in ("LM", "RM"):
            flank_y = -13.0 if position_label == "LM" else 13.0
            if gk_has_ball:
                # When goalie gets ball, all mid players sprint into opposition half!
                return [{
                    "commandType": "MOVE_TO",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_x": opp_goal_x * 0.45,
                        "target_y": flank_y,
                        "sprint": can_sprint
                    },
                    "duration": 0
                }]
            is_ball_my_flank = (position_label == "LM" and ball_pos.get("y", 0) < 0) or (position_label == "RM" and ball_pos.get("y", 0) >= 0)
            if in_attack and not is_ball_my_flank:
                # Rest-Defense Screen on opposite flank: sit at midfield to kill clearances
                return [{
                    "commandType": "MOVE_TO",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_x": 0.0,
                        "target_y": -8.0 if position_label == "LM" else 8.0,
                        "sprint": False
                    },
                    "duration": 0
                }]
            else:
                # Stand on corner of the box to receive cleanly
                target_x = opp_goal_x * (0.55 if in_attack else 0.50)
                return [{
                    "commandType": "MOVE_TO",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_x": target_x,
                        "target_y": flank_y,
                        "sprint": False
                    },
                    "duration": 0
                }]
        elif position_label in ("ST", "FWD", "FWD1", "FWD2"):
            if gk_has_ball:
                # Striker sprints deep into opposition half for long GK delivery!
                target_y = 0.0 if position_label in ("ST", "FWD") else (-6.0 if position_label == "FWD1" else 6.0)
                return [{
                    "commandType": "MOVE_TO",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_x": opp_goal_x * 0.65,
                        "target_y": target_y,
                        "sprint": can_sprint
                    },
                    "duration": 0
                }]
            # Middle of the box / central "D"
            target_x = opp_goal_x * (0.65 if in_attack else 0.58)
            target_y = 0.0 if position_label in ("ST", "FWD") else (-6.0 if position_label == "FWD1" else 6.0)
            return [{
                "commandType": "MOVE_TO",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {
                    "target_x": target_x,
                    "target_y": target_y,
                    "sprint": can_sprint
                },
                "duration": 0
            }]

    # Fast path 4: Defensive marking for CB/DEF when opponent is in our defensive territory
    if not we_have_ball and role_rules and getattr(role_rules, "own_half_only", False):
        if opponents:
            dangerous = min(opponents, key=lambda p: abs(p.get("position", {}).get("x", 0) - my_goal_x))
            dist_to_my_goal = abs(dangerous.get("position", {}).get("x", 0) - my_goal_x)
            # Dangerous opponent within 35 units of our goal line
            if dist_to_my_goal < 35.0:
                return [{
                    "commandType": "MARK",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_player_id": _player_idx(dangerous),
                        "tightness": "TIGHT"
                    },
                    "duration": 3
                }]

    # Fast path 5: Opponent has ball — ONLY nearest outfield teammate presses within 6.5m (prevents overcommitment)
    if possession_id is not None and not we_have_ball and role_rules and getattr(role_rules, "may_press", False):
        ball_carrier = next((p for p in players if _player_idx(p) == possession_id), None)
        if ball_carrier and not _is_my_team(ball_carrier, team_id):
            carrier_pos = ball_carrier.get("position", ball_pos)
            dist_to_carrier = dist(my_pos, carrier_pos)
            i_am_nearest_presser = is_nearest_to_ball(my_pos, my_player_id, my_team, carrier_pos)
            if i_am_nearest_presser and dist_to_carrier < 6.5:
                # Single designated presser in tackling range
                return [{
                    "commandType": "PRESS_BALL",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {"intensity": press_intensity},
                    "duration": 3
                }]

    # Fast path 6: Midfield passing lane corridor interception
    if possession_id is not None and not we_have_ball and position_label in ("LM", "RM", "MID"):
        opp_carrier = next((p for p in opponents if _player_idx(p) == possession_id), None)
        if opp_carrier:
            c_pos = opp_carrier.get("position", ball_pos)
            fwd_opps = [
                p for p in opponents
                if _player_idx(p) != 0 and abs(p.get("position", {}).get("x", 0) - my_goal_x) < abs(c_pos.get("x", 0) - my_goal_x) - 2.0
            ]
            if fwd_opps:
                target_receiver = min(fwd_opps, key=lambda p: abs(p.get("position", {}).get("x", 0) - my_goal_x))
                r_pos = target_receiver.get("position", {})
                corridor_x = (c_pos.get("x", 0) + r_pos.get("x", 0)) * 0.5
                corridor_y = (c_pos.get("y", 0) + r_pos.get("y", 0)) * 0.5
                if dist(my_pos, {"x": corridor_x, "y": corridor_y}) < 15.0:
                    return [{
                        "commandType": "MOVE_TO",
                        "playerId": my_player_id,
                        "teamId": team_id,
                        "parameters": {
                            "target_x": corridor_x,
                            "target_y": corridor_y,
                            "sprint": False
                        },
                        "duration": 0
                    }]

    # No fast path applies - use LLM for complex decision
    return None


def _fast_path_with_ball(
    my_player_id: int,
    team_id: int,
    position_label: str,
    me: dict,
    my_team: list,
    opponents: list,
    ball_pos: dict,
    my_pos: dict,
    my_goal_x: float,
    opp_goal_x: float,
    can_sprint: bool = True,
) -> list[dict]:
    """Fast decisions when I have the ball."""
    
    # GK with ball → long kick if >= 3 opponents in our half, else open distribution
    if my_player_id == 0:
        outfield = [p for p in my_team if _player_idx(p) != 0]
        if outfield:
            opps_in_our_half = sum(
                1 for p in opponents
                if (p.get("position", {}).get("x", 0) < 0 if team_id == 0 else p.get("position", {}).get("x", 0) > 0)
            )
            if opps_in_our_half >= 3:
                # 3+ opponents pressing in our half -> play long over the press to forwards/wingers in opposition half
                forward_targets = [
                    p for p in outfield
                    if (p.get("position", {}).get("x", 0) > 0 if team_id == 0 else p.get("position", {}).get("x", 0) < 0)
                ]
                if not forward_targets:
                    forward_targets = outfield
                target = max(forward_targets, key=lambda p: abs(p.get("position", {}).get("x", 0) - my_goal_x))
                return [{
                    "commandType": "GK_DISTRIBUTE",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_player_id": _player_idx(target),
                        "method": "KICK"
                    },
                    "duration": 0
                }]
            else:
                nearest = min(outfield, key=lambda p: dist(p.get("position", {}), my_pos))
                return [{
                    "commandType": "GK_DISTRIBUTE",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_player_id": _player_idx(nearest),
                        "method": "THROW" if dist(nearest.get("position", {}), my_pos) < 25 else "KICK"
                    },
                    "duration": 0
                }]

    # Defender under pressure in own third → instant aerial clearance to flank
    in_own_third = (my_pos.get("x", 0) < -55.0 / 3.0) if team_id == 0 else (my_pos.get("x", 0) > 55.0 / 3.0)
    nearest_opp_dist = min(
        [dist(p.get("position", {}), my_pos) for p in opponents],
        default=99.0
    )
    if in_own_third and nearest_opp_dist < 5.0 and position_label in ("CB", "DEF"):
        wide_targets = [
            p for p in my_team
            if _player_idx(p) in (2, 3) and _player_idx(p) != my_player_id
        ]
        if not wide_targets:
            wide_targets = [
                p for p in my_team
                if _player_idx(p) not in (0, my_player_id)
            ]
        if wide_targets:
            target = min(wide_targets, key=lambda p: abs(p.get("position", {}).get("x", 0) - opp_goal_x))
            return [{
                "commandType": "PASS",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {
                    "target_player_id": _player_idx(target),
                    "type": "AERIAL"
                },
                "duration": 0
            }]

    # Forward in attacking third with clear shot → instant far-post shoot
    if position_label in ("FWD1", "FWD2", "FWD", "ST"):
        in_att_third = is_attacking_third(my_pos.get("x", 0), team_id)
        if in_att_third:
            blockers = shot_blockers(my_pos, opp_goal_x, opponents)
            if blockers < 2:
                opp_gk = next((p for p in opponents if _player_idx(p) == 0), None)
                if opp_gk:
                    gk_y = opp_gk.get("position", {}).get("y", 0.0)
                    aim = "TR" if gk_y < 0 else "TL"
                else:
                    my_y = my_pos.get("y", 0)
                    aim = "TR" if my_y < 0 else "TL"
                return [{
                    "commandType": "SHOOT",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "aim_location": aim,
                        "power": 0.9
                    },
                    "duration": 0
                }]

    # Overload to Isolate: When opponents cluster on my flank, switch play aerially to opposite isolated winger
    if abs(my_pos.get("y", 0)) > 12.0:
        opps_on_flank = sum(1 for p in opponents if p.get("position", {}).get("y", 0) * my_pos.get("y", 0) > 0)
        if opps_on_flank >= 2:
            opposite_winger = next(
                (p for p in my_team if _player_idx(p) in (2, 3) and _player_idx(p) != my_player_id and p.get("position", {}).get("y", 0) * my_pos.get("y", 0) < -20.0),
                None
            )
            if opposite_winger:
                return [{
                    "commandType": "PASS",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_player_id": _player_idx(opposite_winger),
                        "type": "AERIAL"
                    },
                    "duration": 0
                }]

    # Third-Man Combination: When ST holds up ball in attacking half, layoff through-pass to advancing winger
    if position_label in ("ST", "FWD", "FWD2") and is_attacking_third(my_pos.get("x", 0), team_id):
        wingers = [p for p in my_team if _player_idx(p) in (2, 3) and _player_idx(p) != my_player_id]
        if wingers:
            open_winger = max(wingers, key=lambda w: min([dist(w.get("position", {}), o.get("position", {})) for o in opponents], default=99.0))
            w_dist = dist(my_pos, open_winger.get("position", {}))
            if w_dist < 28.0 and not is_lane_blocked(my_pos, open_winger.get("position", {}), opponents, clearance=2.0):
                return [{
                    "commandType": "PASS",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_player_id": _player_idx(open_winger),
                        "type": "THROUGH" if w_dist > 14.0 else "GROUND"
                    },
                    "duration": 0
                }]

    # Winger on flank in attacking third → aerial cross into box for central forward
    if position_label in ("LM", "RM", "MID", "FWD1") and is_attacking_third(my_pos.get("x", 0), team_id) and abs(my_pos.get("y", 0)) > 12.0:
        st = next((p for p in my_team if _player_idx(p) in (3, 4) and _player_idx(p) != my_player_id), None)
        if st:
            st_pos = st.get("position", {})
            if abs(st_pos.get("x", 0) - opp_goal_x) < 25.0 and abs(st_pos.get("y", 0)) < 15.0:
                return [{
                    "commandType": "PASS",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_player_id": _player_idx(st),
                        "type": "AERIAL"
                    },
                    "duration": 0
                }]

    # Midfield counter-attack quick-release: When MID/LM/RM has ball, look for through-ball to forward ST
    if position_label in ("LM", "RM", "MID") and not is_attacking_third(my_pos.get("x", 0), team_id):
        st = next((p for p in my_team if _player_idx(p) in (3, 4) and _player_idx(p) != my_player_id), None)
        if st:
            st_pos = st.get("position", {})
            st_dist_goal = abs(st_pos.get("x", 0) - opp_goal_x)
            my_dist_goal = abs(my_pos.get("x", 0) - opp_goal_x)
            if st_dist_goal < my_dist_goal - 5.0:
                st_dist = dist(my_pos, st_pos)
                pass_type = "THROUGH" if st_dist > 15.0 else "GROUND"
                return [{
                    "commandType": "PASS",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_player_id": _player_idx(st),
                        "type": pass_type
                    },
                    "duration": 0
                }]

    # Under pressure or marked (opponent < 8.5m or defender directly in front < 12m) → instant pass to open teammate
    def is_in_forward_cone(opp_pos):
        dx = (opp_pos.get("x", 0) - my_pos.get("x", 0)) * (1 if team_id == 0 else -1)
        dy = abs(opp_pos.get("y", 0) - my_pos.get("y", 0))
        return (0.0 < dx < 12.0) and (dy < 7.0)

    defender_in_front = any(is_in_forward_cone(p.get("position", {})) for p in opponents)
    is_pressured_or_marked = (nearest_opp_dist < 8.5) or defender_in_front

    if is_pressured_or_marked:
        outfield = [p for p in my_team if _player_idx(p) != my_player_id and _player_idx(p) != 0]
        if outfield:
            def safety_score(teammate):
                tm_pos = teammate.get("position", {})
                min_opp_dist = min(
                    [dist(p.get("position", {}), tm_pos) for p in opponents],
                    default=0
                )
                forward_bonus = 5.0 if abs(tm_pos.get("x", 0) - opp_goal_x) < abs(my_pos.get("x", 0) - opp_goal_x) else 0
                return min_opp_dist + forward_bonus
            
            best_target = max(outfield, key=safety_score)
            target_dist = dist(best_target.get("position", {}), my_pos)
            pass_type = "AERIAL" if nearest_opp_dist < 5.0 else ("THROUGH" if target_dist > 20 else "GROUND")
            
            return [{
                "commandType": "PASS",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {
                    "target_player_id": _player_idx(best_target),
                    "type": pass_type
                },
                "duration": 0
            }]
    
    # Unpressured advance / through-ball transition
    if not is_pressured_or_marked:
        if position_label in ("ST", "FWD", "FWD1", "FWD2"):
            # Move to middle of the box / central "D"
            return [{
                "commandType": "MOVE_TO",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {
                    "target_x": opp_goal_x * 0.65,
                    "target_y": 0.0,
                    "sprint": can_sprint
                },
                "duration": 0
            }]
        elif position_label in ("LM", "RM", "MID"):
            st = next((p for p in my_team if _player_idx(p) in (3, 4) and _player_idx(p) != my_player_id), None)
            if st and not is_lane_blocked(my_pos, st.get("position", {}), opponents, clearance=2.0):
                st_dist = dist(my_pos, st.get("position", {}))
                return [{
                    "commandType": "PASS",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {
                        "target_player_id": _player_idx(st),
                        "type": "THROUGH" if st_dist > 15.0 else "GROUND"
                    },
                    "duration": 0
                }]
            flank_y = -13.0 if (position_label == "LM" or my_pos.get("y", 0) < 0) else 13.0
            return [{
                "commandType": "MOVE_TO",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {
                    "target_x": opp_goal_x * 0.55,
                    "target_y": flank_y,
                    "sprint": can_sprint
                },
                "duration": 0
            }]

    return None
