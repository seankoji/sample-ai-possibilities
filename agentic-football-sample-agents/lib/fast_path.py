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
    dist,
    is_attacking_third,
    shot_blockers,
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
    
    # Fast path 1: I have the ball
    if possession_id == my_player_id:
        return _fast_path_with_ball(
            my_player_id, team_id, position_label, me, my_team,
            opponents, ball_pos, my_pos, my_goal_x, opp_goal_x
        )
    
    # Fast path 2: Ball is free and very close (< 5 units)
    if possession_id is None:
        dist_to_ball = dist(my_pos, ball_pos)
        if dist_to_ball < 5.0:
            # Instant intercept for free ball nearby
            return [{
                "commandType": "INTERCEPT",
                "playerId": my_player_id,
                "teamId": team_id,
                "parameters": {"aggressive": True},
                "duration": 2
            }]
    
    # Fast path 3: Opponent has ball very close (< 7 units) and I can press
    if possession_id is not None and role_rules and role_rules.may_press:
        ball_carrier = next((p for p in players if _player_idx(p) == possession_id), None)
        if ball_carrier and not _is_my_team(ball_carrier, team_id):
            carrier_pos = ball_carrier.get("position", ball_pos)
            dist_to_carrier = dist(my_pos, carrier_pos)
            if dist_to_carrier < 7.0:
                # Instant press on nearby opponent
                return [{
                    "commandType": "PRESS_BALL",
                    "playerId": my_player_id,
                    "teamId": team_id,
                    "parameters": {"intensity": 0.8},
                    "duration": 3
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
) -> list[dict]:
    """Fast decisions when I have the ball."""
    
    # GK with ball → instant distribute to nearest outfield teammate
    if my_player_id == 0:
        outfield = [p for p in my_team if _player_idx(p) != 0]
        if outfield:
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
    
    # Forward in attacking third with clear shot → instant shoot
    if position_label in ("FWD1", "FWD2", "FWD"):
        in_att_third = is_attacking_third(my_pos.get("x", 0), team_id)
        if in_att_third:
            blockers = shot_blockers(my_pos, opp_goal_x, opponents)
            if blockers < 2:
                # Clear shot - take it immediately
                # Aim based on my position (if left side, aim far right corner and vice versa)
                my_y = my_pos.get("y", 0)
                aim = "TR" if my_y < 0 else "TL"  # Aim far post
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
    
    # Under immediate pressure (opponent < 5 units) → instant pass to best teammate
    nearest_opp_dist = min(
        [dist(p.get("position", {}), my_pos) for p in opponents],
        default=99.0
    )
    if nearest_opp_dist < 5.0:
        # Find safest pass - teammate furthest from opponents
        outfield = [p for p in my_team if _player_idx(p) != my_player_id and _player_idx(p) != 0]
        if outfield:
            def safety_score(teammate):
                tm_pos = teammate.get("position", {})
                # Higher score = better (far from opponents, ahead of ball)
                min_opp_dist = min(
                    [dist(p.get("position", {}), tm_pos) for p in opponents],
                    default=0
                )
                forward_bonus = 5.0 if abs(tm_pos.get("x", 0) - opp_goal_x) < abs(my_pos.get("x", 0) - opp_goal_x) else 0
                return min_opp_dist + forward_bonus
            
            best_target = max(outfield, key=safety_score)
            target_dist = dist(best_target.get("position", {}), my_pos)
            pass_type = "THROUGH" if target_dist > 20 else "GROUND"
            
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
    
    # Ball possession but no obvious instant action - use LLM
    return None
