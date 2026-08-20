"""Game state summarization utilities for AI soccer agents."""

import math


# ---------------------------------------------------------------------------
# Format-agnostic helpers — handle both new (agentId/teamCode/possessionAgentId)
# and old (playerId/teamId/possessionPlayerId) game server formats.
# ---------------------------------------------------------------------------

def _player_idx(p: dict) -> int:
    """Numeric index (0-4) from a player dict — new agentId or old playerId."""
    if not isinstance(p, dict):
        return 0
    agent_id = p.get("agentId")
    if isinstance(agent_id, str):
        try:
            return int(agent_id.rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            import re
            digits = re.findall(r"\d+", agent_id)
            if digits:
                return int(digits[-1])
    pid = p.get("playerId")
    if pid is not None:
        try:
            return int(pid)
        except (ValueError, TypeError):
            return 0
    return 0


def _is_my_team(p: dict, team_id: int) -> bool:
    """True if player belongs to team_id — new teamCode or old teamId."""
    if not isinstance(p, dict):
        return False
    tc = p.get("teamCode")
    if isinstance(tc, str):
        target = "home" if int(team_id) == 0 else "away"
        return tc.lower() == target
    tid = p.get("teamId")
    if tid is not None:
        try:
            return int(tid) == int(team_id)
        except (ValueError, TypeError):
            return False
    return False


def _possession_idx(ball: dict) -> int | None:
    """Numeric possession player index from ball dict — new possessionAgentId or old possessionPlayerId.
    Returns int or None."""
    if not isinstance(ball, dict) or ball.get("isFree") is True:
        return None
    agent_id = ball.get("possessionAgentId")
    if isinstance(agent_id, str) and agent_id and agent_id.lower() not in ("none", "null", "-1"):
        try:
            idx = int(agent_id.rsplit("_", 1)[-1])
            return idx if 0 <= idx <= 9 else None
        except (ValueError, IndexError):
            import re
            digits = re.findall(r"\d+", agent_id)
            if digits:
                idx = int(digits[-1])
                return idx if 0 <= idx <= 9 else None
    pid = ball.get("possessionPlayerId")
    if pid is not None:
        try:
            idx = int(pid)
            return idx if 0 <= idx <= 9 else None
        except (ValueError, TypeError):
            return None
    return None


def get_goal_positions(team_id: int) -> tuple[float, float]:
    """Return (my_goal_x, opp_goal_x) based on team."""
    if int(team_id) == 0:
        return -55.0, 55.0
    return 55.0, -55.0


def get_possession_info(ball: dict, players: list, team_id: int) -> tuple:
    """Return (possession_id, ball_status_str, we_have_ball)."""
    possession_id = _possession_idx(ball)
    if possession_id is not None:
        poss_agent_id = ball.get("possessionAgentId")
        holder = None
        if poss_agent_id:
            holder = next((p for p in players if p.get("agentId") == poss_agent_id), None)
        if not holder:
            poss_tc = ball.get("possessionTeamCode")
            poss_tid = ball.get("possessionTeamId")
            if poss_tc is not None:
                holder = next(
                    (p for p in players if _player_idx(p) == possession_id and str(p.get("teamCode", "")).lower() == str(poss_tc).lower()),
                    None,
                )
            elif poss_tid is not None:
                holder = next(
                    (p for p in players if _player_idx(p) == possession_id and _is_my_team(p, poss_tid)),
                    None,
                )
            else:
                holder = next((p for p in players if _player_idx(p) == possession_id), None)
        if holder:
            is_mine = _is_my_team(holder, team_id)
            side = "MY" if is_mine else "OPP"
            return possession_id, f"{side} player {possession_id}", is_mine
        return possession_id, "unknown", False
    return None, "free", False


def dist(pos1: dict, pos2: dict) -> float:
    """Euclidean distance between two position dicts with x,y keys."""
    return math.sqrt(
        (pos1.get("x", 0) - pos2.get("x", 0)) ** 2
        + (pos1.get("y", 0) - pos2.get("y", 0)) ** 2
    )


def shot_blockers(me_pos: dict, opp_goal_x: float, opponents: list, cone_deg: float = 15.0) -> int:
    """Count opponents inside the shot cone (±cone_deg of line me→opp goal center)
    who are closer to the goal than me."""
    me_x = me_pos.get("x", 0.0)
    me_y = me_pos.get("y", 0.0)
    v_gx = opp_goal_x - me_x
    v_gy = 0.0 - me_y
    d_goal = math.sqrt(v_gx ** 2 + v_gy ** 2)
    if d_goal == 0:
        return 0

    cos_cone = math.cos(math.radians(cone_deg))
    count = 0
    for p in opponents:
        opp_pos = p.get("position", {})
        opp_x = opp_pos.get("x", 0.0)
        opp_y = opp_pos.get("y", 0.0)

        # Distance from opponent to opp goal
        d_opp_goal = math.sqrt((opp_goal_x - opp_x) ** 2 + opp_y ** 2)
        if d_opp_goal >= d_goal:
            continue

        v_ox = opp_x - me_x
        v_oy = opp_y - me_y
        d_opp = math.sqrt(v_ox ** 2 + v_oy ** 2)
        if d_opp == 0:
            count += 1
            continue

        dot = v_gx * v_ox + v_gy * v_oy
        if dot <= 0:
            continue

        cos_angle = dot / (d_goal * d_opp)
        cos_angle = max(-1.0, min(1.0, cos_angle))
        if cos_angle >= cos_cone:
            count += 1

    return count


def is_nearest_to_ball(my_pos: dict, my_player_id: int, teammates: list, ball_pos: dict) -> bool:
    """True if I am the nearest OUTFIELD teammate (exclude player 0/GK) to the ball.
    Tie-break: within 1.0 units, lower player id wins (deterministic across agents)."""
    if my_player_id == 0:
        return False

    my_d = dist(my_pos, ball_pos)
    for p in teammates:
        pid = _player_idx(p)
        if pid == 0 or pid == my_player_id:
            continue
        p_d = dist(p.get("position", {}), ball_pos)
        if p_d < my_d - 1.0:
            return False
        if abs(p_d - my_d) <= 1.0 and pid < my_player_id:
            return False
    return True


def is_attacking_third(pos_x: float, team_id: int) -> bool:
    """True if pos_x is in the final third toward the opponent goal.
    Team 0: pos_x > 55/3 ≈ 18.3. Team 1: pos_x < -18.3."""
    if team_id == 0:
        return pos_x > (55.0 / 3.0)
    return pos_x < (-55.0 / 3.0)


def ball_side(ball_y: float) -> str:
    """'left' if ball_y < -5, 'right' if ball_y > 5, else 'center'."""
    if ball_y < -5.0:
        return "left"
    elif ball_y > 5.0:
        return "right"
    return "center"


def get_score_diff(game_state: dict, team_id: int) -> int:
    """Return score_diff = my_score - opp_score."""
    score = game_state.get("score", {})
    if not isinstance(score, dict):
        return 0
    if team_id == 0:
        my_s = score.get("home", score.get("team0", score.get(0, score.get("0", 0))))
        opp_s = score.get("away", score.get("team1", score.get(1, score.get("1", 0))))
    else:
        my_s = score.get("away", score.get("team1", score.get(1, score.get("1", 0))))
        opp_s = score.get("home", score.get("team0", score.get(0, score.get("0", 0))))
    try:
        return int(my_s or 0) - int(opp_s or 0)
    except (ValueError, TypeError):
        return 0


def point_to_segment_dist(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance from point (px, py) to line segment (x1, y1)-(x2, y2)."""
    dx = x2 - x1
    dy = y2 - y1
    l2 = dx * dx + dy * dy
    if l2 == 0.0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def is_lane_blocked(
    p_from: dict | tuple[float, float],
    p_to: dict | tuple[float, float],
    opponents: list[dict],
    clearance: float = 2.5,
) -> bool:
    """True if any opponent is within clearance distance of the line segment from p_from to p_to."""
    x1 = p_from.get("x", 0.0) if isinstance(p_from, dict) else p_from[0]
    y1 = p_from.get("y", 0.0) if isinstance(p_from, dict) else p_from[1]
    x2 = p_to.get("x", 0.0) if isinstance(p_to, dict) else p_to[0]
    y2 = p_to.get("y", 0.0) if isinstance(p_to, dict) else p_to[1]

    for opp in opponents:
        pos = opp.get("position", opp) if isinstance(opp, dict) else opp
        ox = pos.get("x", 0.0) if isinstance(pos, dict) else pos[0]
        oy = pos.get("y", 0.0) if isinstance(pos, dict) else pos[1]
        if point_to_segment_dist(ox, oy, x1, y1, x2, y2) < clearance:
            return True
    return False


def get_far_post_aim(opp_gk_y: float, prefer_top: bool = True) -> str:
    """Compute far-post shot corner given opponent GK y position.
    If opp GK on left (y < 0) -> aim right ("TR" / "BR").
    If opp GK on right (y >= 0) -> aim left ("TL" / "BL")."""
    if opp_gk_y < 0:
        return "TR" if prefer_top else "BR"
    return "TL" if prefer_top else "BL"


def summarize_state(
    game_state: dict,
    team_id: int,
    my_player_id: int,
    position_label: str,
    tactical: bool = False,
) -> str:
    """Build a concise text summary of the game state for a single-player agent."""
    ball = game_state.get("ball", {})
    ball_pos = ball.get("position", {"x": 0, "y": 0})
    score = game_state.get("score", {})
    game_time = game_state.get("gameTime", 0)
    play_mode = game_state.get("playMode", 0)
    players = game_state.get("players", [])

    my_team = sorted(
        [p for p in players if _is_my_team(p, team_id)],
        key=lambda p: _player_idx(p),
    )
    opponents = sorted(
        [p for p in players if not _is_my_team(p, team_id)],
        key=lambda p: _player_idx(p),
    )

    me = next((p for p in my_team if _player_idx(p) == my_player_id), None)
    possession_id, ball_status, _ = get_possession_info(ball, players, team_id)

    my_goal_x, opp_goal_x = get_goal_positions(team_id)

    lines = [
        f"Time: {game_time:.0f}s | Score: {score.get('home',0)}-{score.get('away',0)} | "
        f"Team: {team_id} ({'HOME' if team_id == 0 else 'AWAY'}) | PlayMode: {play_mode}",
        f"Ball: ({ball_pos.get('x',0):.1f}, {ball_pos.get('y',0):.1f}) held by {ball_status}",
        f"Your goal at x={my_goal_x:.0f} | Opponent goal at x={opp_goal_x:.0f}",
        "",
    ]

    # My player info
    if me:
        pos = me.get("position", {})
        stam_raw = me.get("stamina", 100)
        # Normalize: engine uses 0.0-1.0 scale, but LLM needs percentage (0-100)
        stam = stam_raw * 100 if stam_raw <= 1.0 else stam_raw
        stam_display = f"{stam:.0f}%"
        dist_ball = dist(pos, ball_pos)
        has_ball = possession_id == my_player_id
        extra = f" distOppGoal={abs(pos.get('x', 0) - opp_goal_x):.1f}" if position_label in ("MID", "FWD1", "FWD2") else ""
        lines.append(
            f">>> YOUR PLAYER ({position_label}, id={my_player_id}): "
            f"pos=({pos.get('x',0):.1f},{pos.get('y',0):.1f}) "
            f"stam={stam_display} distBall={dist_ball:.1f}{extra} hasBall={has_ball}"
        )
    lines.append("")

    # Teammates
    lines.append("Teammates:")
    for p in my_team:
        if _player_idx(p) == my_player_id:
            continue
        pos = p.get("position", {})
        pid = _player_idx(p)
        role = "GK" if pid == 0 else f"P{pid}"
        extra = ""
        if position_label == "MID":
            extra = f" distOppGoal={abs(pos.get('x', 0) - opp_goal_x):.1f}"
        lines.append(f"  {role}(id={pid}): ({pos.get('x',0):.1f},{pos.get('y',0):.1f}){extra}")

    lines.append("")

    # Opponents
    opp_header = "Opponents (defenders to watch):" if position_label in ("FWD1", "FWD2") else "Opponents:"
    lines.append(opp_header)
    for p in opponents:
        pos = p.get("position", {})
        pid = _player_idx(p)
        d_goal = abs(pos.get("x", 0) - my_goal_x)
        d_me = dist(pos, me.get("position", {})) if me else 0
        lines.append(f"  P{pid}: ({pos.get('x',0):.1f},{pos.get('y',0):.1f}) distToMyGoal={d_goal:.1f} distToMe={d_me:.1f}")

    if tactical and me:
        pos = me.get("position", {})
        stam_raw = me.get("stamina", 100)
        stam_val = stam_raw * 100 if stam_raw <= 1.0 else stam_raw
        stam_display = f"{stam_val:.0f}%"
        dist_ball = dist(pos, ball_pos)
        goal_vec_x = opp_goal_x - pos.get("x", 0)
        goal_vec_y = 0.0 - pos.get("y", 0)
        nearest_opp_dist = min([dist(p.get("position", {}), pos) for p in opponents], default=99.0) if opponents else 99.0
        blockers = shot_blockers(pos, opp_goal_x, opponents)
        am_nearest = is_nearest_to_ball(pos, my_player_id, my_team, ball_pos)
        att_third = is_attacking_third(pos.get("x", 0), team_id)
        bside = ball_side(ball_pos.get("y", 0))
        score_diff = get_score_diff(game_state, team_id)
        lines.append("")
        lines.append(
            f">>> YOU ({position_label}, id={my_player_id}): "
            f"pos=({pos.get('x',0):.1f},{pos.get('y',0):.1f}) "
            f"stam={stam_display} distBall={dist_ball:.1f} "
            f"goalVec=({goal_vec_x:.1f},{goal_vec_y:.1f}) "
            f"nearestOpp={nearest_opp_dist:.1f} blockers={blockers} "
            f"amNearestToBall={str(am_nearest).lower()} "
            f"attackingThird={str(att_third).lower()} ballSide={bside} "
            f"scoreDiff={score_diff:+d} gameTime={game_time:.0f}s"
        )

    return "\n".join(lines)
