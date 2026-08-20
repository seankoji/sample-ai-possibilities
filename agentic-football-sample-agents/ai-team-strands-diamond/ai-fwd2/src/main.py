"""
AI Soccer Striker Agent — Controls ONLY player 4 (Striker).
Uses Strands SDK + Amazon Nova Micro (1-2-1 Diamond Formation).
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, ST_CONFIG
from rules import RoleRules

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 4
POSITION_LABEL = "ST"
ROLE_RULES = RoleRules(label="ST", own_half_only=False, may_press=True, shoot_gate=True)

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are ST (player {MY_PLAYER_ID}) in a 1-2-1 diamond 5v5 team. One command per tick, JSON only.

POSSESSION (you have ball): SHOOT only if attackingThird=true and blockers<2. Else hold up ball with MOVE_TO (sprint=false) or PASS to LM (id=2) / RM (id=3).
DEFENDING (opponent has ball): If amNearestToBall=true, PRESS_BALL steering carrier outward toward touchline. Else INTERCEPT or MARK high.
SUPPORT (teammate has ball): MOVE_TO central attacking channel (y=0) to offer forward target pocket.

RULES: SHOOT only when attackingThird=true and blockers<2. Hold-up play: no sprint when advancing. Never pass backward into own third.

Commands: MOVE_TO(target_x,target_y,sprint) PASS(target_player_id,type:GROUND|AERIAL|THROUGH) SHOOT(aim_location:TL|TR|BL|BR|CENTER,power:0-1) PRESS_BALL(intensity) MARK(target_player_id,tightness:LOOSE|TIGHT) INTERCEPT(aggressive:bool) SET_STANCE(stance:0|1|2)
Field: x in [-55,55], y in [-35,35]. Team 0 attacks +x, team 1 attacks -x.
Reply ONLY: [{{"commandType":"...","playerId":{MY_PLAYER_ID},"parameters":{{...}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(ST_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=ST_CONFIG, role_rules=ROLE_RULES,
)

if __name__ == "__main__":
    app.run()
