# Implementation Plan: 1–2–1 Diamond Strategy Team (`ai-team-strands-diamond`)

**Audience:** implementing agent (Gemini). This document is self-contained — everything
you need is here. Read it fully before writing code.

**Goal:** Build a new 5-agent 5v5 soccer team implementing a 1–2–1 diamond formation with
deterministic tactical guardrails, optimized for sub-300ms per-tick decisions. Victory
depends on spatial geometry, latency optimization, and strict action diversity — not
conversational reasoning. A missed 1-second deadline = an IDLE tick = fatal passing lanes.

---

## 1. Repo Orientation

You are in a repo of sample teams for an agentic football environment. Each team is 5
independent agents (one per player), each deployed separately to Amazon Bedrock AgentCore
using the Strands Agents SDK. There is **no cross-agent communication** — every agent
receives the full game state each tick and returns commands for its own player only.

### File map

```
agentic-football-sample-agents/
├── lib/                          # SHARED library — single source of truth for ALL teams
│   ├── agent_base.py             # create_agent() + create_invoke_handler() (3-layer error handling)
│   ├── state.py                  # summarize_state() → text summary of game state for the LLM
│   ├── fallback.py               # FallbackConfig dataclass + build_fallback() rule-based commands
│   ├── parsing.py                # parse_commands() extracts/validates JSON commands from LLM output
│   ├── json_tolerant.py          # recovers Python-flavoured JSON (True/False/None, trailing commas)
│   ├── _bootstrap.py             # resolves lib/ path for local dev and deployed envs
│   ├── test_helpers.py           # mock AgentCore app + sample game state for local tests
│   └── test_parsing.py           # parsing test suite
├── ai-team-strands-balanced/     # existing team (DO NOT MODIFY)
├── ai-team-strands-extremely-aggressive/   # existing team (DO NOT MODIFY)
├── ai-team-strands-extremely-defensive/    # existing team (DO NOT MODIFY)
├── ai-team-strands-gateway/      # existing team (DO NOT MODIFY)
├── ai-team-strands-memory/       # existing team (DO NOT MODIFY)
└── ai-team-strands-diamond/      # ← YOU CREATE THIS
```

### Team directory structure (copy from `ai-team-strands-balanced/`)

```
ai-team-strands-diamond/
├── ai-gk/    src/main.py, pyproject.toml, requirements.txt, test_local.py, .bedrock_agentcore.yaml.template
├── ai-def/   (same)
├── ai-mid/   (same)
├── ai-fwd1/  (same)
├── ai-fwd2/  (same)
├── agentcore/agentcore.json      # runtime entries per agent
├── deploy_all.py                 # build+deploy; temporarily copies lib/ into each agent dir
└── README.md
```

### How an agent works (every `main.py` follows this pattern)

1. `MY_PLAYER_ID` (0–4) + `POSITION_LABEL` + `SYSTEM_PROMPT`
2. `fallback_commands = build_fallback(<POSITION>_CONFIG)`
3. `agent = create_agent(SYSTEM_PROMPT, model_id="...")`
4. `create_invoke_handler(app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands, fallback_cfg=<CONFIG>)`

The invoke handler (`lib/agent_base.py`) has 3 layers: LLM response → parsed commands;
else rule-based fallback; else last-resort safe command.

### Game facts

- Player IDs: 0=GK, 1=DEF, 2=MID, 3=FWD1, 4=FWD2 (fixed by game server)
- Field: x ∈ [-55, +55], y ∈ [-35, +35]
- Team 0 (HOME) defends -x, attacks +x. Team 1 (AWAY) defends +x, attacks -x.
- Valid commands: `MOVE_TO` (target_x, target_y, sprint), `PASS` (target_player_id, type:
  GROUND|AERIAL|THROUGH), `SHOOT` (aim_location: TL|TR|BL|BR|CENTER, power 0.0–1.0),
  `SLIDE_TACKLE` (target_player_id, sprint, distance), `PRESS_BALL` (intensity 0.0–1.0),
  `MARK` (target_player_id, tightness: LOOSE|TIGHT), `INTERCEPT` (aggressive: bool),
  `FOLLOW_PLAYER` (target_player_id, target_team, distance), `GK_DISTRIBUTE`
  (target_player_id, method: THROW|KICK), `SET_STANCE` (stance: 0=Balanced/1=Attack/2=Defend),
  `CLEAR_OVERRIDE`, `RESET`.
- Game state dict: `{ball: {position: {x,y}, possessionAgentId|possessionPlayerId},
  players: [{agentId|playerId, teamCode|teamId, position: {x,y}, stamina}], score,
  gameTime, playMode}`. `lib/state.py` already has format-agnostic helpers
  (`_player_idx`, `_is_my_team`, `_possession_idx`, `get_goal_positions`,
  `get_possession_info`, `dist`) — reuse them.

### Hard constraints

- **`lib/` is shared by 5 teams.** All changes must be additive and backwards-compatible:
  new fields default to current behavior; new functions are opt-in. Existing teams'
  behavior must not change.
- Do not modify any existing team directory.
- Follow existing code style (type hints, docstrings, module docstring headers).

---

## 2. The Strategy Being Implemented

### Formation: 1–2–1 Diamond

```
          [ GK ]
            |
         [ CB ]        ← anchor, never crosses halfway
        /      \
    [ LM ]    [ RM ]   ← two-way midfielders, provide width
        \      /
         [ ST ]        ← pivot: hold up, disciplined shooting, press outward
```

### Role remapping (player IDs are fixed; roles are prompt + fallback config)

| Player ID | Dir      | Old role | New role | Model (old → new)        |
|-----------|----------|----------|----------|--------------------------|
| 0         | ai-gk    | GK       | GK       | Nova Micro → Nova Micro  |
| 1         | ai-def   | DEF      | CB       | Nova Lite → Nova Micro   |
| 2         | ai-mid   | MID      | LM       | Nova Pro → **Nova Micro**|
| 3         | ai-fwd1  | FWD1     | RM       | Nova Micro → Nova Micro  |
| 4         | ai-fwd2  | FWD2     | ST       | Nova Lite → Nova Micro   |

All-Micro routing is deliberate (latency). Do not use Nova Pro anywhere.

### Role definitions

- **GK:** hold goal-line center; clear high-danger loose balls; distribute WIDE to LM/RM
  (never through central traffic).
- **CB:** never crosses halfway unless settled attacking possession; MARK central runs;
  INTERCEPT through-balls; CLEAR under pressure.
- **LM/RM:** width in possession; track back into half-spaces out of possession; feed ST
  with angled passes.
- **ST:** HOLD up ball; SHOOT only from high-probability angles; press opponent ball
  carrier outward toward touchlines.

### Tactical phases (encode in prompts AND fallback logic)

| Phase | On-ball agent | Nearest off-ball agent | Distant off-ball agents |
|---|---|---|---|
| In possession | SHOOT if clear lane; else PASS forward or MOVE_TO (dribble) into open space | MOVE_TO open passing pocket / half-space (passing triangles) | Maintain width, cover transition zones |
| Out of possession | — | Nearest agent only: PRESS_BALL or TACKLE | MARK open runners, INTERCEPT passing lanes |
| Danger (own third, pressured) | CLEAR (long AERIAL pass to wide flank) | Drop deep for second balls | Anchor resets to penalty-box edge |

### Edge-case rules (enforce in CODE, reinforce in prompts)

1. **Anti-swarm:** only the single nearest outfield player may PRESS_BALL/SLIDE_TACKLE.
   Everyone else: MARK or lane-blocking MOVE_TO.
2. **Stamina:** no sprint when stamina < 30; wide players jog (no press) when ball is on
   the opposite flank.
3. **Shot discipline:** SHOOT only if in attacking third AND fewer than 2 blocking
   defenders in the shot cone.

---

## 3. Architecture Decision: Deterministic Rules Layer

Prompts guide the LLM; code enforces. Add a sanitizer between parsing and yielding in
`lib/agent_base.py`. Each agent independently computes the facts it needs (nearest to
ball, blockers, etc.) from the game state it already receives — no shared memory needed.

```
LLM response → parse_commands() → sanitize_commands() → yield
                                        ↓ (emptied)
                                  fallback_fn() → sanitize → yield
```

---

## 4. Work Packages

### WP1 — `lib/state.py`: derived tactical metrics

Add these helpers (reuse existing `_player_idx`, `_is_my_team`, `dist`,
`get_goal_positions`):

```python
def shot_blockers(me_pos: dict, opp_goal_x: float, opponents: list, cone_deg: float = 15.0) -> int:
    """Count opponents inside the shot cone (±cone_deg of line me→opp goal center)
    who are closer to the goal than me."""

def is_nearest_to_ball(my_pos: dict, my_player_id: int, teammates: list, ball_pos: dict) -> bool:
    """True if I am the nearest OUTFIELD teammate (exclude player 0/GK) to the ball.
    Tie-break: within 1.0 units, lower player id wins (deterministic across agents)."""

def is_attacking_third(pos_x: float, team_id: int) -> bool:
    """True if pos_x is in the final third toward the opponent goal.
    Team 0: pos_x > 55/3 ≈ 18.3. Team 1: pos_x < -18.3."""

def ball_side(ball_y: float) -> str:
    """'left' if ball_y < -5, 'right' if ball_y > 5, else 'center'."""
```

Extend `summarize_state()` to append one compact tactical line for the controlled player
(keep the whole summary under ~200 tokens — trim elsewhere if needed):

```
>>> YOU (LM, id=2): pos=(-12.0,-14.0) stam=74 distBall=8.2 goalVec=(67.0,3.1) nearestOpp=4.5 blockers=1 amNearestToBall=true attackingThird=false ballSide=left
```

Gate this behind a new optional parameter `tactical: bool = False` on
`summarize_state()` so existing teams' prompts are unchanged.

### WP2 — `lib/rules.py` (NEW FILE): command sanitizer

```python
"""Deterministic tactical guardrails applied to parsed LLM commands."""

@dataclass
class RoleRules:
    label: str                      # "GK" | "CB" | "LM" | "RM" | "ST"
    own_half_only: bool = False     # CB: clamp MOVE_TO targets to own half
    box_only: bool = False          # GK: clamp MOVE_TO targets to box region (within ~15 of own goal x, |y| <= 20)
    may_press: bool = True
    shoot_gate: bool = True         # require attacking third AND blockers < 2
    home_y: float | None = None     # LM → -15, RM → +15 (wide home flank)

def sanitize_commands(
    commands: list[dict],
    game_state: dict,
    team_id: int,
    my_player_id: int,
    rules: RoleRules,
) -> list[dict]:
    """Filter/mutate commands per tactical rules. May return [] (caller falls back)."""
```

Rules, in order:

1. **Schema validation:** drop commands missing required params or with out-of-range
   values (`SHOOT`: valid aim_location + power ∈ [0,1]; `PASS`/`MARK`/`GK_DISTRIBUTE`/
   `FOLLOW_PLAYER`/`SLIDE_TACKLE`: target_player_id int 0–4 ≠ self; `PRESS_BALL`:
   intensity ∈ [0,1]; `MOVE_TO`: numeric target_x/target_y).
2. **Anti-swarm:** strip `PRESS_BALL`/`SLIDE_TACKLE` unless `is_nearest_to_ball(...)`.
   Substitute: `MARK` nearest opponent in my half (TIGHT if in own third, else LOOSE),
   duration 3. If no opponent to mark, drop the command.
3. **Shot discipline:** if `rules.shoot_gate`, strip `SHOOT` unless
   `is_attacking_third` AND `shot_blockers(...) < 2`. Substitute: `PASS` GROUND to the
   teammate closest to the opponent goal (excluding self/GK), else drop.
4. **Role boundaries:** `own_half_only` → clamp MOVE_TO target_x to own half;
   `box_only` → clamp to box region.
5. **Stamina:** if my stamina < 30, force `sprint: false` on MOVE_TO and strip
   PRESS_BALL. If `rules.home_y` is set and `ball_side()` is the opposite flank, strip
   PRESS_BALL (substitute MOVE_TO toward (ball_x * 0.3, home_y) with sprint=false).

### WP3 — `lib/agent_base.py`: wiring + inference caps

1. `create_invoke_handler(...)`: add optional param `role_rules: RoleRules | None = None`.
   When provided, call `sanitize_commands()` on BOTH the LLM-parsed commands and the
   fallback commands (the current fallback presses whenever in range — itself a swarm
   source). If sanitizing empties the LLM command list, fall through to `fallback_fn`
   (existing layer 2). When `role_rules is None`, behavior is identical to today.
2. `create_agent(system_prompt, model_id, max_tokens=150, temperature=0.0)`: pass
   inference config to `BedrockModel` (one command ≈ 40 tokens; capping kills rambling
   and tail latency). Check the installed Strands version's `BedrockModel` kwargs and
   adapt parameter names if needed. Keep defaults so existing callers are unaffected.

### WP4 — `lib/fallback.py`: diamond configs (additive)

Add optional fields to `FallbackConfig` (defaults preserve current behavior):

```python
distribute_wide_ids: list[int] = field(default_factory=list)  # GK: prefer these targets (LM/RM)
clear_when_pressured: bool = False   # CB: own third + opponent within 5 → long AERIAL PASS to wide flank
phase_logic: bool = False            # use diamond phase-ordered decision tree (below)
```

New configs:

```python
CB_CONFIG  = FallbackConfig(possession_action="PASS", pass_exclude_ids=[0],
    default_x_factor=0.55, default_x_ref="my_goal", default_y=0,
    mark_threshold=30.0, mark_tightness="TIGHT",
    clear_when_pressured=True, phase_logic=True,
    press_distance=12.0, press_intensity=0.6,
    default_stance=2, last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2})

LM_CONFIG  = FallbackConfig(possession_action="SHOOT_OR_PASS",
    default_x_factor=0.4, default_x_ref="ball_x", default_y=-15,
    press_distance=15.0, press_intensity=0.6,
    shoot_threshold=20.0, shoot_aim="TL", shoot_power=0.8,
    support_x_factor=0.5, support_y=-15, support_sprint=False,
    phase_logic=True, default_stance=0,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.5}, last_resort_duration=3)

RM_CONFIG  # mirror of LM_CONFIG with y=+15, shoot_aim="TR"

ST_CONFIG  = FallbackConfig(possession_action="SHOOT_OR_ADVANCE",
    advance_x_factor=0.6, advance_y=0, advance_sprint=False,   # hold-up: no sprint
    support_x_factor=0.55, support_y=0, support_sprint=False,
    default_x_factor=0.35, default_x_ref="opp_goal", default_y=0,
    press_distance=15.0, press_intensity=0.7,
    shoot_threshold=20.0, shoot_aim="TR", shoot_power=0.85,
    phase_logic=True, default_stance=1,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.6}, last_resort_duration=3)

GK_DIAMOND_CONFIG = FallbackConfig(  # do NOT rename/replace existing GK_CONFIG
    possession_action="GK_DISTRIBUTE",
    distribute_wide_ids=[2, 3],      # LM/RM — never central
    default_x_factor=0.9, default_x_ref="my_goal", default_y="track_ball",
    default_stance=2, last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2})
```

`phase_logic=True` decision order in `build_fallback()`:

1. I have ball → possession action (GK_DISTRIBUTE honoring `distribute_wide_ids`;
   CLEAR if `clear_when_pressured` and pressured in own third; else existing
   SHOOT_OR_PASS / SHOOT_OR_ADVANCE / PASS logic).
2. Teammate has ball → support MOVE_TO (half-space pocket, sprint per config).
3. Opponent has ball → PRESS_BALL **only if** I am nearest outfield teammate (use
   `is_nearest_to_ball` from state.py) and within `press_distance`; else MARK dangerous
   opponent (existing mark_threshold logic); else INTERCEPT.
4. Default → MOVE_TO default position (sprint=false).

### WP5 — Create `ai-team-strands-diamond/`

1. `cp -r ai-team-strands-balanced ai-team-strands-diamond`; delete all `__pycache__`,
   `agentcore/cdk/node_modules`, `agentcore/cdk/cdk.out`, `.bedrock_agentcore.yaml`
   (keep the `.template`).
2. Rewrite all 5 `src/main.py`: new role, new prompt (<250 tokens each — count them),
   `model_id="us.amazon.nova-micro-v1:0"` for all five, new fallback config, and pass
   `role_rules` to `create_invoke_handler`.
3. `agentcore/agentcore.json`: rename runtimes to `ai_diamond_gk_agent`,
   `ai_diamond_def_agent`, `ai_diamond_mid_agent`, `ai_diamond_fwd1_agent`,
   `ai_diamond_fwd2_agent` (same structure as balanced).
4. `deploy_all.py`: update any team-name constants/paths.
5. `README.md`: brief description of the diamond team (model table, role table).

**Prompt template per role** (adapt; keep each under 250 tokens; keep the JSON response
contract and field facts exactly — parsing depends on them):

```
You are {ROLE} (player {ID}) in a 1-2-1 diamond 5v5 team. One command per tick, JSON only.

POSSESSION (you have ball): {role-specific on-ball priorities}
DEFENDING (opponent has ball): PRESS_BALL only if amNearestToBall=true. Else {role-specific off-ball}.
SUPPORT (teammate has ball): {role-specific support movement}

RULES: {2-4 hard rules referencing the tactical metrics in the state summary}

Commands: MOVE_TO(target_x,target_y,sprint) PASS(target_player_id,type:GROUND|AERIAL|THROUGH)
SHOOT(aim_location:TL|TR|BL|BR|CENTER,power:0-1) PRESS_BALL(intensity) MARK(target_player_id,tightness:LOOSE|TIGHT)
INTERCEPT(aggressive:bool) SET_STANCE(stance:0|1|2){GK only: GK_DISTRIBUTE(target_player_id,method:THROW|KICK)}

Field: x∈[-55,55], y∈[-35,35]. Team 0 attacks +x, team 1 attacks -x.
Reply ONLY: [{"commandType":"...","playerId":{ID},"parameters":{...},"duration":0}]
```

Role-specific content:

- **GK (id 0):** stay on goal line between ball and goal center; INTERCEPT loose balls in
  box; GK_DISTRIBUTE to LM (id 2) or RM (id 3) only — never central. Rules: never sprint;
  never leave box region.
- **CB (id 1):** anchor. Possession: PASS to LM/RM; CLEAR (AERIAL to wide flank) if
  pressured in own third. Defending: MARK most central opponent near own goal; INTERCEPT
  through-balls. Rules: never MOVE_TO past halfway line; press only if nearest.
- **LM (id 2) / RM (id 3):** two-way mid, home flank y≈∓15 / ±15. Possession: SHOOT only
  if attackingThird and blockers<2; else PASS forward to ST or angled to opposite mid;
  else MOVE_TO open space. Support: MOVE_TO half-space pocket forming a triangle with
  ball carrier. Rules: if ballSide is opposite flank, no press — jog to (ball_x*0.3,
  home_y); stam<30 → never sprint.
- **ST (id 4):** pivot. Possession: SHOOT only if attackingThird and blockers<2; else
  PASS to LM/RM; else MOVE_TO with sprint=false (hold up). Defending: if
  amNearestToBall, PRESS_BALL steering carrier toward nearest touchline (position between
  carrier and field center). Rules: never pass backward into own third.

### WP6 — Tests

1. New `lib/test_rules.py` (mirror style of `lib/test_parsing.py`): one test per rule —
   swarm strip + MARK substitute, shot gate (0 blockers → kept; 2 blockers → stripped),
   CB halfway clamp, GK box clamp, stamina sprint strip, opposite-flank press strip,
   schema drops (bad power, self-pass, missing target).
2. Extend `lib/test_helpers.py` sample states: 0-blocker shot, 2-blocker shot, ball on
   opposite flank, stamina=25, two teammates equidistant from ball (tie-break).
3. Update each diamond agent's `test_local.py` expectations for new configs.
4. Run: `python3 lib/test_parsing.py` (no regressions), `python3 lib/test_rules.py`,
   and each `ai-team-strands-diamond/ai-*/test_local.py`.

---

## 5. Acceptance Criteria

- [ ] `lib/` changes are additive; existing teams' tests still pass unchanged.
- [ ] `lib/rules.py` implements all 5 rule groups; each has ≥1 unit test.
- [ ] `summarize_state(..., tactical=True)` emits the tactical line; default behavior unchanged.
- [ ] All 5 diamond prompts < 250 tokens each; all 5 agents on `us.amazon.nova-micro-v1:0`.
- [ ] `create_agent` caps `max_tokens=150`, `temperature=0.0` (or Strands equivalent).
- [ ] Anti-swarm is deterministic: two agents at equal ball distance → lower player ID presses.
- [ ] GK fallback distributes only to player IDs 2 or 3.
- [ ] CB fallback/LLM commands never target x past the halfway line toward the opponent goal.
- [ ] All local tests pass: `python3 lib/test_parsing.py`, `python3 lib/test_rules.py`,
      `python3 ai-team-strands-diamond/ai-{gk,def,mid,fwd1,fwd2}/test_local.py`.
- [ ] `python3 ai-team-strands-diamond/ai-gk/test_local.py --llm` works with AWS creds
      (run at least one --llm smoke test if credentials are available).

## 6. Non-Goals

- No AgentCore Memory / gateway coordination (adds latency; conflicts with 1s budget).
- No Pydantic-at-inference or tool-calling structured output (schema validation lives in
  `rules.py`; `json_tolerant.py` already handles malformed JSON upstream).
- No changes to existing team directories or their behavior.
- No deployment to AWS (leave `deploy_all.py` ready to run; the human deploys).

## 7. Deploy (human step, after acceptance)

```bash
cd ai-team-strands-diamond
AWS_DEFAULT_REGION=us-east-1 python deploy_all.py
```
