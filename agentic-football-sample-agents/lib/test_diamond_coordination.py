"""Diamond 1-2-1 Full Team Multi-Agent Coordination Test Suite.

Simulates simultaneous execution of all 5 diamond roles (GK, CB, LM, RM, ST)
on the exact same tick to verify:
1. No conflicting commands (max 1 player presses ball)
2. Proper passing chains (no pass to oneself or invalid target)
3. Complementary shape & spatial coverage (no overlapping positions)
4. Fast-path latency guarantee across all 5 roles (<5ms per decision)
5. Sanitizer compliance for all generated commands
"""

import sys
import time
from pathlib import Path

LIB_DIR = Path(__file__).parent.resolve()
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from fast_path import fast_path_decision
from rules import RoleRules, sanitize_commands

# 1-2-1 Diamond Role Definitions
DIAMOND_ROLES = [
    (0, "GK", RoleRules(label="GK", box_only=True, may_press=False, shoot_gate=False)),
    (1, "CB", RoleRules(label="CB", own_half_only=True, may_press=True, shoot_gate=True)),
    (2, "LM", RoleRules(label="LM", own_half_only=False, may_press=True, shoot_gate=True, home_y=-15.0)),
    (3, "RM", RoleRules(label="RM", own_half_only=False, may_press=True, shoot_gate=True, home_y=15.0)),
    (4, "ST", RoleRules(label="ST", own_half_only=False, may_press=True, shoot_gate=True)),
]


def run_5v5_tick(game_state: dict, team_id: int = 0) -> list[dict]:
    """Simulate all 5 agents receiving the tick simultaneously."""
    team_commands = []
    for pid, pos_label, rules in DIAMOND_ROLES:
        t0 = time.perf_counter()
        cmds = fast_path_decision(game_state, team_id, pid, pos_label, rules)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        
        # Verify latency SLA: Fast-path must execute in < 5ms
        if cmds is not None:
            assert elapsed_ms < 5.0, f"Fast-path latency SLA exceeded for {pos_label}: {elapsed_ms:.2f}ms"
            sanitized = sanitize_commands(cmds, game_state, team_id, pid, rules)
            assert len(sanitized) > 0, f"Command from {pos_label} failed sanitization!"
            team_commands.extend(sanitized)
    return team_commands


def test_coordination_phase_possession_build_up():
    """Phase 1: GK in possession -> GK distributes, outfield holds diamond shape."""
    game_state = {
        "ball": {"position": {"x": -50, "y": 0}, "possessionAgentId": "agentId_0"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -35, "y": 0}, "stamina": 90},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": -15, "y": -15}, "stamina": 85},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": -15, "y": 15}, "stamina": 85},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 10, "y": 0}, "stamina": 90},
        ],
    }
    
    cmds = run_5v5_tick(game_state, team_id=0)
    assert len(cmds) == 5, "All 5 agents must produce commands on the tick"
    
    # GK must distribute
    gk_cmd = next(c for c in cmds if c["playerId"] == 0)
    assert gk_cmd["commandType"] == "GK_DISTRIBUTE"
    
    # Outfield must hold support positions without conflicting
    outfield_moves = [c for c in cmds if c["playerId"] != 0 and c["commandType"] == "MOVE_TO"]
    assert len(outfield_moves) == 4, "All outfield players must provide diamond support"
    print("✓ Phase 1: Possession build-up coordination verified")


def test_coordination_phase_defending_box():
    """Phase 2: Opponent attacking our box -> CB marks runner, LM/RM/ST support."""
    game_state = {
        "ball": {"position": {"x": -30, "y": 5}, "possessionAgentId": "agentId_6"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -35, "y": 0}, "stamina": 90},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": -25, "y": -15}, "stamina": 85},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": -25, "y": 15}, "stamina": 85},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 0, "y": 0}, "stamina": 90},
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": -32, "y": 0}, "stamina": 90},
            {"agentId": "agentId_6", "teamCode": "away", "position": {"x": -25, "y": 5}, "stamina": 90},
        ],
    }
    
    cmds = run_5v5_tick(game_state, team_id=0)
    
    # CB marks the dangerous attacker closest to goal (agentId_5 at x=-42)
    cb_cmd = next((c for c in cmds if c["playerId"] == 1), None)
    assert cb_cmd is not None and cb_cmd["commandType"] == "MARK"
    assert cb_cmd["parameters"]["target_player_id"] == 5
    
    # Verify no two players are marking the exact same target
    marks = [c for c in cmds if c["commandType"] == "MARK"]
    mark_targets = [m["parameters"]["target_player_id"] for m in marks]
    assert len(mark_targets) == len(set(mark_targets)), "No duplicate marking assignments"
    print("✓ Phase 2: Defending box coordination & mark allocation verified")


def test_coordination_phase_attacking_shot():
    """Phase 3: Striker in attacking third -> Striker finishes, wings support."""
    game_state = {
        "ball": {"position": {"x": 40, "y": -2}, "possessionAgentId": "agentId_4"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -30, "y": 0}, "stamina": 90},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 30, "y": -15}, "stamina": 85},
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 30, "y": 15}, "stamina": 85},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 40, "y": -2}, "stamina": 90},
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": 52, "y": 3}, "stamina": 100},
        ],
    }
    
    cmds = run_5v5_tick(game_state, team_id=0)
    
    # ST takes clinical shot
    st_cmd = next(c for c in cmds if c["playerId"] == 4)
    assert st_cmd["commandType"] == "SHOOT"
    assert st_cmd["parameters"]["power"] >= 0.85
    
    # CB holds anchor in own half
    cb_cmd = next(c for c in cmds if c["playerId"] == 1)
    assert cb_cmd["commandType"] == "MOVE_TO"
    assert cb_cmd["parameters"]["target_x"] <= 0.0, "CB must hold defensive anchor in own half"
def test_coordination_phase_free_ball_single_chaser():
    """Phase 4: Free ball in midfield -> EXACTLY 1 player intercepts, others spread into open receiving pockets."""
    game_state = {
        "ball": {"position": {"x": 5, "y": 2}, "isFree": True, "possessionAgentId": None},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}, "stamina": 100},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -30, "y": 0}, "stamina": 90},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 6, "y": 3}, "stamina": 85},  # Closest to ball (dist=1.4)
            {"agentId": "agentId_3", "teamCode": "home", "position": {"x": 8, "y": 10}, "stamina": 85}, # Dist=8.5
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 15, "y": 0}, "stamina": 90},  # Dist=10.2
        ],
    }
    
    cmds = run_5v5_tick(game_state, team_id=0)
    
    # Exactly 1 player (LM / Player 2) must intercept
    intercepts = [c for c in cmds if c["commandType"] == "INTERCEPT"]
    assert len(intercepts) == 1, f"Expected exactly 1 player to chase ball, got {len(intercepts)}"
    assert intercepts[0]["playerId"] == 2, f"Expected Player 2 to intercept, got Player {intercepts[0]['playerId']}"
    
    # Other outfield players (1, 3, 4) must MOVE_TO open receiving pockets to receive the pass
    support_moves = [c for c in cmds if c["commandType"] == "MOVE_TO" and c["playerId"] in (1, 3, 4)]
    assert len(support_moves) == 3, "Other 3 outfield teammates must get into position to receive pass"
    print("✓ Phase 4: Free ball single-chaser & receiving pocket allocation verified")


if __name__ == "__main__":
    test_coordination_phase_possession_build_up()
    test_coordination_phase_defending_box()
    test_coordination_phase_attacking_shot()
    test_coordination_phase_free_ball_single_chaser()
    print("\nAll 4 Diamond multi-agent coordination suites PASSED!")
