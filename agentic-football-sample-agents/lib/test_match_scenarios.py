"""Comprehensive Match Scenario Regression Test Suite.

Locks in core football rules, match engine physics, and tactical strategies:
1. Kickoff Formation Rapid Lock
2. Corner & Flank Wall Trapping
3. DEFENSIVE Coaching Posture (1-0 lead protection)
4. ALL_OUT Coaching Posture (0-1 comeback mode)
5. Opponent Back-to-Goal Press Trigger
6. Flank-to-Box Aerial Crossing
7. Stamina Conservation (<30% stamina disables sprinting)
8. Own Third Clearance Under Pressure
9. Far-Post Dynamic Shooting Angles
10. 10-Player Game ID (0-9) Full Compatibility
"""

import sys
import os
from pathlib import Path

# Add lib/ to sys.path
LIB_DIR = Path(__file__).parent.resolve()
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from fast_path import fast_path_decision
from rules import RoleRules, sanitize_commands
from coach import update_coaching, classify, DEFENSIVE, ALL_OUT, BALANCED, ATTACKING
from state import (
    get_goal_positions,
    get_possession_info,
    get_far_post_aim,
    _possession_idx,
    _player_idx,
    _is_my_team,
)


def test_scenario_kickoff_rapid_lock():
    """Scenario 1: Kickoff state immediately locks all positions without inference."""
    game_state = {
        "playMode": "KICK_OFF",
        "ball": {"position": {"x": 0, "y": 0}, "isFree": True},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -45, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -20, "y": 5}, "stamina": 100},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": -10, "y": -10}, "stamina": 100},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": -10, "y": 10}, "stamina": 100},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 0, "y": 0}, "stamina": 100},
        ],
    }
    
    # Verify GK
    cmd_gk = fast_path_decision(game_state, 0, 0, "GK")
    assert cmd_gk is not None and cmd_gk[0]["commandType"] == "MOVE_TO"
    assert cmd_gk[0]["parameters"]["target_x"] == -55.0 * 0.95

    # Verify CB (25% up pitch from goal)
    cmd_cb = fast_path_decision(game_state, 0, 1, "CB")
    assert cmd_cb is not None and cmd_cb[0]["commandType"] == "MOVE_TO"
    assert cmd_cb[0]["parameters"]["target_x"] == -55.0 * 0.50

    # Verify ST
    cmd_st = fast_path_decision(game_state, 0, 4, "ST")
    assert cmd_st is not None and cmd_st[0]["commandType"] == "MOVE_TO"
    assert cmd_st[0]["parameters"]["target_x"] == 0.0
    print("✓ Scenario 1: Kickoff rapid lock verified for all roles")


def test_scenario_defensive_coaching_posture():
    """Scenario 2: Lead protection coaching posture tightens gates and anchors defense."""
    game_state = {
        "gameTime": 120.0,
        "teamChat": ["Focus on possession, protect the lead, slow the game"],
        "ball": {"position": {"x": 20, "y": 0}, "possessionAgentId": "agentId_2"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 90},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -35, "y": 0}, "stamina": 90},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 20, "y": 0}, "stamina": 90},
        ],
    }
    
    cb_rules = RoleRules(label="CB", own_half_only=True, may_press=True, shoot_gate=True)
    prompt_line, effective_rules = update_coaching(game_state, cb_rules)
    
    assert "DEFENSIVE" in prompt_line
    assert effective_rules.max_shot_blockers == 1, "DEFENSIVE posture must restrict shot blockers to <= 1"
    assert effective_rules.own_half_only is True, "CB must remain anchored in own half"
    print("✓ Scenario 2: DEFENSIVE coaching posture modulation verified")


def test_scenario_all_out_coaching_posture():
    """Scenario 3: Comeback mode unlocks CB offensive runs and relaxes shot gate."""
    game_state = {
        "gameTime": 160.0,
        "teamChat": ["Push forward, we need a goal, all out!"],
        "ball": {"position": {"x": 10, "y": 0}, "possessionAgentId": "agentId_2"},
        "players": [
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -20, "y": 0}, "stamina": 80},
        ],
    }
    
    cb_rules = RoleRules(label="CB", own_half_only=True, may_press=True, shoot_gate=True)
    prompt_line, effective_rules = update_coaching(game_state, cb_rules)
    
    assert "ALL_OUT" in prompt_line
    assert effective_rules.own_half_only is False, "ALL_OUT must permit CB to cross halfway"
    assert effective_rules.max_shot_blockers == 3, "ALL_OUT must relax shot blocker threshold to 3"
    print("✓ Scenario 3: ALL_OUT coaching posture modulation verified")


def test_scenario_opponent_back_to_goal_press():
    """Scenario 4: Opponent ball carrier close triggers immediate high-intensity press."""
    game_state = {
        "ball": {"position": {"x": 10, "y": 5}, "possessionAgentId": "agentId_5"},
        "players": [
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 12, "y": 7}, "stamina": 85},
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": 10, "y": 5}, "stamina": 90},
        ],
    }
    
    rules = RoleRules(label="RM", may_press=True)
    cmd = fast_path_decision(game_state, 0, 3, "RM", rules)
    assert cmd is not None and cmd[0]["commandType"] == "PRESS_BALL"
    assert cmd[0]["parameters"]["intensity"] >= 0.8
    print("✓ Scenario 4: Ball carrier press trigger verified")


def test_scenario_flank_to_box_cross():
    """Scenario 5: Winger on flank in attacking third crosses to central striker."""
    game_state = {
        "ball": {"position": {"x": 40, "y": 20}, "possessionAgentId": "agentId_3"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 40, "y": 20}, "stamina": 85},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 45, "y": 0}, "stamina": 90},
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": 30, "y": 10}, "stamina": 90},
        ],
    }
    
    cmd = fast_path_decision(game_state, 0, 3, "RM", None)
    assert cmd is not None and cmd[0]["commandType"] == "PASS"
    assert cmd[0]["parameters"]["type"] == "AERIAL"
    assert cmd[0]["parameters"]["target_player_id"] == 4
    print("✓ Scenario 5: Flank-to-box cross verified")


def test_scenario_stamina_preservation():
    """Scenario 6: Low stamina (<30%) prohibits sprinting and caps pressing."""
    game_state = {
        "ball": {"position": {"x": -10, "y": 0}, "possessionAgentId": "agentId_2"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": -10, "y": 0}, "stamina": 80},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 10, "y": 0}, "stamina": 22},  # Low stamina
        ],
    }
    
    cmd = fast_path_decision(game_state, 0, 4, "ST", None)
    assert cmd is not None and cmd[0]["commandType"] == "MOVE_TO"
    assert cmd[0]["parameters"]["sprint"] is False, "Player with stamina < 30 must never sprint"
    print("✓ Scenario 6: Stamina preservation verified")


def test_scenario_box_emergency_clearance():
    """Scenario 7: CB under pressure in own box executes immediate aerial flank clearance."""
    game_state = {
        "ball": {"position": {"x": -48, "y": 2}, "possessionAgentId": "agentId_1"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -52, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -48, "y": 2}, "stamina": 90},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": -20, "y": -15}, "stamina": 85},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": -20, "y": 15}, "stamina": 85},
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": -46, "y": 3}, "stamina": 90},
        ],
    }
    
    cmd = fast_path_decision(game_state, 0, 1, "CB", RoleRules(label="CB", own_half_only=True))
    assert cmd is not None and cmd[0]["commandType"] == "PASS"
    assert cmd[0]["parameters"]["type"] == "AERIAL"
    assert cmd[0]["parameters"]["target_player_id"] in (2, 3), "Clearance must target wide flank teammates"
    print("✓ Scenario 7: Box emergency clearance verified")


def test_scenario_far_post_shooting_angles():
    """Scenario 8: Far-post aiming dynamically shifts based on opponent GK position."""
    aim_right = get_far_post_aim(-5.0, prefer_top=True)
    assert aim_right == "TR"
    
    aim_left = get_far_post_aim(5.0, prefer_top=True)
    assert aim_left == "TL"
    print("✓ Scenario 8: Far-post shooting angles verified")


def test_scenario_ten_player_id_compatibility():
    """Scenario 9: Away team player IDs (5-9) properly parsed and supported."""
    game_state = {
        "ball": {"position": {"x": -30, "y": 5}, "possessionAgentId": "agentId_7"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -35, "y": 0}, "stamina": 90},
            {"agentId": "agentId_7", "teamCode": "away", "position": {"x": -30, "y": 5}, "stamina": 90},
        ],
    }
    
    assert _possession_idx(game_state["ball"]) == 7
    
    mark_cmd = [{
        "commandType": "MARK",
        "playerId": 1,
        "teamId": 0,
        "parameters": {"target_player_id": 7, "tightness": "TIGHT"},
        "duration": 3,
    }]
    
    sanitized = sanitize_commands(mark_cmd, game_state, 0, 1, RoleRules(label="CB", own_half_only=True))
    assert len(sanitized) == 1
    assert sanitized[0]["parameters"]["target_player_id"] == 7
def test_scenario_marked_player_passes_immediately():
    """Scenario 10: Player receiving ball under pressure (<8.5m or defender in front) passes immediately."""
    game_state = {
        "ball": {"position": {"x": 10, "y": 0}, "possessionAgentId": "agentId_4"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 10, "y": -15}, "stamina": 90},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 10, "y": 15}, "stamina": 90},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 10, "y": 0}, "stamina": 90},
            # Opponent closing in 6m away
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": 16, "y": 0}, "stamina": 90},
        ],
    }
    
    cmd = fast_path_decision(game_state, 0, 4, "ST", None)
    assert cmd is not None, "Player marked or with defender in front must trigger fast-path pass"
    assert cmd[0]["commandType"] == "PASS"
    assert cmd[0]["parameters"]["target_player_id"] in (2, 3), "Must pass to open wing teammate"
    print("✓ Scenario 10: Marked/pressured player passes immediately verified")


def test_scenario_rebound_crashing_and_rest_defense():
    """Scenario 11: In attacking third, winger on ball flank crashes goalmouth while opposite winger forms rest-defense screen."""
    game_state = {
        "ball": {"position": {"x": 35, "y": -15}, "possessionAgentId": "agentId_2"},  # LM on ball
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -25, "y": 0}, "stamina": 90},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 35, "y": -15}, "stamina": 90},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 10, "y": 15}, "stamina": 90},   # RM opposite flank
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 30, "y": 0}, "stamina": 90},
        ],
    }
    
    # RM on opposite flank acts as rest-defense screen at midfield (x=0)
    cmd_rm = fast_path_decision(game_state, 0, 3, "RM", None)
    assert cmd_rm is not None and cmd_rm[0]["commandType"] == "MOVE_TO"
    assert cmd_rm[0]["parameters"]["target_x"] == 0.0, "Opposite winger must form rest-defense screen at midfield"

    # ST takes up position in the middle of the box (x ≈ 55 * 0.65 = 35.75)
    cmd_st = fast_path_decision(game_state, 0, 4, "ST", None)
    assert cmd_st is not None and cmd_st[0]["commandType"] == "MOVE_TO"
    assert 24.0 <= cmd_st[0]["parameters"]["target_x"] <= 40.0, "Striker must position in the attacking pocket"
    print("✓ Scenario 11: Box positioning & rest-defense screen verified")


def test_scenario_overload_field_switch():
    """Scenario 12: Winger on heavily overloaded touchline switches play aerially to opposite open winger."""
    game_state = {
        "ball": {"position": {"x": 20, "y": -18}, "possessionAgentId": "agentId_2"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 20, "y": -18}, "stamina": 90},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 20, "y": 22}, "stamina": 90},  # Isolated on opposite touchline
            # 3 opponents clustered on left flank (y < 0)
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": 22, "y": -15}, "stamina": 90},
            {"agentId": "agentId_6", "teamCode": "away", "position": {"x": 18, "y": -10}, "stamina": 90},
            {"agentId": "agentId_7", "teamCode": "away", "position": {"x": 25, "y": -20}, "stamina": 90},
        ],
    }
    
    cmd = fast_path_decision(game_state, 0, 2, "LM", None)
    assert cmd is not None, "Overloaded touchline must trigger fast-path switch"
    assert cmd[0]["commandType"] == "PASS"
    assert cmd[0]["parameters"]["type"] == "AERIAL"
    assert cmd[0]["parameters"]["target_player_id"] == 3, "Must switch play to isolated opposite winger"
    print("✓ Scenario 12: Overload-to-isolate field switch verified")


def test_scenario_gk_possession_outfield_runs_and_long_kick():
    """Scenario 13: When GK gets ball, mid/fwd sprint into opp half and GK kicks long if >= 3 opps in our half."""
    game_state = {
        "ball": {"position": {"x": -50, "y": 0}, "possessionAgentId": "agentId_0"},  # GK has ball
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -35, "y": 0}, "stamina": 90},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": -10, "y": -10}, "stamina": 90}, # LM
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": -10, "y": 10}, "stamina": 90},  # RM
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 15, "y": 0}, "stamina": 90},    # ST in opp half
            # 3 opponents pressing in our half (x < 0)
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": -25, "y": 0}, "stamina": 90},
            {"agentId": "agentId_6", "teamCode": "away", "position": {"x": -20, "y": -10}, "stamina": 90},
            {"agentId": "agentId_7", "teamCode": "away", "position": {"x": -15, "y": 10}, "stamina": 90},
        ],
    }
    
    # 1. Midfielder (LM) must sprint into opposition half
    cmd_lm = fast_path_decision(game_state, 0, 2, "LM", None)
    assert cmd_lm is not None and cmd_lm[0]["commandType"] == "MOVE_TO"
    assert cmd_lm[0]["parameters"]["target_x"] > 0, "LM must sprint into opposition half when GK has ball"
    assert cmd_lm[0]["parameters"]["sprint"] is True

    # 2. Striker (ST) must sprint deep into opposition half
    cmd_st = fast_path_decision(game_state, 0, 4, "ST", None)
    assert cmd_st is not None and cmd_st[0]["commandType"] == "MOVE_TO"
    assert cmd_st[0]["parameters"]["target_x"] >= 25.0, "ST must sprint into opposition half"

    # 3. Goalkeeper must execute long KICK over the 3-man press
    cmd_gk = fast_path_decision(game_state, 0, 0, "GK", None)
    assert cmd_gk is not None and cmd_gk[0]["commandType"] == "GK_DISTRIBUTE"
    assert cmd_gk[0]["parameters"]["method"] == "KICK", "GK must KICK long when >= 3 opponents are in our half"
    assert cmd_gk[0]["parameters"]["target_player_id"] == 4, "GK must target forward player upfield"
def test_scenario_striker_inside_box_instant_shoot():
    """Scenario 14: Striker receives ball inside the box -> immediately shoots at best far-post path."""
    game_state = {
        "ball": {"position": {"x": 42, "y": -4}, "possessionAgentId": "agentId_4"},  # Inside box (x=42, y=-4)
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 42, "y": -4}, "stamina": 90},
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": 52, "y": -2}, "stamina": 100},  # Opp GK at y=-2
        ],
    }
    
    cmd = fast_path_decision(game_state, 0, 4, "ST", None)
    assert cmd is not None, "Striker inside box must trigger instant fast-path shoot"
    assert cmd[0]["parameters"]["aim_location"] in ("TR", "BR"), "Must shoot at far-post (TR/BR when GK is at y < 0)"
    assert cmd[0]["parameters"]["power"] >= 0.90
def test_scenario_line_breaking_through_pass():
    """Scenario 15: Line-breaking pass when ST breaks level with opponent backline."""
    game_state = {
        "ball": {"position": {"x": 10, "y": -12}, "possessionAgentId": "agentId_2"}, # LM on ball
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 10, "y": -12}},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 30, "y": 0}},  # ST breaking behind
            # Opponent backline at x=28
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": 28, "y": -5}},
            {"agentId": "agentId_6", "teamCode": "away", "position": {"x": 28, "y": 5}},
        ],
    }
    cmd = fast_path_decision(game_state, 0, 2, "LM", None)
    assert cmd is not None and cmd[0]["commandType"] == "PASS"
    assert cmd[0]["parameters"]["type"] == "THROUGH"
    assert cmd[0]["parameters"]["target_player_id"] == 4
    print("✓ Scenario 15: Line-breaking through pass verified")


def test_scenario_danger_zone_14_cutback():
    """Scenario 16: Winger in half-space with blocked goal cuts back along deck to central box edge."""
    game_state = {
        "ball": {"position": {"x": 45, "y": -14}, "possessionAgentId": "agentId_2"}, # LM in half-space
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 45, "y": -14}},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 34, "y": 0}},   # ST central zone 14
            # Opponents directly in the shot cone between LM (45, -14) and goal (55, 0)
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": 48, "y": -9}},
            {"agentId": "agentId_6", "teamCode": "away", "position": {"x": 51, "y": -5}},
            {"agentId": "agentId_7", "teamCode": "away", "position": {"x": 53, "y": -2}},
        ],
    }
    cmd = fast_path_decision(game_state, 0, 2, "LM", None)
    assert cmd is not None and cmd[0]["commandType"] == "PASS"
    assert cmd[0]["parameters"]["type"] == "GROUND"
    assert cmd[0]["parameters"]["target_player_id"] == 4
    print("✓ Scenario 16: Danger Zone 14 cutback verified")


def test_scenario_midfielder_open_goal_shoot_never_pass():
    """Scenario 17: Midfielder on ball with clear sight on goal must shoot, never pass."""
    game_state = {
        "ball": {"position": {"x": 42, "y": -5}, "possessionAgentId": "agentId_2"}, # LM on ball in box/shooting range
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 42, "y": -5}},  # LM
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 48, "y": 8}},   # ST
            {"agentId": "agentId_0", "teamCode": "away", "position": {"x": 52, "y": 5}},   # Opponent GK
        ],
    }
    cmd = fast_path_decision(game_state, 0, 2, "LM", None)
    assert cmd is not None, "Midfielder with open goal must trigger fast-path"
    assert cmd[0]["commandType"] == "SHOOT", f"Expected SHOOT, got {cmd[0]['commandType']}"
    assert cmd[0]["parameters"]["power"] >= 0.90
    print("✓ Scenario 17: Midfielder open-goal shooting (never pass) verified")


if __name__ == "__main__":
    test_scenario_kickoff_rapid_lock()
    test_scenario_defensive_coaching_posture()
    test_scenario_all_out_coaching_posture()
    test_scenario_opponent_back_to_goal_press()
    test_scenario_flank_to_box_cross()
    test_scenario_stamina_preservation()
    test_scenario_box_emergency_clearance()
    test_scenario_far_post_shooting_angles()
    test_scenario_ten_player_id_compatibility()
    test_scenario_marked_player_passes_immediately()
    test_scenario_rebound_crashing_and_rest_defense()
    test_scenario_overload_field_switch()
    test_scenario_gk_possession_outfield_runs_and_long_kick()
    test_scenario_striker_inside_box_instant_shoot()
    test_scenario_line_breaking_through_pass()
    test_scenario_danger_zone_14_cutback()
    test_scenario_midfielder_open_goal_shoot_never_pass()
    print("\nAll 17 match scenario regression tests PASSED!")
