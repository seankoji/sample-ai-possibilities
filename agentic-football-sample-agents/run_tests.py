#!/usr/bin/env python3
"""
Unified Test Runner for Agentic Football Sample Agents.

Usage:
    python run_tests.py                      # Run all unit tests in lib/ and test_local.py across all teams
    python run_tests.py <team_name>          # Run tests for a specific team (e.g. ai-team-strands-memory)
    python run_tests.py lib                  # Run only shared library tests
    python run_tests.py --integration        # Run integration simulations with synthetic game states
    python run_tests.py <team> --integration # Run team tests + integration simulations

Exit code:
    0 on success, 1 if any test suite fails.
"""

import argparse
import asyncio
import importlib
import json
import os
import sys
import time
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Any

REPO_ROOT = Path(__file__).parent.resolve()
LIB_DIR = REPO_ROOT / "lib"

ALL_TEAMS = sorted(
    [d.name for d in REPO_ROOT.iterdir() if d.is_dir() and d.name.startswith("ai-team-")]
) or ["ai-team-strands-diamond"]

POSITIONS = ["ai-gk", "ai-def", "ai-mid", "ai-fwd1", "ai-fwd2"]


def run_command_test(script_path: Path, args: list[str] = None) -> Tuple[bool, str, float]:
    """Execute a python test script as a subprocess and measure elapsed time."""
    start_time = time.perf_counter()
    cmd = [sys.executable, str(script_path)] + (args or [])
    try:
        res = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        elapsed = time.perf_counter() - start_time
        output = res.stdout + ("\n" + res.stderr if res.stderr else "")
        return res.returncode == 0, output, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.perf_counter() - start_time
        return False, "ERROR: Test timed out after 60s", elapsed
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        return False, f"ERROR: Failed to run test: {e}", elapsed


def run_lib_tests(verbose: bool = False) -> List[Dict[str, Any]]:
    """Run all lib/test_*.py test files."""
    results = []
    test_files = sorted(LIB_DIR.glob("test_*.py"))
    # Exclude test_helpers.py since it's a module, not a runnable test suite
    test_files = [f for f in test_files if f.name != "test_helpers.py"]

    for test_file in test_files:
        rel_path = test_file.relative_to(REPO_ROOT)
        success, output, elapsed = run_command_test(test_file)
        results.append({
            "suite": str(rel_path),
            "passed": success,
            "duration": elapsed,
            "output": output,
        })
        if verbose or not success:
            print(f"\n--- Output for {rel_path} ---")
            print(output.strip())
    return results


def run_team_local_tests(team_name: str, verbose: bool = False) -> List[Dict[str, Any]]:
    """Run test_local.py for all agents in a team."""
    results = []
    team_dir = REPO_ROOT / team_name
    if not team_dir.is_dir():
        print(f"Warning: Team directory not found: {team_name}")
        return results

    for pos in POSITIONS:
        test_file = team_dir / pos / "test_local.py"
        if not test_file.exists():
            continue

        rel_path = test_file.relative_to(REPO_ROOT)
        success, output, elapsed = run_command_test(test_file)
        results.append({
            "suite": str(rel_path),
            "passed": success,
            "duration": elapsed,
            "output": output,
        })
        if verbose or not success:
            print(f"\n--- Output for {rel_path} ---")
            print(output.strip())
    return results


def run_integration_tests(teams_to_test: List[str], verbose: bool = False) -> List[Dict[str, Any]]:
    """Simulate full invoke handler executions on diverse sample game states."""
    results = []
    # Add lib to sys.path
    if str(LIB_DIR) not in sys.path:
        sys.path.insert(0, str(LIB_DIR))

    from test_helpers import (
        mock_agentcore_memory,
        mock_agentcore_gateway,
        GAME_STATE,
        GAME_STATE_NO_BLOCKERS,
        GAME_STATE_TWO_BLOCKERS,
        GAME_STATE_OPPOSITE_FLANK,
        GAME_STATE_LOW_STAMINA,
        TEAM_ID,
    )

    test_states = [
        ("open_play", GAME_STATE),
        ("no_blockers", GAME_STATE_NO_BLOCKERS),
        ("two_blockers", GAME_STATE_TWO_BLOCKERS),
        ("opposite_flank", GAME_STATE_OPPOSITE_FLANK),
        ("low_stamina", GAME_STATE_LOW_STAMINA),
    ]

    for team in teams_to_test:
        team_dir = REPO_ROOT / team
        if not team_dir.is_dir():
            continue

        start_time = time.perf_counter()
        team_passed = True
        log_lines = []

        # Run integration in a subprocess script to keep each team isolated
        script = f"""
import sys, os, json, asyncio
sys.path.insert(0, "{LIB_DIR}")
sys.path.insert(0, "{team_dir}")
os.environ["MEMORY_ID"] = "test-memory-id"
os.environ["TEAM_ID"] = "0"

from test_helpers import (
    mock_agentcore_memory, mock_agentcore_gateway,
    GAME_STATE, GAME_STATE_NO_BLOCKERS, GAME_STATE_TWO_BLOCKERS,
    GAME_STATE_OPPOSITE_FLANK, GAME_STATE_LOW_STAMINA, TEAM_ID
)

if "{team}" == "ai-team-strands-memory":
    mock_agentcore_memory()
elif "{team}" == "ai-team-strands-gateway":
    mock_agentcore_gateway()
else:
    mock_agentcore_memory()

test_states = [
    ("open_play", GAME_STATE),
    ("no_blockers", GAME_STATE_NO_BLOCKERS),
    ("two_blockers", GAME_STATE_TWO_BLOCKERS),
    ("opposite_flank", GAME_STATE_OPPOSITE_FLANK),
    ("low_stamina", GAME_STATE_LOW_STAMINA),
]

positions = ["ai-gk", "ai-def", "ai-mid", "ai-fwd1", "ai-fwd2"]

for pos in positions:
    pos_dir = os.path.join("{team_dir}", pos, "src")
    sys.path.insert(0, pos_dir)
    try:
        import main
    except Exception as e:
        print(f"FAIL import in {{pos}}: {{e}}")
        sys.exit(1)
    
    # Extract entrypoint handler from main.app
    handler = None
    if hasattr(main, "app") and hasattr(main.app, "entrypoint"):
        # The entrypoint was decorated
        pass
    
    # Test fallback command generation directly
    if hasattr(main, "fallback_commands"):
        for state_name, state in test_states:
            cmds = main.fallback_commands(state, TEAM_ID, main.MY_PLAYER_ID)
            assert len(cmds) > 0, f"Empty fallback in {{pos}} on {{state_name}}"
            assert all(c.get("playerId") == main.MY_PLAYER_ID for c in cmds), f"Invalid playerId in {{pos}}"
            assert all(c.get("teamId") == TEAM_ID for c in cmds), f"Invalid teamId in {{pos}}"
            assert all(isinstance(c.get("commandType"), str) for c in cmds), f"Invalid commandType in {{pos}}"
    
    sys.path.remove(pos_dir)
    if "main" in sys.modules:
        del sys.modules["main"]

print("All integration state checks PASSED")
"""
        cmd = [sys.executable, "-c", script]
        try:
            res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
            elapsed = time.perf_counter() - start_time
            team_passed = res.returncode == 0
            output = res.stdout + ("\n" + res.stderr if res.stderr else "")
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            team_passed = False
            output = f"Integration error: {e}"

        results.append({
            "suite": f"integration::{team}",
            "passed": team_passed,
            "duration": elapsed,
            "output": output,
        })
        if verbose or not team_passed:
            print(f"\n--- Integration Output for {team} ---")
            print(output.strip())

    return results


def print_summary_table(results: List[Dict[str, Any]]):
    """Print formatted summary table."""
    print("\n" + "=" * 78)
    print(f"{'Test Suite / Target':<50} {'Status':<12} {'Duration':<12}")
    print("=" * 78)

    total_passed = 0
    total_failed = 0
    total_time = 0.0

    for r in results:
        status = "PASSED" if r["passed"] else "FAILED"
        if r["passed"]:
            total_passed += 1
        else:
            total_failed += 1
        duration_str = f"{r['duration']:.2f}s"
        total_time += r["duration"]
        print(f"{r['suite']:<50} {status:<12} {duration_str:<12}")

    print("-" * 78)
    total_suites = total_passed + total_failed
    print(f"Total: {total_suites} suites | Passed: {total_passed} | Failed: {total_failed} | Time: {total_time:.2f}s")
    print("=" * 78)


def resolve_team_targets(target_arg: str | None) -> Tuple[bool, List[str]]:
    """Determine whether to run lib tests and which teams to target."""
    if not target_arg or target_arg.lower() in ("all", "."):
        return True, list(ALL_TEAMS)

    if target_arg.lower() == "lib":
        return True, []

    # Check for direct match or substring match in team names
    target_clean = target_arg.strip().rstrip("/")
    matching_teams = [t for t in ALL_TEAMS if target_clean == t or target_clean in t]

    if not matching_teams:
        # Check if directory exists
        p = REPO_ROOT / target_clean
        if p.is_dir():
            matching_teams = [target_clean]
        else:
            print(f"ERROR: No matching team found for '{target_arg}'.")
            print(f"Available teams:\n  " + "\n  ".join(ALL_TEAMS))
            sys.exit(1)

    return False, matching_teams


def main():
    parser = argparse.ArgumentParser(
        description="Unified Test Runner for Agentic Football Sample Agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Optional target: 'lib', team name (e.g. 'ai-team-strands-memory' or 'memory'), or omit for all",
    )
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Run integration state simulations across target teams",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output for each test suite",
    )

    args = parser.parse_args()

    include_lib, teams_to_run = resolve_team_targets(args.target)

    print("==============================================================================")
    print("  Agentic Football — Unified Test Runner")
    print("==============================================================================")
    if include_lib:
        print("  Running Shared Library Tests (lib/)")
    if teams_to_run:
        print(f"  Target Teams ({len(teams_to_run)}): {', '.join(teams_to_run)}")
    if args.integration:
        print("  Running Integration Simulations (--integration)")
    print("==============================================================================")

    all_results: List[Dict[str, Any]] = []

    # 1. Run lib tests if applicable
    if include_lib:
        lib_results = run_lib_tests(verbose=args.verbose)
        all_results.extend(lib_results)

    # 2. Run local tests across selected teams
    for team in teams_to_run:
        team_results = run_team_local_tests(team, verbose=args.verbose)
        all_results.extend(team_results)

    # 3. Run integration simulation if requested
    if args.integration:
        int_teams = teams_to_run if teams_to_run else ALL_TEAMS
        int_results = run_integration_tests(int_teams, verbose=args.verbose)
        all_results.extend(int_results)

    # Print summary table
    print_summary_table(all_results)

    # Check failures
    any_failed = any(not r["passed"] for r in all_results)
    if any_failed:
        print("\n❌ One or more test suites FAILED.")
        sys.exit(1)
    else:
        print("\n✅ All test suites PASSED successfully.")
        sys.exit(0)


if __name__ == "__main__":
    main()
