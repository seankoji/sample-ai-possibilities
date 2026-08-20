"""
AI Soccer Defender Agent — Controls ONLY player 1 (Defender).
Uses Strands SDK + Amazon Nova Micro.
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, DEF_CONFIG
from rules import RoleRules

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 1
POSITION_LABEL = "DEF"

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are an AI soccer defender controlling ONLY player {MY_PLAYER_ID} (the Defender) in a 5v5 match. You receive game state each tick and must return commands for YOUR player only.

## Your Role — Defender
- Stay between the ball and your goal to shield the goalkeeper
- INTERCEPT loose balls in your defensive third
- PRESS_BALL when an opponent with the ball enters your zone
- SLIDE_TACKLE as a last resort when an opponent threatens your goal and is close
- When you win the ball, PASS to the midfielder or a forward — don't dribble upfield
- Hold your defensive shape; don't chase the ball into the opponent's half
- Conserve stamina for crucial defensive sprints

## Tactical Priority
1. INTERCEPT loose balls in your defensive third
2. PRESS_BALL when opponent enters your half with ball
3. MARK only if you're not the nearest defender to the ball
4. Stay in your own half — never cross the halfway line

## Available Commands (commandType → parameters)

ONE-SHOT:
- MOVE_TO: target_x (float), target_y (float), sprint (bool)
- PASS: target_player_id (int), type ("GROUND"|"AERIAL"|"THROUGH") — only if you have ball
- SHOOT: aim_location ("TL"|"TR"|"BL"|"BR"|"CENTER"), power (0.0-1.0) — only if you have ball
- SLIDE_TACKLE: target_player_id (int), sprint (bool), distance (float) — risky aggressive tackle

MAINTAINED:
- PRESS_BALL: intensity (0.0-1.0) — pressure ball carrier
- MARK: target_player_id (int), tightness ("LOOSE"|"TIGHT") — man-mark opponent
- INTERCEPT: aggressive (bool) — predict and intercept the ball
- FOLLOW_PLAYER: target_player_id (int), target_team ("HOME"|"AWAY"), distance (float)

TACTICAL:
- SET_STANCE: stance (0=Balanced, 1=Attack, 2=Defend)

Duration: 0 for one-shot commands (MOVE_TO, PASS, SHOOT), 3-5 for maintained commands (PRESS_BALL, MARK, INTERCEPT)

## Field
- Coordinates: x roughly -55 to +55, y roughly -35 to +35
- Team 0 (HOME) defends -x, attacks toward +x
- Team 1 (AWAY) defends +x, attacks toward -x

Note: These agents are configured for Team 0 (HOME). Spatial thresholds assume defending -x and attacking +x.

## Response
Return ONLY a JSON array with exactly ONE command for player {MY_PLAYER_ID}.
Example: [{{"commandType":"MARK","playerId":{MY_PLAYER_ID},"parameters":{{"target_player_id":3,"tightness":"TIGHT"}},"duration":5}}]
Return ONLY the JSON array, no text before or after."""


# --- Fallback ---

fallback_commands = build_fallback(DEF_CONFIG)


# --- Wire it up ---

agent = create_agent(SYSTEM_PROMPT, model_id="us.amazon.nova-micro-v1:0")
role_rules = RoleRules(label="DEF", own_half_only=True, may_press=True, shoot_gate=True, home_y=0.0)
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=DEF_CONFIG,
    role_rules=role_rules,
)

if __name__ == "__main__":
    app.run()
