# Contributing to Agentic Football Sample Agents

Thank you for contributing to the Agentic Football repository! This guide details best practices for creating new teams, authoring system prompts, configuring tactical guardrails, and meeting testing standards.

---

## 1. Adding a New Team via Scaffolding

To maintain uniform directory layouts and automated CDK deployments across teams, always scaffold new teams using `scaffold_team.py`:

```bash
# Scaffold a new team (default base is diamond)
python scaffold_team.py ai-team-strands-<team_name> --base diamond

# Or use balanced base
python scaffold_team.py ai-team-strands-<team_name> --base balanced
```

### Team Directory Structure
The generator creates the standard structure:
```
ai-team-strands-<name>/
├── agentcore/
│   ├── agentcore.json          # CDK project & runtime definitions
│   └── cdk/                    # CDK deployment configuration
├── ai-gk/                      # Goalkeeper (Player ID 0)
│   ├── src/main.py
│   ├── .bedrock_agentcore.yaml.template
│   ├── pyproject.toml
│   └── test_local.py
├── ai-def/                     # Defender / Center Back (Player ID 1)
├── ai-mid/                     # Midfielder / Left Mid (Player ID 2)
├── ai-fwd1/                    # Forward 1 / Right Mid (Player ID 3)
├── ai-fwd2/                    # Forward 2 / Striker (Player ID 4)
├── deploy_all.py               # Automated build & CDK deployment script
├── deploy-all.sh               # Shell deployment wrapper
└── README.md                   # Team-specific documentation
```

---

## 2. System Prompt Design Best Practices

Latency and deterministic command formatting are critical. Small models (such as Amazon Nova Micro) perform best when instructions are compact and strictly structured.

### Guidelines:
1. **Token Budget**: Keep prompts strictly under **250 tokens**.
2. **Explicit Player ID Binding**: Anchor the agent's identity and Player ID in the opening line:
   ```python
   SYSTEM_PROMPT = f"""You are CB (player {MY_PLAYER_ID}) in a 1-2-1 diamond 5v5 team. One command per tick, JSON only."""
   ```
3. **Phased Tactical Triggers**:
   Structure instructions into clear game phases:
   - `POSSESSION (you have ball)`: Shooting conditions, pass target priorities.
   - `DEFENDING (opponent has ball)`: When to press, when to mark or intercept.
   - `SUPPORT (teammate has ball)`: Positioning targets and space creation.
4. **Strict JSON Schema Instruction**:
   State allowable commands concisely and mandate single-command JSON array replies:
   ```
   Reply ONLY: [{"commandType":"...","playerId":<ID>,"parameters":{...},"duration":0}]
   ```
5. **Never Ask for Explanations**: Disallow markdown prose, markdown code fences, or reasoning text in production prompts.

---

## 3. RoleRules Guardrail Definitions & Fallback Hierarchy

To prevent tactical breakdowns (such as all 5 players swarming the ball or defenders abandoning their goal), every agent should configure `RoleRules` from `lib/rules.py`.

### Guardrail Parameters (`RoleRules`)
```python
from rules import RoleRules

# Goalkeeper Guardrails
ROLE_RULES = RoleRules(
    label="GK",
    box_only=True,       # Clamps movements within the penalty box
    may_press=False,     # Forbids leaving goal line to press outfield balls
    shoot_gate=True,     # Prevents unviable shots
)

# Center Back Guardrails
ROLE_RULES = RoleRules(
    label="CB",
    own_half_only=True,  # Clamps target_x <= 0 to prevent over-committing
    may_press=True,      # May only press if amNearestToBall=True
    shoot_gate=True,
)

# Wide Midfielders / Wingers Guardrails
ROLE_RULES = RoleRules(
    label="LM",          # or "RM"
    own_half_only=False,
    may_press=True,
    shoot_gate=True,
    home_y=-15.0,        # Wide flank target coordinate
)
```

### The 3-Layer Resilience Hierarchy
All agent handlers built with `create_invoke_handler` implement three safety layers:
1. **Layer 1 — LLM Response**:
   LLM output $\rightarrow$ parsed via `parse_commands()` $\rightarrow$ sanitized via `sanitize_commands()`.
2. **Layer 2 — Deterministic Fallback**:
   If LLM output is empty or invalid $\rightarrow$ invoke position's `fallback_commands()` $\rightarrow$ sanitized via `sanitize_commands()`.
3. **Layer 3 — Last-Resort Emergency Command**:
   If unhandled exceptions occur $\rightarrow$ return safe stationary command (`MOVE_TO` home coordinate or `SET_STANCE`).

---

## 4. Pre-Deploy Validation & Testing Standards

Before committing code or deploying to Bedrock AgentCore, all test suites must pass.

### Running Tests
Execute the unified test runner:
```bash
# Run all unit tests and local agent tests
python run_tests.py

# Run integration simulation
python run_tests.py --integration
```

### Required Test Checks:
- **Unit Tests**: All tests in `lib/test_parsing.py` and `lib/test_rules.py` must pass.
- **Local Position Tests**: Every position's `test_local.py` must pass schema validation, fallback generation, and player ID clamping.
- **Pre-Deploy Gate**: Both `deploy_all.py` and `deploy-all.sh` will automatically run `test_local.py` for each position before staging or executing `agentcore deploy`. If any test fails, deployment is aborted immediately.
- **No Stray Files**: Ensure `.venv`, `uv.lock`, `__pycache__`, and `cdk.out` are never committed to git.
