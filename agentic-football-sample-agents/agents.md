# Diamond Team — Agent Documentation & Log Interpretation

## Team Composition (1-2-1 Diamond Formation)

| Player ID | Position | Agent Name | ARN Suffix | Model |
|---|---|---|---|---|
| 0 | Goalkeeper (GK) | Neuer | `agent-b25ePZGB95` | Amazon Nova Micro |
| 1 | Center Back (CB) | Van Dyke | `agent-eqjrqCAoUC` | Amazon Nova Micro |
| 2 | Left Mid (LM) | De Bruyne | `agent-zfxfrq4dd9` | Amazon Nova Micro |
| 3 | Right Mid (RM) | Kane | `agent-lIG5eFDZXJ` | Amazon Nova Micro |
| 4 | Striker (ST) | Mbappe | `agent-5qJkmsFtw1` | Amazon Nova Micro |

---

## Interpreting CloudWatch Logs

### Log Group Structure

Each agent has a log group at:
```
/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_<pos>_agent-<id>-DEFAULT
```

Each log group contains 3 streams:

| Stream | Purpose |
|---|---|
| `spans` | OpenTelemetry traces with full LLM input/output, latency, and token counts |
| `otel-rt-logs` | Runtime operational logs (invocations, command summaries, errors) |
| `2026/08/20/[runtime-logs-...]` | Application-level logs with game state and decisions |

---

### Reading the `spans` Stream

Spans use OpenTelemetry format. The key span types are:

#### 1. `POST /invocations` — HTTP-level request envelope
- No events. Contains only timing and request metadata.

#### 2. `chat` — Full LLM conversation turn(s)
- **This is the most useful span for debugging decisions.**
- Contains multiple events representing the conversation:

| Event Name | Content |
|---|---|
| `gen_ai.system.message` | The system prompt (role rules, allowed commands) |
| `gen_ai.user.message` | Game state summary sent to the LLM each tick |
| `gen_ai.assistant.message` | The LLM's raw JSON command response |
| `gen_ai.choice` | End-of-turn marker (usually empty, signals completion) |

- A single `chat` span can contain **multiple turns** (user→assistant→user→assistant...) representing consecutive ticks within one agent session.

#### 3. `execute_event_loop_cycle` — Strands SDK internal loop
- Contains the user message as an event but not the assistant response.
- Useful for tracking cycle timing.

#### 4. `chat us.amazon.nova-micro-v1:0` — Model invocation metadata
- No events. Contains token counts and latency in `attributes`:
  - `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens`
  - `gen_ai.server.request.duration` (ms)
  - `gen_ai.server.time_to_first_token` (ms)

---

### Key Attributes in Spans

```json
{
  "gen_ai.usage.prompt_tokens": 757,
  "gen_ai.usage.output_tokens": 25,
  "gen_ai.server.request.duration": 359,
  "gen_ai.server.time_to_first_token": 298,
  "gen_ai.request.model": "us.amazon.nova-micro-v1:0",
  "session.id": "aa4c925e-...-team0-pos0"
}
```

- **session.id**: Format is `<match-id>-team<N>-pos<N>`. Use this to correlate all 5 agents in a single match.
- **Duration**: End-to-end LLM call time. Target is <300ms.
- **Token counts**: System prompt is ~750 tokens, game state is ~200 tokens, output is ~25 tokens per tick.

---

### Reading the Runtime Logs Stream

The runtime logs (`otel-rt-logs` or date-prefixed streams) contain structured JSON entries:

```json
{
  "timestamp": "2026-08-20T08:30:03.283Z",
  "level": "INFO",
  "message": "LLM returned 1 commands: ['MOVE_TO']",
  "logger": "bedrock_agentcore.app",
  "requestId": "170d14f8-...",
  "sessionId": "...-team0-pos0"
}
```

Key log messages to look for:

| Message Pattern | Meaning |
|---|---|
| `"<POS> agent invoked for team X, controlling player Y"` | Start of a tick invocation |
| `"LLM returned N commands: [...]"` | Successful LLM parse — shows final sanitized command types |
| `"Fast-path returned commands: ..."` | Deterministic fast-path skipped LLM (lower latency) |
| `"[WARN] recovered malformed JSON"` | LLM output needed tolerance parsing — prompt may need tuning |
| `"fallback"` | Layer 2 (rule-based) was used instead of LLM |
| `"ERROR"` / `"Exception"` / `"Traceback"` | Agent failure — check for model throttling or timeout |

---

### Game State Fields in User Messages

Each tick, the LLM receives a compact game state prompt. Key fields:

```
Time: 220s | Score: 0-0 | Team: 0 (HOME) | PlayMode: OPEN_PLAY
Ball: (-0.0, 0.2) held by free
Your goal at x=-55 | Opponent goal at x=55

>>> YOUR PLAYER (GK, id=0): pos=(-6.4,0.5) stam=100 distBall=6.4 hasBall=False

Teammates:
  P1(id=1): (-6.4,-1.2)
  ...

Opponents:
  P0: (-6.2,-0.4) distToMyGoal=48.8 distToMe=0.9
  ...

>>> YOU (GK, id=0): pos=(-6.4,0.5) stam=100 distBall=6.4 goalVec=(61.4,-0.5)
    nearestOpp=0.9 blockers=3 amNearestToBall=false attackingThird=false
    ballSide=center scoreDiff=+0 gameTime=220s
```

**Tactical awareness fields** (injected by `summarize_state` with `tactical=True`):

| Field | Description | Used By |
|---|---|---|
| `amNearestToBall` | Whether this player is closest outfield to ball | Anti-swarm press rule |
| `attackingThird` | Whether in the attacking third (x > 55/3 for team 0) | Shot discipline gate |
| `blockers` | Number of opponents between player and opponent goal | Shot discipline gate |
| `ballSide` | `left`, `right`, or `center` | Flank pressing rules |
| `scoreDiff` | Goal difference from this team's perspective | Chasing/lead adjustments |
| `nearestOpp` | Distance to closest opponent | Pressing urgency |

---

## Identifying Contradictions in Logs

A **contradiction** is when the LLM issues a command that violates the agent's programmed role rules. The `sanitize_commands()` layer catches and corrects these post-LLM, but they reveal prompt effectiveness issues.

### Common Contradiction Patterns

| Contradiction | What to Look For | Root Cause |
|---|---|---|
| **GK out of box** | GK position x > -40 (team 0) or x < 40 (team 1) | Game start positioning or GK drifting after kick-off |
| **GK PRESS_BALL** | GK issuing press commands | LLM ignoring `may_press=False` rule |
| **CB crossing halfway** | CB MOVE_TO with x > 0 (team 0) | LLM not respecting `own_half_only` boundary |
| **Shooting without viability** | SHOOT when `attackingThird=false` or `blockers >= 2` | LLM ignoring shot gate conditions |
| **Wrong-flank pressing** | LM pressing ball on right side (y > 12) or RM pressing left (y < -12) | LLM not factoring `home_y` flank assignment |
| **Sprinting on empty stamina** | Sprint=true when stamina < 30 | LLM ignoring stamina threshold |
| **GK distributing without ball** | GK_DISTRIBUTE when hasBall=false | LLM hallucinating possession |

### How the Sanitizer Resolves Contradictions

The `sanitize_commands()` function in `lib/rules.py` applies corrections:

1. **GK box clamp**: MOVE_TO targets clamped to `x ∈ [-55, -40]` (team 0)
2. **CB half clamp**: MOVE_TO targets clamped to `x ≤ 0` (team 0)
3. **Anti-swarm**: Secondary PRESS_BALL converted to MARK or MOVE_TO home
4. **Shot gate**: Invalid SHOOT converted to PASS to best-positioned teammate
5. **Stamina guard**: Sprint disabled when stamina < 30%
6. **Wrong-flank press**: Converted to MOVE_TO zonal position

### Monitoring Contradiction Rate

Run the `lib/monitor_logs.py` script to scan recent CloudWatch logs:

```bash
python lib/monitor_logs.py
```

Or query spans directly:
```bash
aws logs filter-log-events \
  --region us-east-1 \
  --log-group-name "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_gk_agent-b25ePZGB95-DEFAULT" \
  --log-stream-names "spans" \
  --limit 100 \
  --output json
```

### Interpreting Contradiction Severity

- **HIGH** — Structural violation (GK outside box, CB in opponent half, shooting without viability). Indicates the LLM is fundamentally ignoring positional constraints. Consider prompt rewording or adding few-shot examples.
- **MEDIUM** — Tactical violation (pressing from wrong flank, sprinting on low stamina, distributing to wrong player). The sanitizer corrects these, but they waste an LLM inference cycle. Consider adding explicit `IF/THEN` rules to the system prompt.
- **LOW** — Stylistic violation (GK sprinting, ST deep retreat). Minor inefficiencies that don't break gameplay.

---

## Telemetry from Most Recent Match (Aug 20, 2026)

| Metric | Value |
|---|---|
| Total LLM decisions analysed | 4,610 |
| Contradictions detected | 1,992 (43.2% rate) |
| HIGH severity | 1,394 |
| MEDIUM severity | 598 |

### Top Issues Found

1. **GK_OUT_OF_BOX (930 occurrences)** — GK positioned at x≈5.9 instead of x≥40 (team 1). Caused by early-game kick-off positioning before the GK reaches its box. The sanitizer clamps movement but can't teleport the player back.

2. **ST_SHOOT_NO_ATT / ST_SHOOT_BLOCKED (193 each)** — Striker (Mbappe) repeatedly attempting shots from midfield (x≈1.0) with 3 blockers. The shot discipline gate converts these to passes, but the LLM keeps trying. Recommend adding explicit "DO NOT shoot when blockers>=2" to the ST system prompt.

3. **CB_CROSS_HALFWAY (66 occurrences)** — CB (Van Dyke) attempting to move to x=-55 when playing as team 1 (where own half is x≥0). The LLM is confused about direction when team_id=1. Recommend clarifying goal direction in the prompt for team 1 scenarios.

4. **SPRINT_LOW_STAMINA (598 occurrences)** — RM (Kane) sprinting at stamina=1. The stamina system uses a 0-1 scale in the game engine but is displayed as integer in prompts. The LLM sees "stam=1" and doesn't realize this means 1% not 100%. Recommend normalizing to percentage display.

5. **RM_SHOOT_NO_ATT (12 occurrences)** — Kane shooting from x≈-1.6 (deep in own half as team 1). Same directional confusion as CB.

### Per-Player Violation Count

| Player | Violations | Primary Issue |
|---|---|---|
| GK (Neuer) | 930 | Out-of-box positioning |
| CB (Van Dyke) | 66 | Directional confusion (team 1) |
| LM (De Bruyne) | 0 ✅ | Clean |
| RM (Kane) | 610 | Stamina sprint + invalid shots |
| ST (Mbappe) | 386 | Shot discipline violations |
