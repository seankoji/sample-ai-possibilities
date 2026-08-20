"""
AI Soccer Striker Agent — Controls ONLY player 4 (Striker).
Uses Strands SDK + Amazon Nova Micro (1-2-1 Diamond Formation).
"""

import os, sys
_here = os.path.dirname(os.path.abspath(__file__))
for _p in [os.path.join(_here, "..", "lib"), os.path.join(_here, "..", "..", "..", "lib")]:
    if os.path.isdir(_p) and os.path.abspath(_p) not in sys.path:
        sys.path.insert(0, os.path.abspath(_p))
try:
    from _bootstrap import setup_lib_path
    setup_lib_path(__file__)
except ImportError:
    pass

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

You are called when the GK has the ball and needs passing options. Think carefully:

GK HAS BALL — YOUR JOB IS TO MAKE A RUN OR HOLD POSITION AS A TARGET:
  - Check if there is SPACE BEHIND the opponent defence (gap between their last defender and GK).
  - If space exists behind: MOVE_TO a position to receive a long ball (x=25 to x=35, y=0). Sprint=true.
  - If defence is deep and no space behind: Hold at x=15 to x=20, y=0 as a short target for a KICK.
  - If you are already in a good receiving position and unmarked, STAY (don't over-run past the defence).
  - NEVER go beyond x=44 (stay out of 6-yard box — you miss from there).

KEY DECISION: Look at the opponent back line x positions. If their last defender is at x>15, there IS space behind for you to run into. If they are at x<5, they are deep — hold your position.

YOUR ZONE: Central corridor, y between -4 and 4. x between 10 and 42 (Team 0).

POSSESSION (you receive the ball): SHOOT if attackingThird=true AND blockers<2 (aim_location=BR, power 0.85). Otherwise PASS to LM (id=2) or RM (id=3).

Commands: MOVE_TO(target_x,target_y,sprint) PASS(target_player_id,type:GROUND|AERIAL|THROUGH) SHOOT(aim_location:TL|TR|BL|BR|CENTER,power:0-1)
Field: x in [-55,55], y in [-35,35]. Team 0 attacks +x, team 1 attacks -x.
Reply ONLY: [{{"commandType":"...","playerId":{MY_PLAYER_ID},"parameters":{{...}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(ST_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.anthropic.claude-sonnet-4-20250514-v1:0", max_tokens=80, temperature=0.1)
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=ST_CONFIG, role_rules=ROLE_RULES,
)

if __name__ == "__main__":
    app.run()
