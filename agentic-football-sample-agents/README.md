# Agentic Football — Per-Position AI Sample Agents

Autonomous 5v5 soccer agents built with the [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and deployed to [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/).

In this architecture, every player on the pitch is driven by its own independent AI agent runtime, receiving game state updates each tick and returning structured JSON commands within strict match latency budgets.

---

## 1. 5-Agent Architecture

Each team is composed of 5 distinct position agents operating as decoupled micro-runtimes:

```
                          [ 0: Goalkeeper (GK) ]
                                    |
                          [ 1: Defender (DEF/CB) ]
                                 /      \
             [ 2: Midfielder (MID/LM) ]  [ 3: Forward 1 / Right Mid (FWD1/RM) ]
                                 \      /
                          [ 4: Forward 2 / Striker (FWD2/ST) ]
```

| Player ID | Standard Position | Diamond Formation | Typical Model | Primary Responsibilities |
|---|---|---|---|---|
| **0** | Goalkeeper (`GK`) | Goalkeeper (`GK`) | Amazon Nova Micro | Goal-line protection, shot blocking, wide distribution via `GK_DISTRIBUTE` |
| **1** | Defender (`DEF`) | Center Back (`CB`) | Amazon Nova Lite / Micro | Backline anchor, marking central runners, clearances to flanks, defensive shape |
| **2** | Midfielder (`MID`) | Left Mid (`LM`) | Amazon Nova Pro / Micro | Transition link, passing triangles, half-space coverage, long-range shooting |
| **3** | Forward 1 (`FWD1`) | Right Mid (`RM`) | Amazon Nova Micro | Wide attacking runs, pressing high, through-ball reception, crossing |
| **4** | Forward 2 (`FWD2`) | Striker (`ST`) | Amazon Nova Lite / Micro | Central target pivot, hold-up play, disciplined finishing, channel pressing |

---

## 2. Shared Library API Contract (`lib/`)

The `lib/` directory provides a single source of truth shared across all teams. Agent runtimes and local test suites import directly from `lib/`:

```
lib/
├── state.py          # State representation & geometric metric extractors
├── rules.py          # Deterministic RoleRules & command sanitization guardrails
├── agent_base.py     # Strands Agent factory & 3-layer resilient invoke handlers
├── fallback.py       # Position-specific heuristic rule-based command engines
├── json_tolerant.py  # Python-to-JSON literal normalization & recovery
├── parsing.py        # Strict + tolerant command parsing & ID clamping
├── test_helpers.py   # Comprehensive AgentCore/Memory/Gateway mocks & test states
├── test_parsing.py   # Unit test suite for parser resilience
└── test_rules.py     # Unit test suite for tactical guardrails
```

### Shared Modules Contract

1. **`lib/state.py`**:
   - `summarize_state(game_state, team_id, my_player_id, position_label, tactical=False) -> str`: Converts raw game state dictionaries into token-lean, human-readable prompts (<250 tokens). When `tactical=True`, injects geometric awareness: `shotBlockers`, `attackingThird`, `ballSide`, `amNearestToBall`, and `oppGoalDist`.
   - Spatial utilities: `get_goal_positions()`, `dist()`, `is_attacking_third()`, `shot_blockers()`, `is_nearest_to_ball()`, `ball_side()`.

2. **`lib/rules.py`**:
   - `RoleRules(label, own_half_only, box_only, may_press, shoot_gate, home_y)`: Encapsulates tactical boundary rules.
   - `sanitize_commands(commands, game_state, team_id, my_player_id, rules) -> list[dict]`:
     * **Schema Validation**: Validates command types and parameter ranges.
     * **Anti-Swarm**: Restricts `PRESS_BALL` to the nearest outfield player; converts secondary presses into zonal marking (`MARK`) or home-positioning (`MOVE_TO`).
     * **Shot Discipline**: Converts unviable shots (outside attacking third or blocked by $\ge 2$ defenders) into progressive passes.
     * **Role Boundaries**: Clamps GK movements to the penalty box and CB movements to own half.
     * **Stamina Awareness**: Disables sprint and press when stamina $< 30\%$.

3. **`lib/agent_base.py`**:
   - `create_agent(system_prompt, model_id, max_tokens, temperature) -> Agent`: Initializes Strands Agent with Bedrock model bindings.
   - `create_invoke_handler(app, agent, my_player_id, position_label, fallback_fn, fallback_cfg, role_rules)`: Wires the `@app.entrypoint` with a **3-layer resilience hierarchy**:
     1. **Layer 1 (LLM Inference)**: Prompt LLM $\rightarrow$ Parse JSON $\rightarrow$ Sanitize via `RoleRules`.
     2. **Layer 2 (Rule-Based Fallback)**: Execute `fallback_fn` $\rightarrow$ Sanitize via `RoleRules`.
     3. **Layer 3 (Last Resort)**: Return zero-risk static command (e.g. `MOVE_TO` home coordinate or `SET_STANCE`).

4. **`lib/json_tolerant.py` & `lib/parsing.py`**:
   - Rescues Python-syntax literals (`True`, `False`, `None`), trailing commas, and markdown fences emitted by smaller LLMs without touching string literals.

---

## 3. Team Variations

| Team Directory | Strategy / Formation | Key Capabilities | Model Strategy |
|---|---|---|---|
| [`ai-team-strands-balanced`](./ai-team-strands-balanced/) | 1-1-1-2 Standard | Baseline all-around team | Micro / Lite / Pro tiering |
| [`ai-team-strands-diamond`](./ai-team-strands-diamond/) | 1-2-1 Diamond Formation | Deterministic `RoleRules` spatial guardrails, width support | 100% Amazon Nova Micro (<300ms) |
| [`ai-team-strands-memory`](./ai-team-strands-memory/) | 1-1-1-2 with STM Recall | AgentCore Short-Term Memory session tracking across ticks | Micro / Lite / Pro + STM |
| [`ai-team-strands-gateway`](./ai-team-strands-gateway/) | 1-1-1-2 with MCP Tools | AgentCore Gateway integration with serverless Lambda tools | Micro / Lite / Pro + MCP |
| [`ai-team-strands-extremely-aggressive`](./ai-team-strands-extremely-aggressive/) | High Press & Overload | Max intensity pressing, forward overload runs | Nova Micro / Lite |
| [`ai-team-strands-extremely-defensive`](./ai-team-strands-extremely-defensive/) | Low Block Counter | Goal-line packing, long counter-attacking through-balls | Nova Micro / Lite |

---

## 4. Setup & Dependency Management

We use [`uv`](https://docs.astral.sh/uv/) for high-speed, reproducible Python environment management.

### Prerequisites
- Python 3.10+
- Node.js 20+ & npm
- AWS CLI configured (`aws configure` or `AWS_PROFILE`)
- AgentCore CLI and AWS CDK:
  ```bash
  npm install -g @aws/agentcore aws-cdk
  ```
- `uv` package manager:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```

### Virtual Environment Setup
Create and sync the repo-root virtual environment:
```bash
# Create virtual environment with uv
uv venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv pip install -r ai-team-strands-balanced/ai-gk/requirements.txt
```

---

## 5. Unified Test Runner (`run_tests.py`)

Run all unit tests, position agent local tests, and integration simulations using `run_tests.py`:

```bash
# Run entire test suite (lib unit tests + all 6 teams' local tests)
python run_tests.py

# Run tests for a specific team
python run_tests.py ai-team-strands-diamond
python run_tests.py memory

# Run shared library tests only
python run_tests.py lib

# Run full integration simulation across synthetic game states
python run_tests.py --integration

# Verbose output
python run_tests.py -v
```

---

## 6. Team Scaffolding Tool (`scaffold_team.py`)

Generate a completely configured new team in seconds:

```bash
# Scaffold a new team based on diamond template
python scaffold_team.py ai-team-strands-possession --base diamond

# Scaffold from balanced template
python scaffold_team.py counter-attack --base balanced
```

The scaffolding tool automatically:
1. Clones the base team directory without transient build artifacts (`.venv`, `cdk.out`, etc.).
2. Renames CDK project names and runtime targets in `agentcore/agentcore.json`.
3. Renames agent keys in `.bedrock_agentcore.yaml.template` and `pyproject.toml`.
4. Configures `deploy_all.py`, `deploy-all.sh`, and local test runners.
5. Runs verification tests immediately to ensure ready-to-deploy status.

---

## 7. Deployment to Bedrock AgentCore

Deploy all 5 position agents to AWS with a single command:

```bash
# Deploy balanced team
cd ai-team-strands-balanced
AWS_DEFAULT_REGION=us-east-1 python deploy_all.py

# Or deploy diamond team
cd ../ai-team-strands-diamond
AWS_DEFAULT_REGION=us-east-1 python deploy_all.py
```

### Pre-Deploy Validation Gate
Every `deploy_all.py` and `deploy-all.sh` executes a **pre-deploy validation step** running `test_local.py` for all 5 position agents. If any agent fails local test assertions, deployment halts immediately before touching AWS resources.

---

## 8. Debugging & Observability

### Tail Live CloudWatch Logs
```bash
aws logs tail /aws/bedrock-agentcore/runtime/<agent_name> --follow

# Example:
aws logs tail /aws/bedrock-agentcore/runtime/ai_diamond_mid_agent --follow
```

### Key Metrics to Monitor
- **Invocation Count**: 1 invocation per agent per tick (5 per team tick).
- **Latency**: Keep under 300ms for fast match simulator progression.
- **Recovered Output**: Check logs for `[WARN] recovered malformed JSON` to verify if prompt adjustments are needed.
