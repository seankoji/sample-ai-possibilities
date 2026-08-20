"""
AI Soccer Goalkeeper Agent — Controls ONLY player 0 (Goalkeeper).
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
from fallback import build_fallback, GK_DIAMOND_CONFIG
from rules import RoleRules

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 0
POSITION_LABEL = "GK"
ROLE_RULES = RoleRules(label="GK", box_only=True, may_press=False, shoot_gate=True)

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are GK (player {MY_PLAYER_ID}). One JSON command per tick.

You are ONLY called when you have the ball and need to distribute it. Analyze the game state carefully:

DECISION FRAMEWORK (think step by step):
1. Check CB (id=1): Is he tightly marked? Look at opponent distances to CB. If an opponent is within 3m of CB, passing to him is DANGEROUS.
2. Check LM (id=2) and RM (id=3): Are they in space? Could you THROW to them to start a quick attack?
3. Check ST (id=4): Is he making a run? Could a long KICK over the defense reach him?
4. Check opponent GK: Is their keeper off their line (far from x=55 or x=-55)? If so, a long-range SHOOT could score!

COMMANDS YOU CAN USE:
- GK_DISTRIBUTE(target_player_id, method:THROW|KICK) — THROW is short/accurate, KICK is long/less accurate
- SHOOT(aim_location:TL|TR|BL|BR|CENTER, power:0-1) — only if opponent GK is way out of position (x < 30 for team 1, x > -30 for team 0)
- PASS(target_player_id, type:GROUND|AERIAL|THROUGH) — ground pass to nearby teammate

RULES:
- NEVER pass to a teammate who has an opponent within 2m of them (they'll get intercepted)
- Prefer THROW to an unmarked midfielder over KICK to a marked striker
- If ALL teammates are marked, KICK long to ST (id=4) — he's the best at winning aerial duels
- A long-range SHOOT is only viable if opponent GK x position shows they are more than 20 units from their goal line

Field: x in [-55,55], y in [-35,35]. Team 0 attacks +x, team 1 attacks -x.
DO NOT explain. DO NOT reason. Output ONLY the JSON array.
Reply ONLY: [{{"commandType":"...","playerId":{MY_PLAYER_ID},"parameters":{{...}},"duration":0}}]"""


# --- Fallback ---

fallback_commands = build_fallback(GK_DIAMOND_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.anthropic.claude-sonnet-4-20250514-v1:0", max_tokens=150, temperature=0.1)
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=GK_DIAMOND_CONFIG, role_rules=ROLE_RULES,
)

if __name__ == "__main__":
    app.run()
