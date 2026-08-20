"""
AI Soccer Right Midfielder Agent — Controls ONLY player 3 (Right Midfielder).
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
from fallback import build_fallback, RM_CONFIG
from rules import RoleRules

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 3
POSITION_LABEL = "RM"
ROLE_RULES = RoleRules(label="RM", own_half_only=False, may_press=True, shoot_gate=True, home_y=8.0)

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are RM (player {MY_PLAYER_ID}) in a 1-2-1 diamond 5v5 team. One command per tick, JSON only.

You are called when the GK has the ball and needs passing options. Think carefully:

GK HAS BALL — YOUR JOB IS TO FIND SPACE ON THE RIGHT FLANK:
  - Position yourself where GK or CB can reach you with a pass/throw.
  - Move into space AWAY from opponents. Check opponent positions — find the gap.
  - Ideal: x=-10 to x=5 (Team 0), y=4 to y=6. This gives a passing triangle with CB and GK.
  - If an opponent is blocking the lane between you and GK, shift wider (y=8) or deeper to open it.
  - If the CB has moved wide, anticipate receiving a pass from CB — position yourself ahead of him.
  - Anticipate a long kick down the RIGHT flank — get into space at x=10 to x=20, y=6.

YOUR FLANK: RIGHT side. y must be POSITIVE (y between 3 and 8).

POSSESSION (you receive the ball): PASS forward to ST (id=4) or switch to LM (id=2). Only SHOOT if attackingThird=true AND blockers<2 (aim_location=BR, power 0.85).

Commands: MOVE_TO(target_x,target_y,sprint) PASS(target_player_id,type:GROUND|AERIAL|THROUGH) SHOOT(aim_location:TL|TR|BL|BR|CENTER,power:0-1)
Field: x in [-55,55], y in [-35,35]. Team 0 attacks +x, team 1 attacks -x.
Reply ONLY: [{{"commandType":"...","playerId":{MY_PLAYER_ID},"parameters":{{...}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(RM_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.anthropic.claude-sonnet-4-20250514-v1:0", max_tokens=80, temperature=0.1)
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=RM_CONFIG, role_rules=ROLE_RULES,
)

if __name__ == "__main__":
    app.run()
