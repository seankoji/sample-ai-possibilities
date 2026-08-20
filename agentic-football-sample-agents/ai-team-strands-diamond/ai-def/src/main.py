"""
AI Soccer Center Back Agent — Controls ONLY player 1 (Center Back).
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
from fallback import build_fallback, CB_CONFIG
from rules import RoleRules

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 1
POSITION_LABEL = "CB"
ROLE_RULES = RoleRules(label="CB", own_half_only=True, may_press=True, shoot_gate=True)

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are CB (player {MY_PLAYER_ID}) in a 1-2-1 diamond 5v5 team. One command per tick, JSON only.

You are called when the GK has the ball and needs passing options. Think carefully:

GK HAS BALL — YOUR JOB IS TO OFFER A SAFE PASSING LANE:
  - Check if opponents are between you and the GK. If yes, MOVE to one side (y=+5 or y=-5) to open a clear lane.
  - If you are tightly marked (opponent within 3m), MOVE AWAY from the marker to create separation.
  - Position yourself at x=-25 to x=-20 (Team 0) to give GK a short safe option.
  - If both midfielders are free, drop slightly deeper (x=-30) so GK can throw to you as a safe reset.
  - If you ARE free and in a good position, stay put — don't over-move.

ALSO CONSIDER:
  - Can you shift wide to open a direct lane from GK to a midfielder behind you?
  - Is there a gap you can exploit by moving laterally?

POSSESSION (you receive the ball): ALWAYS PASS immediately to LM (id=2) or RM (id=3). Never hold it.

Commands: MOVE_TO(target_x,target_y,sprint) PASS(target_player_id,type:GROUND|AERIAL|THROUGH)
Field: x in [-55,55], y in [-35,35]. Team 0 attacks +x, team 1 attacks -x.
Reply ONLY: [{{"commandType":"...","playerId":{MY_PLAYER_ID},"parameters":{{...}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(CB_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.anthropic.claude-sonnet-4-20250514-v1:0", max_tokens=80, temperature=0.1)
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=CB_CONFIG, role_rules=ROLE_RULES,
)

if __name__ == "__main__":
    app.run()
