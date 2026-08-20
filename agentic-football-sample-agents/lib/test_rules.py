"""Unit tests for tactical rules and sanitizers in lib/rules.py."""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from test_helpers import (
    mock_agentcore,
    GAME_STATE,
    GAME_STATE_NO_BLOCKERS,
    GAME_STATE_TWO_BLOCKERS,
    GAME_STATE_OPPOSITE_FLANK,
    GAME_STATE_LOW_STAMINA,
    GAME_STATE_TIE_BREAK,
    TEAM_ID,
)
mock_agentcore()

from rules import RoleRules, sanitize_commands, _validate_schema
from state import (
    shot_blockers,
    is_nearest_to_ball,
    is_attacking_third,
    ball_side,
    summarize_state,
)


def test_state_metrics():
    print("=== TEST STATE METRICS ===")
    # is_attacking_third
    assert is_attacking_third(20.0, team_id=0) is True
    assert is_attacking_third(10.0, team_id=0) is False
    assert is_attacking_third(-20.0, team_id=1) is True
    assert is_attacking_third(-10.0, team_id=1) is False

    # ball_side
    assert ball_side(-10.0) == "left"
    assert ball_side(10.0) == "right"
    assert ball_side(0.0) == "center"

    # shot_blockers
    # In GAME_STATE_NO_BLOCKERS, player 4 at (35, 0) shooting toward (55, 0)
    p4_pos = {"x": 35.0, "y": 0.0}
    opps_no_blockers = [p for p in GAME_STATE_NO_BLOCKERS["players"] if p.get("teamCode") == "away"]
    assert shot_blockers(p4_pos, 55.0, opps_no_blockers) == 0

    # In GAME_STATE_TWO_BLOCKERS, 2 opponents in cone
    opps_two_blockers = [p for p in GAME_STATE_TWO_BLOCKERS["players"] if p.get("teamCode") == "away"]
    assert shot_blockers(p4_pos, 55.0, opps_two_blockers) == 2

    # is_nearest_to_ball tie-break
    ball_pos = GAME_STATE_TIE_BREAK["ball"]["position"]
    p1_pos = {"x": 10.0, "y": 0.0}
    p2_pos = {"x": 10.5, "y": 0.0}
    tm = [p for p in GAME_STATE_TIE_BREAK["players"] if p.get("teamCode") == "home"]
    # Player 1 (id 1) should be nearest due to lower ID in tie-break zone (within 1.0 unit)
    assert is_nearest_to_ball(p1_pos, 1, tm, ball_pos) is True
    assert is_nearest_to_ball(p2_pos, 2, tm, ball_pos) is False

    # GK (player 0) is never nearest outfield teammate
    p0_pos = {"x": -50.0, "y": 0.0}
    assert is_nearest_to_ball(p0_pos, 0, tm, ball_pos) is False

    # summarize_state with tactical=True
    summary = summarize_state(GAME_STATE, TEAM_ID, 2, "LM", tactical=True)
    assert ">>> YOU (LM, id=2):" in summary
    assert "blockers=" in summary
    assert "amNearestToBall=" in summary

    # summarize_state with tactical=False (default unchanged)
    summary_default = summarize_state(GAME_STATE, TEAM_ID, 2, "LM", tactical=False)
    assert ">>> YOU (LM, id=2):" not in summary_default
    assert ">>> YOUR PLAYER (LM, id=2):" in summary_default

    print("  State metrics tests PASSED")
    print()


def test_schema_validation():
    print("=== TEST SCHEMA VALIDATION ===")
    # Valid commands
    assert _validate_schema({"commandType": "SHOOT", "parameters": {"aim_location": "TL", "power": 0.8}}, 4) is True
    assert _validate_schema({"commandType": "PASS", "parameters": {"target_player_id": 2, "type": "GROUND"}}, 4) is True
    assert _validate_schema({"commandType": "MOVE_TO", "parameters": {"target_x": 10.0, "target_y": -5.0, "sprint": True}}, 4) is True
    assert _validate_schema({"commandType": "PRESS_BALL", "parameters": {"intensity": 0.7}}, 4) is True
    assert _validate_schema({"commandType": "MARK", "parameters": {"target_player_id": 1, "tightness": "TIGHT"}}, 4) is True
    assert _validate_schema({"commandType": "SET_STANCE", "parameters": {"stance": 1}}, 4) is True

    # Invalid commands
    assert _validate_schema({"commandType": "SHOOT", "parameters": {"aim_location": "INVALID", "power": 0.8}}, 4) is False
    assert _validate_schema({"commandType": "SHOOT", "parameters": {"aim_location": "TL", "power": 1.5}}, 4) is False
    assert _validate_schema({"commandType": "PASS", "parameters": {"target_player_id": 4}}, 4) is False  # self-pass
    assert _validate_schema({"commandType": "PASS", "parameters": {"target_player_id": 6}}, 4) is False  # out of range
    assert _validate_schema({"commandType": "PRESS_BALL", "parameters": {"intensity": -0.1}}, 4) is False
    assert _validate_schema({"commandType": "MOVE_TO", "parameters": {"target_x": "bad"}}, 4) is False
    assert _validate_schema({"commandType": "SET_STANCE", "parameters": {"stance": 5}}, 4) is False

    print("  Schema validation tests PASSED")
    print()


def test_anti_swarm():
    print("=== TEST ANTI-SWARM ===")
    cb_rules = RoleRules(label="CB", own_half_only=True, may_press=True, shoot_gate=True)

    # 1. State with opponent in our half (x <= 0)
    # Player 1 (DEF/CB) tries to PRESS_BALL -> should be stripped and substituted with MARK nearest opponent in own half
    state_with_opp_in_half = json.loads(json.dumps(GAME_STATE))
    state_with_opp_in_half["players"].append({
        "agentId": "agentId_1", "teamCode": "away", "position": {"x": -25.0, "y": 5.0},
    })
    cmds = [{"commandType": "PRESS_BALL", "parameters": {"intensity": 0.8}}]
    sanitized = sanitize_commands(cmds, state_with_opp_in_half, TEAM_ID, 1, cb_rules)

    assert len(sanitized) == 1
    assert sanitized[0]["commandType"] == "MARK"
    assert sanitized[0]["playerId"] == 1
    assert sanitized[0]["teamId"] == TEAM_ID
    assert sanitized[0]["duration"] == 3
    print(f"  Non-nearest player PRESS_BALL substituted with: {sanitized[0]['commandType']} {sanitized[0]['parameters']}")

    # 2. State with NO opponents in our half -> fallback to MOVE_TO home coordinate
    sanitized_no_opp = sanitize_commands(cmds, GAME_STATE, TEAM_ID, 1, cb_rules)
    assert len(sanitized_no_opp) == 1
    assert sanitized_no_opp[0]["commandType"] == "MOVE_TO"
    assert sanitized_no_opp[0]["parameters"]["sprint"] is False
    print(f"  Non-nearest player with no mark target -> MOVE_TO home: {sanitized_no_opp[0]['parameters']}")

    # 3. Player 3 (nearest) tries to PRESS_BALL on same flank -> should remain PRESS_BALL
    state_rm_flank = json.loads(json.dumps(GAME_STATE))
    state_rm_flank["ball"]["position"] = {"x": 15.3, "y": 10.0}
    state_rm_flank["players"][3]["position"] = {"x": 15.0, "y": 10.0}
    rm_rules = RoleRules(label="RM", may_press=True, shoot_gate=True, home_y=15.0)
    cmds3 = [{"commandType": "PRESS_BALL", "parameters": {"intensity": 0.8}}]
    sanitized3 = sanitize_commands(cmds3, state_rm_flank, TEAM_ID, 3, rm_rules)
    assert len(sanitized3) == 1
    assert sanitized3[0]["commandType"] == "PRESS_BALL"
    print("  Nearest player PRESS_BALL kept")

    # 4. GK (may_press=False) tries to PRESS_BALL -> should be stripped
    gk_rules = RoleRules(label="GK", box_only=True, may_press=False, shoot_gate=True)
    cmds_gk = [{"commandType": "PRESS_BALL", "parameters": {"intensity": 0.8}}]
    sanitized_gk = sanitize_commands(cmds_gk, state_with_opp_in_half, TEAM_ID, 0, gk_rules)
    assert len(sanitized_gk) == 1
    assert sanitized_gk[0]["commandType"] == "MARK"
    print("  GK PRESS_BALL stripped")

    print("  Anti-swarm tests PASSED")
    print()


def test_shot_discipline():
    print("=== TEST SHOT DISCIPLINE ===")
    st_rules = RoleRules(label="ST", may_press=True, shoot_gate=True)

    # 1. Clear shot in attacking third with 0 blockers -> SHOOT is kept
    cmds = [{"commandType": "SHOOT", "parameters": {"aim_location": "TR", "power": 0.85}}]
    sanitized = sanitize_commands(cmds, GAME_STATE_NO_BLOCKERS, TEAM_ID, 4, st_rules)
    assert len(sanitized) == 1
    assert sanitized[0]["commandType"] == "SHOOT"
    print("  0 blockers in attacking third -> SHOOT kept")

    # 2. Blocked shot in attacking third with 2 blockers -> SHOOT substituted with PASS
    sanitized_blocked = sanitize_commands(cmds, GAME_STATE_TWO_BLOCKERS, TEAM_ID, 4, st_rules)
    assert len(sanitized_blocked) == 1
    assert sanitized_blocked[0]["commandType"] == "PASS"
    assert sanitized_blocked[0]["parameters"]["type"] == "GROUND"
    print(f"  2 blockers -> SHOOT substituted with PASS to P{sanitized_blocked[0]['parameters']['target_player_id']}")

    # 3. SHOOT outside attacking third (e.g. from x=10) -> SHOOT substituted with PASS
    state_midfield = json.loads(json.dumps(GAME_STATE_NO_BLOCKERS))
    for p in state_midfield["players"]:
        if p["agentId"] == "agentId_4":
            p["position"] = {"x": 10.0, "y": 0.0}
    sanitized_mid = sanitize_commands(cmds, state_midfield, TEAM_ID, 4, st_rules)
    assert len(sanitized_mid) == 1
    assert sanitized_mid[0]["commandType"] == "PASS"
    print("  Outside attacking third -> SHOOT substituted with PASS")

    print("  Shot discipline tests PASSED")
    print()


def test_role_boundaries():
    print("=== TEST ROLE BOUNDARIES ===")
    # CB: own_half_only clamps target_x to 0.0 for team 0
    cb_rules = RoleRules(label="CB", own_half_only=True, may_press=True, shoot_gate=True)
    cmds_cb = [{"commandType": "MOVE_TO", "parameters": {"target_x": 25.0, "target_y": 0.0, "sprint": False}}]
    sanitized_cb = sanitize_commands(cmds_cb, GAME_STATE, TEAM_ID, 1, cb_rules)
    assert len(sanitized_cb) == 1
    assert sanitized_cb[0]["parameters"]["target_x"] == 0.0
    print("  CB target_x > 0 clamped to 0.0")

    # GK: box_only clamps target_x to [-55, -40] and target_y to [-20, 20]
    gk_rules = RoleRules(label="GK", box_only=True, may_press=False, shoot_gate=True)
    cmds_gk = [{"commandType": "MOVE_TO", "parameters": {"target_x": -10.0, "target_y": 30.0, "sprint": True}}]
    sanitized_gk = sanitize_commands(cmds_gk, GAME_STATE, TEAM_ID, 0, gk_rules)
    assert len(sanitized_gk) == 1
    assert sanitized_gk[0]["parameters"]["target_x"] == -40.0
    assert sanitized_gk[0]["parameters"]["target_y"] == 20.0
    print("  GK target_x and target_y clamped to box region")

    print("  Role boundaries tests PASSED")
    print()


def test_stamina_and_flank():
    print("=== TEST STAMINA AND FLANK ===")
    # Low stamina (stamina=25 < 30)
    lm_rules = RoleRules(label="LM", may_press=True, shoot_gate=True, home_y=-15.0)
    cmds_move = [{"commandType": "MOVE_TO", "parameters": {"target_x": 10.0, "target_y": -15.0, "sprint": True}}]
    sanitized_move = sanitize_commands(cmds_move, GAME_STATE_LOW_STAMINA, TEAM_ID, 2, lm_rules)
    assert len(sanitized_move) == 1
    assert sanitized_move[0]["parameters"]["sprint"] is False
    print("  Low stamina forced sprint=False")

    # When nearest player has low stamina and tries to PRESS_BALL -> stripped
    state_nearest_low_stam = json.loads(json.dumps(GAME_STATE_LOW_STAMINA))
    state_nearest_low_stam["ball"]["position"] = {"x": 5.0, "y": -15.0}
    cmds_press = [{"commandType": "PRESS_BALL", "parameters": {"intensity": 0.7}}]
    sanitized_press = sanitize_commands(cmds_press, state_nearest_low_stam, TEAM_ID, 2, lm_rules)
    assert len(sanitized_press) == 0
    print("  Low stamina stripped PRESS_BALL")

    # Opposite flank check: LM (home_y=-15) when ball is at y=20 (right flank)
    sanitized_flank = sanitize_commands(cmds_press, GAME_STATE_OPPOSITE_FLANK, TEAM_ID, 2, lm_rules)
    assert len(sanitized_flank) == 1
    assert sanitized_flank[0]["commandType"] == "MOVE_TO"
    assert sanitized_flank[0]["parameters"]["target_y"] == -15.0
    assert sanitized_flank[0]["parameters"]["sprint"] is False
    print("  Opposite flank substituted PRESS_BALL with jog MOVE_TO home flank")

    print("  Stamina and flank tests PASSED")
    print()


if __name__ == "__main__":
    test_state_metrics()
    test_schema_validation()
    test_anti_swarm()
    test_shot_discipline()
    test_role_boundaries()
    test_stamina_and_flank()
    print("ALL RULES TESTS PASSED!")
