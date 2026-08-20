"""
AI Soccer Left Midfielder Agent — Controls ONLY player 2 (Left Midfielder).
Uses Strands SDK + Amazon Nova Micro (1-2-1 Diamond Formation).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, LM_CONFIG
from rules import RoleRules

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 2
POSITION_LABEL = "LM"
ROLE_RULES = RoleRules(label="LM", own_half_only=False, may_press=True, shoot_gate=True, home_y=-8.0)

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are LM (player {MY_PLAYER_ID}) in a 1-2-1 diamond 5v5 team. One command per tick, JSON only.

POSSESSION (you have ball): IF IN SHOOTING RANGE (<28m, blockers<=1) OR INSIDE BOX, IMMEDIATELY FIRST-TIME SHOOT AT FAR POST (power 0.95). Else play 1-2 combination PASS forward to ST (id=4) or switch to RM (id=3).
DEFENDING (opponent has ball): PRESS_BALL only if amNearestToBall=true within 6.5m. If ball on right flank, hold left central channel (target_x=0, target_y=-7.0).
SUPPORT (teammate has ball): Advance in left channel (target_x=0.45*opp_goal_x ≈ 24.7m, target_y=-7.0m) to receive combination pass. NEVER wander onto touchline (|y| > 8.0 is forbidden).

RULES: Never sprint when stamina < 30. Never wander onto perimeter walls (|y| <= 8.0, |x| <= 35.0).

Commands: MOVE_TO(target_x,target_y,sprint) PASS(target_player_id,type:GROUND|AERIAL|THROUGH) SHOOT(aim_location:TL|TR|BL|BR|CENTER,power:0-1) PRESS_BALL(intensity) MARK(target_player_id,tightness:LOOSE|TIGHT) INTERCEPT(aggressive:bool) SET_STANCE(stance:0|1|2)
Field: x in [-55,55], y in [-35,35]. Team 0 attacks +x, team 1 attacks -x.
Reply ONLY: [{{"commandType":"...","playerId":{MY_PLAYER_ID},"parameters":{{...}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(LM_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=LM_CONFIG, role_rules=ROLE_RULES,
)

if __name__ == "__main__":
    app.run()
