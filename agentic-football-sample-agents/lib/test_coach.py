"""Unit tests for coaching instruction (teamChat) handling in lib/coach.py."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from test_helpers import mock_agentcore, GAME_STATE_NO_BLOCKERS, GAME_STATE_TWO_BLOCKERS, TEAM_ID

mock_agentcore()

import coach
from coach import classify, apply_posture, update_coaching
from rules import RoleRules, sanitize_commands


def _reset_match():
    """Clear module-level match state between tests."""
    coach._match.update(last_time=0.0, posture=coach.BALANCED, instruction=None)


def _state(team_chat, game_time=150.0):
    return {"gameTime": game_time, "teamChat": team_chat, "players": [], "ball": {}}


def test_classify():
    print("=== TEST CLASSIFY ===")
    # The four workshop example phrases
    assert classify("Press higher, win the ball back quickly") == coach.ATTACKING
    assert classify("Hold position, wait for counter-attack") == coach.DEFENSIVE
    assert classify("Focus on possession, slow the game down") == coach.DEFENSIVE
    assert classify("Push forward, we need a goal") == coach.ALL_OUT

    # Keyword coverage
    assert classify("must score now") == coach.ALL_OUT
    assert classify("everyone forward") == coach.ALL_OUT
    assert classify("park the bus") == coach.DEFENSIVE
    assert classify("protect the lead") == coach.DEFENSIVE
    assert classify("take more shots") == coach.ATTACKING
    assert classify("back to normal") == coach.BALANCED
    assert classify("revert to the shape we had earlier") == coach.BALANCED

    # Case-insensitive
    assert classify("PUSH FORWARD") == coach.ALL_OUT

    # Unrecognized → BALANCED
    assert classify("good luck out there") == coach.BALANCED

    print("  Classify tests PASSED")
    print()


def test_extract_latest():
    print("=== TEST EXTRACT LATEST ===")
    # List of strings
    assert coach._extract_latest(["first", "second"]) == "second"
    # List of dicts (various keys)
    assert coach._extract_latest([{"content": "hello"}]) == "hello"
    assert coach._extract_latest([{"message": "hi"}]) == "hi"
    assert (
        coach._extract_latest([{"role": "user", "content": "push forward"}])
        == "push forward"
    )
    # Empty / malformed
    assert coach._extract_latest([]) is None
    assert coach._extract_latest(None) is None
    assert coach._extract_latest([{"role": "user"}]) is None
    assert coach._extract_latest([42]) is None

    print("  Extract-latest tests PASSED")
    print()


def test_apply_posture():
    print("=== TEST APPLY POSTURE ===")
    cb = RoleRules(label="CB", own_half_only=True)

    all_out = apply_posture(cb, coach.ALL_OUT)
    assert all_out.own_half_only is False
    assert all_out.max_shot_blockers == 3
    # Original untouched (replace returns a copy)
    assert cb.own_half_only is True
    assert cb.max_shot_blockers == 2

    defensive = apply_posture(cb, coach.DEFENSIVE)
    assert defensive.max_shot_blockers == 1
    assert defensive.own_half_only is True  # CB stays pinned

    assert apply_posture(cb, coach.BALANCED) is cb
    assert apply_posture(cb, coach.ATTACKING) is cb
    assert apply_posture(None, coach.ALL_OUT) is None

    print("  Apply-posture tests PASSED")
    print()


def test_update_coaching():
    print("=== TEST UPDATE COACHING ===")
    st = RoleRules(label="ST")

    # Empty teamChat → no prompt line, rules unchanged
    _reset_match()
    line, rules = update_coaching(_state([]), st)
    assert line == ""
    assert rules is st

    # New instruction → prompt line + posture applied
    _reset_match()
    line, rules = update_coaching(_state(["Push forward, we need a goal"]), st)
    assert 'COACH: "Push forward, we need a goal"' in line
    assert "posture=ALL_OUT" in line
    assert rules.max_shot_blockers == 3

    # Same instruction next tick → persists (no reclassify needed)
    line2, rules2 = update_coaching(
        _state(["Push forward, we need a goal"], game_time=151.0), st
    )
    assert "posture=ALL_OUT" in line2
    assert rules2.max_shot_blockers == 3

    # New instruction supersedes (latest wins)
    line3, rules3 = update_coaching(
        _state(["Push forward, we need a goal", "Hold position"], game_time=152.0), st
    )
    assert "posture=DEFENSIVE" in line3
    assert rules3.max_shot_blockers == 1

    # gameTime regression → new match → reset to BALANCED
    line4, rules4 = update_coaching(_state([], game_time=10.0), st)
    assert line4 == ""
    assert rules4 is st

    # None rules pass through
    _reset_match()
    line5, rules5 = update_coaching(_state(["must score"]), None)
    assert "posture=ALL_OUT" in line5
    assert rules5 is None

    print("  Update-coaching tests PASSED")
    print()


def test_shot_gate_respects_posture():
    print("=== TEST SHOT GATE × POSTURE ===")
    shoot = [
        {"commandType": "SHOOT", "parameters": {"aim_location": "TR", "power": 0.9}}
    ]

    st_default = RoleRules(label="ST")

    # Clear shot in attacking third -> SHOOT survives with dynamic far-post aiming
    out_clear = sanitize_commands(shoot, GAME_STATE_NO_BLOCKERS, TEAM_ID, 4, st_default)
    assert len(out_clear) == 1 and out_clear[0]["commandType"] == "SHOOT", (
        f"expected SHOOT, got {out_clear}"
    )
    assert out_clear[0]["parameters"]["power"] >= 0.90

    # Default gate (max_blockers=2): 2 blockers -> converted to PASS
    out_default_blocked = sanitize_commands(shoot, GAME_STATE_TWO_BLOCKERS, TEAM_ID, 4, st_default)
    assert len(out_default_blocked) == 1 and out_default_blocked[0]["commandType"] == "PASS", (
        f"expected PASS, got {out_default_blocked}"
    )

    # ALL_OUT gate (max_blockers=3): 2 blockers -> SHOOT survives
    st_all_out = apply_posture(st_default, coach.ALL_OUT)
    out_all_out = sanitize_commands(shoot, GAME_STATE_TWO_BLOCKERS, TEAM_ID, 4, st_all_out)
    assert len(out_all_out) == 1 and out_all_out[0]["commandType"] == "SHOOT", (
        f"expected SHOOT, got {out_all_out}"
    )

    # DEFENSIVE gate (max_blockers=1): 2 blockers -> converted to PASS
    st_defensive = apply_posture(st_default, coach.DEFENSIVE)
    out_def = sanitize_commands(shoot, GAME_STATE_TWO_BLOCKERS, TEAM_ID, 4, st_defensive)
    assert len(out_def) == 1 and out_def[0]["commandType"] == "PASS", (
        f"expected PASS, got {out_def}"
    )

    print("  Shot-gate posture tests PASSED")
    print()


if __name__ == "__main__":
    test_classify()
    test_extract_latest()
    test_apply_posture()
    test_update_coaching()
    test_shot_gate_respects_posture()
    print("ALL COACH TESTS PASSED")
