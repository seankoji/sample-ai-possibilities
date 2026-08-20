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
    assert "scoreDiff=" in summary

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

    # 2. Blocked shot in attacking third with 2 blockers outside 20m in neutral game -> SHOOT substituted with PASS
    # In GAME_STATE_TWO_BLOCKERS, player 4 is at (35, 0), opp goal is at (55, 0), distance = 20.0
    state_far_blocked = json.loads(json.dumps(GAME_STATE_TWO_BLOCKERS))
    for p in state_far_blocked["players"]:
        if p["agentId"] == "agentId_4":
            p["position"] = {"x": 25.0, "y": 0.0}
    sanitized_blocked = sanitize_commands(cmds, state_far_blocked, TEAM_ID, 4, st_rules)
    assert len(sanitized_blocked) == 1
    assert sanitized_blocked[0]["commandType"] == "PASS"
    print(f"  2 blockers outside 20m -> SHOOT substituted with PASS to P{sanitized_blocked[0]['parameters']['target_player_id']}")

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
    assert sanitized_flank[0]["parameters"]["target_y"] in (-15.0, -12.0, -8.0)
    assert sanitized_flank[0]["parameters"]["sprint"] is False
    print("  Opposite flank substituted PRESS_BALL with jog MOVE_TO home flank")

    print("  Stamina and flank tests PASSED")
    print()


def test_lane_clearance_and_rerouting():
    print("=== TEST LANE CLEARANCE & REROUTING ===")
    from state import point_to_segment_dist, is_lane_blocked
    # Segment (0, 0) to (20, 0)
    # Point at (10, 1) -> distance is 1.0
    assert abs(point_to_segment_dist(10.0, 1.0, 0.0, 0.0, 20.0, 0.0) - 1.0) < 1e-5
    # Point at (-5, 0) -> distance is 5.0 (clamped to start point)
    assert abs(point_to_segment_dist(-5.0, 0.0, 0.0, 0.0, 20.0, 0.0) - 5.0) < 1e-5

    # Opponents list with an opponent blocking lane to player 4
    opponents = [{"position": {"x": 20.0, "y": 0.0}}]
    assert is_lane_blocked({"x": 0.0, "y": 0.0}, {"x": 30.0, "y": 0.0}, opponents, clearance=2.5) is True
    assert is_lane_blocked({"x": 0.0, "y": 0.0}, {"x": 30.0, "y": 15.0}, opponents, clearance=2.5) is False

    # Test sanitize_commands PASS rerouting:
    # Player 2 at (0, -10) passes to Player 4 at (30, -10), but opponent is at (15, -10) (lane blocked)
    # Teammate Player 3 is at (20, 15) with open lane
    state_pass_test = json.loads(json.dumps(GAME_STATE))
    state_pass_test["players"] = [
        {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50.0, "y": 0.0}},
        {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -25.0, "y": 0.0}},
        {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 0.0, "y": -10.0}},
        {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 20.0, "y": 15.0}},
        {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 30.0, "y": -10.0}},
        {"agentId": "agentId_0", "teamCode": "away", "position": {"x": 50.0, "y": 0.0}},
        {"agentId": "agentId_1", "teamCode": "away", "position": {"x": 15.0, "y": -10.0}}, # Blocker on 2->4 lane
    ]
    lm_rules = RoleRules(label="LM", may_press=True, shoot_gate=True, home_y=-15.0)
    cmds = [{"commandType": "PASS", "parameters": {"target_player_id": 4, "type": "GROUND"}}]
    sanitized = sanitize_commands(cmds, state_pass_test, TEAM_ID, 2, lm_rules)
    assert len(sanitized) == 1
    assert sanitized[0]["parameters"]["target_player_id"] == 3
    print("  Blocked pass to P4 successfully rerouted to open teammate P3")

    print("  Lane clearance & rerouting tests PASSED")
    print()


def test_dynamic_far_post_aim():
    print("=== TEST DYNAMIC FAR POST AIM ===")
    from state import get_far_post_aim
    # GK on left (y = -5) -> far post is right ("TR" / "BR")
    assert get_far_post_aim(-5.0, prefer_top=True) == "TR"
    assert get_far_post_aim(-5.0, prefer_top=False) == "BR"
    # GK on right (y = 5) -> far post is left ("TL" / "BL")
    assert get_far_post_aim(5.0, prefer_top=True) == "TL"
    assert get_far_post_aim(5.0, prefer_top=False) == "BL"

    # Test sanitize_commands SHOOT dynamically aims far post
    state_gk_left = json.loads(json.dumps(GAME_STATE_NO_BLOCKERS))
    for p in state_gk_left["players"]:
        if p.get("teamCode") == "away" and p.get("agentId") == "agentId_0":
            p["position"] = {"x": 50.0, "y": -8.0}
    st_rules = RoleRules(label="ST", may_press=True, shoot_gate=True)
    cmds = [{"commandType": "SHOOT", "parameters": {"aim_location": "TL", "power": 0.9}}]
    sanitized = sanitize_commands(cmds, state_gk_left, TEAM_ID, 4, st_rules)
    assert len(sanitized) == 1
    assert sanitized[0]["parameters"]["aim_location"] == "TR"
    print("  Shooter aim dynamically redirected to far post TR when GK is at y < 0")

    print("  Dynamic far post aim tests PASSED")
    print()


def test_gk_distribution_wide():
    print("=== TEST GK DISTRIBUTION WIDE ===")
    # When GK has ball, sanitize_commands chooses between player 2 and 3 based on openness & larger |y|
    state_gk_ball = json.loads(json.dumps(GAME_STATE))
    state_gk_ball["ball"]["possessionAgentId"] = "agentId_0"
    state_gk_ball["players"] = [
        {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50.0, "y": 0.0}},
        {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -30.0, "y": 0.0}},
        {"agentId": "agentId_2", "teamCode": "home", "position": {"x": -20.0, "y": -18.0}}, # Wide open LM
        {"agentId": "agentId_3", "teamCode": "home", "position": {"x": -20.0, "y": 5.0}},   # Less wide RM
        {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 20.0, "y": 0.0}},
        {"agentId": "agentId_0", "teamCode": "away", "position": {"x": 50.0, "y": 0.0}},
    ]
    gk_rules = RoleRules(label="GK", box_only=True, may_press=False, shoot_gate=True)
    cmds = [{"commandType": "MOVE_TO", "parameters": {"target_x": -50.0, "target_y": 0.0}}]
    sanitized = sanitize_commands(cmds, state_gk_ball, TEAM_ID, 0, gk_rules)
    assert len(sanitized) == 1
    assert sanitized[0]["commandType"] == "GK_DISTRIBUTE"
    assert sanitized[0]["parameters"]["target_player_id"] == 2 # P2 has larger |y| = 18 > 5
    print("  GK distributed to wider wing player P2 instead of central P1")

    # If P2's lane is blocked by opponent, distribute to P3
    state_gk_p2_blocked = json.loads(json.dumps(state_gk_ball))
    state_gk_p2_blocked["players"].append({
        "agentId": "agentId_1", "teamCode": "away", "position": {"x": -35.0, "y": -9.0}
    })
    sanitized_p3 = sanitize_commands(cmds, state_gk_p2_blocked, TEAM_ID, 0, gk_rules)
    assert len(sanitized_p3) == 1
    assert sanitized_p3[0]["parameters"]["target_player_id"] == 3
    print("  GK distributed to unblocked wing player P3 when P2 lane is obstructed")

    print("  GK distribution tests PASSED")
    print()


def test_score_state_adaptations():
    print("=== TEST SCORE STATE ADAPTATIONS ===")
    from state import get_score_diff
    # 1. get_score_diff
    s_home_ahead = {"score": {"home": 3, "away": 1}}
    assert get_score_diff(s_home_ahead, team_id=0) == 2
    assert get_score_diff(s_home_ahead, team_id=1) == -2

    # 2. Deficit in 2nd half: gameTime > 150, scoreDiff < 0
    state_chasing = json.loads(json.dumps(GAME_STATE))
    state_chasing["gameTime"] = 180.0
    state_chasing["score"] = {"home": 0, "away": 2} # losing by 2 as team 0

    # CB own_half_only boundary relaxed (target_x > 0 allowed)
    cb_rules = RoleRules(label="CB", own_half_only=True, may_press=True, shoot_gate=True)
    cmds_cb = [{"commandType": "MOVE_TO", "parameters": {"target_x": 15.0, "target_y": 0.0, "sprint": True}}]
    sanitized_cb = sanitize_commands(cmds_cb, state_chasing, TEAM_ID, 1, cb_rules)
    assert len(sanitized_cb) == 1
    assert sanitized_cb[0]["parameters"]["target_x"] == 15.0
    print("  Chasing deficit: CB own_half_only relaxed (target_x > 0 permitted)")

    # Shot blocker threshold relaxed (allows shot with 2 blockers inside 20m)
    state_chasing_shot = json.loads(json.dumps(GAME_STATE_TWO_BLOCKERS))
    state_chasing_shot["gameTime"] = 180.0
    state_chasing_shot["score"] = {"home": 0, "away": 1}
    st_rules = RoleRules(label="ST", may_press=True, shoot_gate=True)
    cmds_shot = [{"commandType": "SHOOT", "parameters": {"aim_location": "TL", "power": 0.9}}]
    sanitized_shot = sanitize_commands(cmds_shot, state_chasing_shot, TEAM_ID, 4, st_rules)
    assert len(sanitized_shot) == 1
    assert sanitized_shot[0]["commandType"] == "SHOOT"
    print("  Chasing deficit: shot with 2 blockers permitted")

    # Elevated press intensity when chasing
    state_chasing_press = json.loads(json.dumps(GAME_STATE))
    state_chasing_press["gameTime"] = 200.0
    state_chasing_press["score"] = {"home": 1, "away": 2}
    state_chasing_press["ball"]["position"] = {"x": 10.0, "y": 10.0}
    state_chasing_press["players"][3]["position"] = {"x": 10.0, "y": 10.0} # P3 nearest
    rm_rules = RoleRules(label="RM", may_press=True, shoot_gate=True, home_y=15.0)
    cmds_press = [{"commandType": "PRESS_BALL", "parameters": {"intensity": 0.6}}]
    sanitized_press = sanitize_commands(cmds_press, state_chasing_press, TEAM_ID, 3, rm_rules)
    assert len(sanitized_press) == 1
    assert sanitized_press[0]["parameters"]["intensity"] == 0.9
    print("  Chasing deficit: press intensity elevated to 0.9")

    # 3. Defending lead: scoreDiff >= 2
    state_lead = json.loads(json.dumps(GAME_STATE))
    state_lead["score"] = {"home": 3, "away": 0} # ahead by 3
    cmds_lead_move = [{"commandType": "MOVE_TO", "parameters": {"target_x": 10.0, "target_y": -15.0, "sprint": True}}]
    cmds_lead_mark = [{"commandType": "MARK", "parameters": {"target_player_id": 1, "tightness": "LOOSE"}}]
    sanitized_lead_move = sanitize_commands(cmds_lead_move, state_lead, TEAM_ID, 2, rm_rules)
    sanitized_lead_mark = sanitize_commands(cmds_lead_mark, state_lead, TEAM_ID, 2, rm_rules)
    assert sanitized_lead_move[0]["parameters"]["sprint"] is False
    assert sanitized_lead_mark[0]["parameters"]["tightness"] == "TIGHT"
    print("  Defending lead: sprint forced False to protect stamina, marking tightened to TIGHT")

    print("  Score state adaptation tests PASSED")
    print()


if __name__ == "__main__":
    test_state_metrics()
    test_schema_validation()
    test_anti_swarm()
    test_shot_discipline()
    test_role_boundaries()
    test_stamina_and_flank()
    test_lane_clearance_and_rerouting()
    test_dynamic_far_post_aim()
    test_gk_distribution_wide()
    test_score_state_adaptations()
    print("ALL RULES TESTS PASSED!")
