"""Unit tests for the In-Game Adaptive Intelligence Engine."""

from adaptive_memory import (
    TacticalMemoryTracker,
    analyze_and_adapt,
    reset_adaptive_memory,
)
from fast_path import fast_path_decision


def test_high_press_detection_and_direct_counter():
    """Verify that when opponent high-presses across multiple frames, direct counter mode activates."""
    tracker = TacticalMemoryTracker()
    state_high_press = {
        "gameTime": 45,
        "score": {"home": 0, "away": 0},
        "ball": {"position": {"x": -40, "y": 0}, "possessionAgentId": "agentId_0"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -30, "y": 0}},
            {"agentId": "agentId_4", "teamCode": "home", "position": {"x": 20, "y": 0}},
            # 3 opponents in our defensive half (x < 0)
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": -20, "y": 5}},
            {"agentId": "agentId_6", "teamCode": "away", "position": {"x": -25, "y": -5}},
            {"agentId": "agentId_7", "teamCode": "away", "position": {"x": -15, "y": 0}},
        ],
    }
    
    # Record 6 ticks of high press
    for _ in range(6):
        tracker.record_tick(state_high_press, 0)
        
    tactics = tracker.compute_tactics(state_high_press, 0)
    assert tactics.direct_counter_mode is True, "Must activate direct counter mode against high press"
    print("✓ High-press detection and direct counter mode verified")


def test_flank_bias_and_defensive_line_shift():
    """Verify that when opponent attacks predominantly on left flank, defense shifts laterally."""
    tracker = TacticalMemoryTracker()
    state_left_attack = {
        "gameTime": 50,
        "score": {"home": 0, "away": 0},
        "ball": {"position": {"x": -20, "y": -15}, "possessionAgentId": "agentId_5"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -30, "y": 0}},
            {"agentId": "agentId_5", "teamCode": "away", "position": {"x": -20, "y": -15}},
        ],
    }
    
    for _ in range(6):
        tracker.record_tick(state_left_attack, 0)
        
    tactics = tracker.compute_tactics(state_left_attack, 0)
    assert tactics.defensive_line_shift_y == -4.0, f"Expected shift_y=-4.0, got {tactics.defensive_line_shift_y}"
    print("✓ Flank bias detection and lateral line shift verified")


def test_late_game_chasing_morph_1_1_2():
    """Verify that when trailing late in game, formation morphs into 1-1-2 all-out attack."""
    tracker = TacticalMemoryTracker()
    state_trailing = {
        "gameTime": 125,
        "score": {"home": 0, "away": 1},  # Trailing by 1 at 125s
        "ball": {"position": {"x": 10, "y": 0}, "possessionAgentId": "agentId_1"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -20, "y": 0}},
            {"agentId": "agentId_2", "teamCode": "home", "position": {"x": 15, "y": -10}},
        ],
    }
    
    tactics = tracker.compute_tactics(state_trailing, 0)
    assert tactics.formation_morph == "1-1-2", f"Expected 1-1-2, got {tactics.formation_morph}"
    assert tactics.defensive_line_x_factor == 0.35, "CB must push to midfield"
    print("✓ Late-game chasing morph to 1-1-2 verified")


def test_late_game_protecting_morph_2_2_0():
    """Verify that when leading late in game, formation morphs into 2-2-0 lockdown."""
    tracker = TacticalMemoryTracker()
    state_leading = {
        "gameTime": 135,
        "score": {"home": 2, "away": 1},  # Leading by 1 at 135s
        "ball": {"position": {"x": 10, "y": 0}, "possessionAgentId": "agentId_1"},
        "players": [
            {"agentId": "agentId_0", "teamCode": "home", "position": {"x": -50, "y": 0}},
            {"agentId": "agentId_1", "teamCode": "home", "position": {"x": -20, "y": 0}},
        ],
    }
    
    tactics = tracker.compute_tactics(state_leading, 0)
    assert tactics.formation_morph == "2-2-0", f"Expected 2-2-0, got {tactics.formation_morph}"
    assert tactics.defensive_line_x_factor == 0.55, "CB must anchor deep"
    print("✓ Late-game lead protection morph to 2-2-0 verified")


if __name__ == "__main__":
    reset_adaptive_memory()
    test_high_press_detection_and_direct_counter()
    test_flank_bias_and_defensive_line_shift()
    test_late_game_chasing_morph_1_1_2()
    test_late_game_protecting_morph_2_2_0()
    print("\nAll In-Game Adaptive Intelligence Engine tests PASSED!")
