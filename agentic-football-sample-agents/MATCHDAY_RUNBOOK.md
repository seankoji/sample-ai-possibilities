# Matchday Runbook — AWS Agentic Football Cup

Courtside reference: which team to field, what to tell them, and when. Plus the
`teamChat` coaching-handling code your agents need (currently **no team reads
`teamChat`** — adding it is free advantage).

---

## 1. Pre-Match Checklist

- [ ] `python3 run_tests.py` — all 32 suites green
- [ ] Diamond team deployed: `cd ai-team-strands-diamond && AWS_DEFAULT_REGION=us-east-1 python deploy_all.py`
- [ ] Coaching code (§6) wired in and redeployed — without it, instructions do nothing
- [ ] Know your kickoff: you attack +x as HOME (team 0), -x as AWAY (team 1)

## 2. Team Selection vs. Opponent

| Scout report on opponent | Field this team | Why |
|---|---|---|
| Unknown / first look | **Diamond** | Best shape discipline + lowest latency; rules layer prevents self-inflicted wounds |
| Swarms the ball (2+ players pressing) | **Diamond** | Anti-swarm keeps your shape; one pass beats their press; their stamina dies by minute 4 |
| Parks the bus (everyone deep) | **Diamond**, coach ATTACKING early | Shot discipline avoids donating possession; width pulls their block apart |
| High-scoring shootout team | **Diamond**, coach DEFENSIVE when ahead | They win on variance; you win on shot quality |
| You are losing every match badly | **Extremely aggressive** as chaos option | Variance is a strategy when expectation is negative — not before |

Default answer: **the Diamond team.** The other teams are scouting decoys and fallback options.

## 3. Coaching Quick-Reference (phrase → effect)

The classifier (§6) maps your instruction to a **posture** that deterministically changes
agent behavior. Use these exact trigger phrases — the LLM also sees your raw words, but
the posture is what reliably changes play:

| You say (must contain) | Posture | Code effect |
|---|---|---|
| "need a goal", "push forward", "all out", "must score" | **ALL_OUT** | Shoot gate relaxes to blockers<3; CB may cross halfway; LLM told to attack |
| "press higher", "win the ball back", "push up", "attack" | **ATTACKING** | Normal gates; LLM instructed to press and shoot |
| "hold position", "stay back", "defend", "protect the lead", "slow the game", "possession", "keep shape", "drop deep" | **DEFENSIVE** | Shoot gate tightens to blockers<1 (only sitters); CB pinned; LLM told to hold shape |
| "balanced", "revert", "back to normal", "reset" | **BALANCED** | Defaults restored |

Latest instruction wins and persists for the rest of the match (history resets
automatically when a new match starts — detected by gameTime regression).

## 4. Match Timeline Script

| Moment | Send this | Reason |
|---|---|---|
| Kickoff | nothing | BALANCED is correct; gather scout data instead |
| They score first / 0-1 at halfway | "Press higher, win the ball back quickly in their half" | ATTACKING without opening the CB gate yet |
| Still losing, final ~90s | "Push forward, we need a goal" | ALL_OUT: CB joins attack, shoot gate relaxes |
| You go 1-0 up, second half | "Hold position, protect the lead, slow the game down" | DEFENSIVE: no speculative shots, shape over chase |
| 2+ goals up | "Focus on possession, keep shape" | Starve them of the ball; stamina preservation |
| They equalize late | "Back to balanced" then reassess | Reset before re-instructing — avoids contradiction stacking |

## 5. Opponent Counter-Play

- **vs. swarm/press:** never coach DEFENSIVE — their press *wants* you pinned. Stay
  BALANCED; your wide GK distribution + anti-swarm beats them structurally. If losing,
  go straight to ALL_OUT (through balls behind their line are the kill shot).
- **vs. deep block:** coach ATTACKING early ("press higher") — you need volume around
  their box, and their low press can't punish your high line.
- **vs. equal-quality mirror:** don't over-coach. Every instruction is a small
  perturbation; the disciplined team wins the attrition war on IDLE/fallback ticks.
  Coach only on scoreline changes.

## 6. Coaching Dos & Don'ts (from the workshop docs, applied)

- **Be specific:** "win the ball back in the opponent's half" > "press more"
- **One idea per message** — no "press high but stay deep" contradictions
- **Build on history:** instructions accumulate within a match; "revert to balanced"
  works because earlier context exists
- **Don't spam:** each instruction persists until replaced — a stale ALL_OUT from
  minute 1 is still active at minute 5
- **Scope by role when it matters:** "defenders hold position, forwards push higher" —
  the posture is team-wide, but the LLM also reads your raw words and role-scoped
  phrasing helps it

## 7. Code: `teamChat` Handling (add this)

Three pieces: new `lib/coach.py`, a one-line change in `lib/rules.py`, and wiring in
`lib/agent_base.py`. All additive — teams without `role_rules` are unaffected.

### 7a. New file `lib/coach.py`

```python
"""Coaching instruction (teamChat) handling.

Extracts the latest coach instruction from game state, classifies it into a
tactical posture (deterministic keyword match — no extra LLM call), keeps
match-scoped history, and modulates RoleRules so coaching actually changes
behavior instead of being vetoed by the rules layer.
"""

from __future__ import annotations
from dataclasses import replace

DEFENSIVE, BALANCED, ATTACKING, ALL_OUT = "DEFENSIVE", "BALANCED", "ATTACKING", "ALL_OUT"

# Order matters: first match wins. DEFENSIVE before ATTACKING so
# "hold position, wait for counter-attack" classifies DEFENSIVE.
_KEYWORDS = [
    (ALL_OUT,   ["need a goal", "push forward", "all out", "everyone forward", "must score", "go for it"]),
    (DEFENSIVE, ["hold position", "stay back", "defend", "protect the lead", "slow the game",
                 "possession", "keep shape", "drop deep", "park the bus"]),
    (ATTACKING, ["press higher", "win the ball back", "higher press", "push up", "attack",
                 "take more shots", "counter"]),
    (BALANCED,  ["balanced", "revert", "back to normal", "reset", "default"]),
]

# Module-level match state (AgentCore runtimes stay warm between ticks).
_match = {"last_time": 0.0, "posture": BALANCED, "instruction": None}


def _extract_latest(chat) -> str | None:
    """Pull the newest instruction text from teamChat (str or dict entries)."""
    if not isinstance(chat, list) or not chat:
        return None
    last = chat[-1]
    if isinstance(last, str):
        return last
    if isinstance(last, dict):
        for key in ("content", "message", "text", "instruction"):
            if isinstance(last.get(key), str):
                return last[key]
    return None


def classify(text: str) -> str:
    t = text.lower()
    for posture, keywords in _KEYWORDS:
        if any(k in t for k in keywords):
            return posture
    return BALANCED


def apply_posture(rules, posture: str):
    """Return a posture-adjusted copy of RoleRules. None passes through."""
    if rules is None:
        return None
    if posture == ALL_OUT:
        return replace(rules, own_half_only=False, max_shot_blockers=3)
    if posture == DEFENSIVE:
        return replace(rules, max_shot_blockers=1)
    return rules  # BALANCED / ATTACKING: defaults (ATTACKING acts via the prompt line)


def update_coaching(game_state: dict, role_rules):
    """Call once per tick. Returns (prompt_line, effective_rules)."""
    now = float(game_state.get("gameTime", 0) or 0)
    if now < _match["last_time"] - 5:      # clock went backwards → new match
        _match.update(posture=BALANCED, instruction=None)
    _match["last_time"] = now

    instruction = _extract_latest(game_state.get("teamChat"))
    if instruction and instruction != _match["instruction"]:
        _match["instruction"] = instruction
        _match["posture"] = classify(instruction)

    if not _match["instruction"]:
        return "", role_rules
    line = f'\nCOACH: "{_match["instruction"]}" → posture={_match["posture"]}. Obey this posture.'
    return line, apply_posture(role_rules, _match["posture"])
```

### 7b. `lib/rules.py` — two small changes

1. Add to `RoleRules`: `max_shot_blockers: int = 2`
2. In `sanitize_commands`, change the shot gate from `blockers < 2` to
   `blockers < rules.max_shot_blockers`

### 7c. `lib/agent_base.py` — wiring (inside `invoke`, after `game_state` is parsed)

```python
from coach import update_coaching
coach_line, effective_rules = update_coaching(game_state, role_rules)
state_summary = summarize_state(
    game_state, team_id, effective_pid, position_label,
    tactical=(role_rules is not None),
) + coach_line
# ... then use `effective_rules` instead of `role_rules` in every sanitize_commands call
```

### 7d. Tests to add (`lib/test_rules.py` or new `lib/test_coach.py`)

- classify(): each workshop example phrase → expected posture
  ("Press higher, win the ball back quickly" → ATTACKING;
   "Hold position, wait for counter-attack" → DEFENSIVE;
   "Focus on possession, slow the game down" → DEFENSIVE;
   "Push forward, we need a goal" → ALL_OUT)
- teamChat as list of strings AND list of dicts
- ALL_OUT relaxes CB `own_half_only` and raises shot gate to 3 blockers
- gameTime regression resets posture to BALANCED
- empty/missing teamChat → no prompt line, rules unchanged

## 8. Between Matches — Iterate

After each match, check agent logs for:

- `LLM parse failed` / `recovered malformed JSON` rate → prompt or model problem
- Fallback usage rate → if high, the LLM isn't coping; simplify prompts further
- Which rule stripped commands most (add a log line to `sanitize_commands` if missing)
  → that rule is either saving you or fighting the LLM; tune prompts to agree with it
- IDLE ticks → latency; the only fix is smaller prompts/models or warmer runtimes
