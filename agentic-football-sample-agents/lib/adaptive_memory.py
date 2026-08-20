"""In-Game Adaptive Tactical Intelligence Engine for Agentic Football.

Tracks rolling match telemetry across ticks to detect opponent patterns:
- High Press vs Low Block
- Flank Attack Bias
- Goalkeeper Depth & Stance Profile
- Swarm Tackling Tendency
- Score & Clock Momentum Morphing

Zero latency overhead: Pure in-memory analysis (<0.1ms) on every tick.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from state import (
    _player_idx,
    _is_my_team,
    get_goal_positions,
    get_score_diff,
    dist,
)


@dataclass
class AdaptiveTactics:
    """Live tactical adjustments computed for the current match state."""
    # Press & Build-up Modulation
    direct_counter_mode: bool = False
    box_edge_sniping: bool = False
    
    # Positional Shifts
    defensive_line_shift_y: float = 0.0
    defensive_line_x_factor: float = 0.50
    formation_morph: str = "DIAMOND"  # "DIAMOND", "1-1-2" (all-out), "2-2-0" (lockdown)
    
    # Shooting & Passing Adjustments
    preferred_shot_height: str = "HIGH"  # "HIGH" (TR/TL) or "LOW" (BR/BL)
    wall_pass_enabled: bool = False


class TacticalMemoryTracker:
    """Rolling match memory that accumulates opponent telemetry across ticks."""
    
    def __init__(self):
        self.history_len = 0
        self.high_press_ticks = 0
        self.low_block_ticks = 0
        self.left_flank_attacks = 0
        self.right_flank_attacks = 0
        self.gk_sweeper_ticks = 0
        self.swarm_ticks = 0
        
    def reset(self):
        self.history_len = 0
        self.high_press_ticks = 0
        self.low_block_ticks = 0
        self.left_flank_attacks = 0
        self.right_flank_attacks = 0
        self.gk_sweeper_ticks = 0
        self.swarm_ticks = 0

    def record_tick(self, game_state: dict, team_id: int):
        """Observe opponent positioning and update rolling metrics."""
        self.history_len += 1
        players = game_state.get("players", [])
        opponents = [p for p in players if not _is_my_team(p, team_id)]
        ball = game_state.get("ball", {})
        ball_pos = ball.get("position", {"x": 0, "y": 0})
        my_goal_x, opp_goal_x = get_goal_positions(team_id)

        # 1. High Press Tracking: >= 3 opponents in our defensive half
        opps_in_our_half = sum(
            1 for p in opponents
            if (p.get("position", {}).get("x", 0) < 0 if team_id == 0 else p.get("position", {}).get("x", 0) > 0)
        )
        if opps_in_our_half >= 3:
            self.high_press_ticks += 1

        # 2. Low Block Tracking: >= 4 opponents in their defensive third
        opps_in_box = sum(
            1 for p in opponents
            if (p.get("position", {}).get("x", 0) > 25.0 if team_id == 0 else p.get("position", {}).get("x", 0) < -25.0)
        )
        if opps_in_box >= 4:
            self.low_block_ticks += 1

        # 3. Flank Bias Tracking: when opponent attacks, track left vs right flank
        opp_in_possession = any(_player_idx(p) == ball.get("possessionAgentId") for p in opponents)
        if opp_in_possession or (ball_pos.get("x", 0) < 0 if team_id == 0 else ball_pos.get("x", 0) > 0):
            if ball_pos.get("y", 0) < -6.0:
                self.left_flank_attacks += 1
            elif ball_pos.get("y", 0) > 6.0:
                self.right_flank_attacks += 1

        # 4. Opponent GK Depth Tracking
        opp_gk = next((p for p in opponents if _player_idx(p) == 0), None)
        if opp_gk:
            gk_x = opp_gk.get("position", {}).get("x", opp_goal_x)
            # If GK stands further than 6m off their goal line
            if abs(gk_x - opp_goal_x) > 6.0:
                self.gk_sweeper_ticks += 1

        # 5. Swarm Press Tracking: Opponents within 4.5m of our ball carrier
        my_carrier = next((p for p in players if _is_my_team(p, team_id) and _player_idx(p) == ball.get("possessionAgentId")), None)
        if my_carrier:
            c_pos = my_carrier.get("position", {})
            opps_near = sum(1 for p in opponents if dist(p.get("position", {}), c_pos) < 4.5)
            if opps_near >= 2:
                self.swarm_ticks += 1

    def compute_tactics(self, game_state: dict, team_id: int) -> AdaptiveTactics:
        """Compute the live adaptation coefficients based on rolling memory."""
        tactics = AdaptiveTactics()
        score_diff = get_score_diff(game_state, team_id)
        game_time = float(game_state.get("gameTime", 0) or 0)
        
        # 1. Match Momentum & Formation Morphing
        if game_time > 120.0 and score_diff <= -1:
            # Trailing late in game -> Morph into 1-1-2 All-Out Attack
            tactics.formation_morph = "1-1-2"
            tactics.defensive_line_x_factor = 0.35  # CB pushes to midfield
        elif game_time > 130.0 and score_diff >= 1:
            # Leading late in game -> Morph into 2-2-0 Lockdown Rest-Defense
            tactics.formation_morph = "2-2-0"
            tactics.defensive_line_x_factor = 0.55  # CB anchors deep
        else:
            tactics.formation_morph = "DIAMOND"
            tactics.defensive_line_x_factor = 0.50

        # If we have at least 5 frames of history, activate pattern counters
        if self.history_len >= 5:
            # 2. High Press Counter -> Direct Long-Ball Counter Mode
            if (self.high_press_ticks / self.history_len) > 0.40:
                tactics.direct_counter_mode = True

            # 3. Low Block Counter -> Box Edge Sniping Mode
            if (self.low_block_ticks / self.history_len) > 0.35:
                tactics.box_edge_sniping = True

            # 4. Flank Bias -> Shift defensive line laterally to congest opponent's attack
            total_flank = self.left_flank_attacks + self.right_flank_attacks
            if total_flank >= 4:
                left_ratio = self.left_flank_attacks / total_flank
                if left_ratio > 0.65:
                    tactics.defensive_line_shift_y = -4.0  # Shift left
                elif left_ratio < 0.35:
                    tactics.defensive_line_shift_y = 4.0   # Shift right

            # 5. GK Stance Profiling -> High Lob vs Low Driven
            if (self.gk_sweeper_ticks / self.history_len) > 0.40:
                tactics.preferred_shot_height = "HIGH"  # Chip/Lob over advancing keeper
            else:
                tactics.preferred_shot_height = "LOW"   # Low driven strike

            # 6. Swarm Counter -> Wall Pass Activation
            if (self.swarm_ticks / self.history_len) > 0.30:
                tactics.wall_pass_enabled = True

        return tactics


# Global singleton instance per process (zero initialization cost)
_GLOBAL_TRACKER = TacticalMemoryTracker()


def analyze_and_adapt(game_state: dict, team_id: int) -> AdaptiveTactics:
    """Record current tick telemetry and return live adaptive tactical settings."""
    _GLOBAL_TRACKER.record_tick(game_state, team_id)
    return _GLOBAL_TRACKER.compute_tactics(game_state, team_id)


def reset_adaptive_memory():
    """Reset rolling match memory (used between matches and in unit tests)."""
    _GLOBAL_TRACKER.reset()
