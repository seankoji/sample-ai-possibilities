"""
AI Soccer Center Back Agent — Controls ONLY player 1 (Center Back).
Uses Strands SDK + Amazon Nova Micro (1-2-1 Diamond Formation).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, CB_CONFIG
from rules import RoleRules

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 1
POSITION_LABEL = "CB"
ROLE_RULES = RoleRules(label="CB", own_half_only=True, may_press=True, shoot_gate=True)

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are CB (player {MY_PLAYER_ID}) in a 1-2-1 diamond 5v5 team. One command per tick, JSON only.

POSSESSION (you have ball): PASS to LM (id=2) or RM (id=3). If pressured in own third, CLEAR with AERIAL PASS to wide flank.
DEFENDING (opponent has ball): PRESS_BALL only if amNearestToBall=true. Else MARK nearest central opponent near own goal or INTERCEPT passing lanes.
SUPPORT (teammate has ball): Hold defensive anchor position in own half (x around 0.55*my_goal_x, y=0).

RULES: Never cross halfway line (own half only). Press ball only if amNearestToBall=true. Never sprint when stamina < 30.

Commands: MOVE_TO(target_x,target_y,sprint) PASS(target_player_id,type:GROUND|AERIAL|THROUGH) SHOOT(aim_location:TL|TR|BL|BR|CENTER,power:0-1) PRESS_BALL(intensity) MARK(target_player_id,tightness:LOOSE|TIGHT) INTERCEPT(aggressive:bool) SET_STANCE(stance:0|1|2)
Field: x in [-55,55], y in [-35,35]. Team 0 attacks +x, team 1 attacks -x.
Reply ONLY: [{{"commandType":"...","playerId":{MY_PLAYER_ID},"parameters":{{...}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(CB_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=CB_CONFIG, role_rules=ROLE_RULES,
)

if __name__ == "__main__":
    app.run()
