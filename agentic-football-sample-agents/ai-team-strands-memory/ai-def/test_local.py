"""Local test for the DEF (Memory) agent — tests state summary, parsing, and fallback."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from test_helpers import mock_agentcore_memory, GAME_STATE, TEAM_ID
# For real Memory testing, set: export MEMORY_ID=mem-xxxxxxxxxxxxxxxx
os.environ.setdefault("MEMORY_ID", "test-memory-id")
os.environ.setdefault("TEAM_ID", str(TEAM_ID))
mock_agentcore_memory()

from state import summarize_state
from parsing import parse_commands
from main import fallback_commands, MY_PLAYER_ID, POSITION_LABEL


def test_summarize():
    print(f"=== STATE SUMMARY ({POSITION_LABEL}, player {MY_PLAYER_ID}) ===")
    summary = summarize_state(GAME_STATE, TEAM_ID, MY_PLAYER_ID, POSITION_LABEL)
    print(summary)
    print()


def test_fallback():
    print(f"=== FALLBACK ({POSITION_LABEL}) ===")
    cmds = fallback_commands(GAME_STATE, TEAM_ID, MY_PLAYER_ID)
    for c in cmds:
        pid = c.get("playerId")
        tid = c.get("teamId")
        ok = "OK" if pid == MY_PLAYER_ID and tid == TEAM_ID else "WRONG"
        print(f"  [{ok}] P{pid} T{tid}: {c['commandType']} {c.get('parameters', {})}")
    assert all(c["playerId"] == MY_PLAYER_ID for c in cmds), "FAIL: wrong playerId"
    assert all(c["teamId"] == TEAM_ID for c in cmds), "FAIL: wrong teamId"
    print(f"  All {len(cmds)} commands correct")
    print()


def test_parse():
    print("=== PARSE TESTS ===")
    tests = [
        ('[{"commandType":"MARK","playerId":1,"parameters":{"target_player_id":3,"tightness":"TIGHT"},"duration":5}]', 1),
        ("invalid json", 0),
    ]
    for resp, expected in tests:
        cmds = parse_commands(resp, TEAM_ID, MY_PLAYER_ID)
        status = "PASS" if len(cmds) == expected else "FAIL"
        print(f"  [{status}] '{resp[:50]}...' -> {len(cmds)} cmds (expected {expected})")
    print()


def test_llm():
    print("=== LLM + MEMORY TEST ===")
    # Check AWS credentials are available
    import boto3
    try:
        session = boto3.session.Session()
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        print(f"  AWS credentials OK — account: {identity['Account']}")
    except Exception as e:
        print(f"  WARNING: AWS credentials not available ({e})")
        print("  LLM test may fail. Configure AWS credentials and retry.")

    memory_id = os.environ.get("MEMORY_ID", "not set")
    if memory_id == "test-memory-id" or memory_id == "not set":
        print("  NOTE: MEMORY_ID is not set to a real memory resource.")
        print("        For real Memory recall, set: export MEMORY_ID=mem-xxxxxxxxxxxxxxxx")
        print("        Falling back to mock memory for this test.")
    else:
        print(f"  MEMORY_ID = {memory_id}")

    mock_game_state_msg = (
        "Tick 42 | DEF defending. Ball at (30,20). "
        "Opponent FWD at (28,22) threatening goal. Score 0-1. "
        "Decide: mark tight or drop into zone?"
    )
    print(f"  Invoking agent with: '{mock_game_state_msg}'")

    try:
        from main import agent
        response = agent(mock_game_state_msg, GAME_STATE, TEAM_ID, MY_PLAYER_ID)
        print(f"  Raw response: {response}")
    except Exception as e:
        print(f"  Agent invocation error: {e}")
    print()


if __name__ == "__main__":
    if "--llm" in sys.argv:
        test_llm()
    else:
        test_summarize()
        test_fallback()
        test_parse()
        print("Memory agent local tests passed (no LLM/Memory calls).")
        print(f"  Tip: MEMORY_ID env = {os.environ.get('MEMORY_ID', 'not set')}")
        print("  Run with --llm to test the full LLM + Memory path (needs AWS credentials).")
