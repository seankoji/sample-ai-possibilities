"""
AI Soccer Goalkeeper Agent — Controls ONLY player 0 (Goalkeeper).
Uses Strands SDK + Amazon Nova Micro (1-2-1 Diamond Formation).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, GK_DIAMOND_CONFIG
from rules import RoleRules

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 0
POSITION_LABEL = "GK"
ROLE_RULES = RoleRules(label="GK", box_only=True, may_press=False, shoot_gate=True)

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are GK (player {MY_PLAYER_ID}) in a 1-2-1 diamond 5v5 team. One command per tick, JSON only.

POSSESSION (you have ball): GK_DISTRIBUTE to LM (id=2) or RM (id=3) only. Never distribute centrally.
DEFENDING (opponent has ball): Stay on goal line between ball and goal center. INTERCEPT loose balls in box.
SUPPORT (teammate has ball): Hold position in goal area.

RULES: Never sprint. Never leave box region (stay within x in [-55,-40] if team 0, [40,55] if team 1). Never press ball outside box.

Commands: MOVE_TO(target_x,target_y,sprint) PASS(target_player_id,type:GROUND|AERIAL|THROUGH) SHOOT(aim_location:TL|TR|BL|BR|CENTER,power:0-1) PRESS_BALL(intensity) MARK(target_player_id,tightness:LOOSE|TIGHT) INTERCEPT(aggressive:bool) SET_STANCE(stance:0|1|2) GK_DISTRIBUTE(target_player_id,method:THROW|KICK)
Field: x in [-55,55], y in [-35,35]. Team 0 attacks +x, team 1 attacks -x.
Reply ONLY: [{{"commandType":"...","playerId":{MY_PLAYER_ID},"parameters":{{...}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(GK_DIAMOND_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=GK_DIAMOND_CONFIG, role_rules=ROLE_RULES,
)

if __name__ == "__main__":
    app.run()
