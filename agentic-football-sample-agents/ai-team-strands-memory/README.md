# AI Team (Strands + Memory) — Per-Position Soccer Agents with AgentCore Memory

Ever watched a striker fall for the same fake twice? That's your agents without memory — every tick is a blank slate. AgentCore Memory gives your agents cross-tick recall, turning them from amnesiac bots into football brains that learn and adapt as the match unfolds.

With memory enabled, your agents recognize opponent patterns, recall previous tactical decisions, and adjust their play over time — just like real players do. This team variant uses Short-Term Memory (STM) via `AgentCoreMemorySessionManager`, which persists conversation history within a match session. Each of the 5 players is a separate specialized agent (GK, DEF, MID, FWD1, FWD2) with its own memory context.

Five AI agents built with [Strands Agents SDK](https://github.com/strands-agents/sdk-python) and
[Amazon Bedrock AgentCore Memory](https://docs.aws.amazon.com/bedrock-agentcore/) for
cross-tick history recall.

## What's Different from the Balanced Team?

Each agent uses `AgentCoreMemorySessionManager` (STM) to persist conversation history
across game ticks. This lets agents recall opponent movement patterns, previous
tactical decisions, and game flow from earlier in the match.

Key differences:
- A `team_memory` resource is declared in `agentcore/agentcore.json` and created
  by the same `agentcore deploy` that deploys the agents — no separate
  create-memory step
- The CDK stack grants every agent runtime access to the memory and injects its
  ID as the `MEMORY_TEAM_MEMORY_ID` environment variable
- `AgentCoreMemorySessionManager` wired into each Strands Agent
  (`memory_agent_base_cdk.py`, staged into each agent at deploy time)
- System prompts instruct agents to leverage recalled history using the
  recall → reason → record rhythm each tick

## How Memory Works

Think of it like a player's internal monologue during a match. At tick 50, your goalkeeper saves a shot from the opponent's forward who always aims bottom-left. At tick 120, that same forward lines up another shot — but this time, your GK remembers. It shifts early, anticipates the angle, and makes the save look routine.

Each agent has its own isolated memory context — scoped by a unique `session_id` and `actor_id` based on the player's position. The GK only recalls its own saves and decisions, the DEF only its own marking history, and so on. They share the same Memory resource (`MEMORY_ID`), but don't see each other's events. Think of it as **5 separate notebooks stored in the same filing cabinet**.

Every tick follows a three-beat rhythm:

- **Recall**: the session manager retrieves relevant history from the Memory resource
- **Reason**: the LLM receives both the current game state and recalled context, so it can spot patterns
- **Record**: the agent's decision gets stored back into memory for future ticks

The result? Agents that get smarter as the match progresses. Early ticks are exploratory — by the second half, your team has built a mental model of the opponent.

## Architecture

```
agents/
├── lib/                          # Shared library (same as other teams)
└── ai-team-strands-memory/
    ├── ai-gk/                    # Goalkeeper  (player 0) — Nova Micro + Memory
    ├── ai-def/                   # Defender    (player 1) — Nova Lite  + Memory
    ├── ai-mid/                   # Midfielder  (player 2) — Nova Pro   + Memory
    ├── ai-fwd1/                  # Forward 1   (player 3) — Nova Micro + Memory
    ├── ai-fwd2/                  # Forward 2   (player 4) — Nova Lite  + Memory
    ├── agentcore/                # AgentCore project config (agents + memory)
    │   ├── agentcore.json        # Runtimes + team_memory declaration
    │   └── cdk/                  # CDK app used by `agentcore deploy`
    ├── memory_agent_base_cdk.py  # Memory-aware agent factory (CDK flow)
    ├── deploy_all.py             # Cross-platform deploy script
    ├── destroy_all.py            # Cross-platform teardown script
    └── README.md
```

## Prerequisites

- Python 3.10+
- Node.js 20+ and npm
- AWS CLI configured with valid credentials
- AgentCore CLI and CDK: `npm install -g @aws/agentcore aws-cdk`
- [uv](https://docs.astral.sh/uv/getting-started/installation/) — used by the AgentCore CLI to package Python dependencies
- `rsync` — used to stage the shared library into each agent's build directory (pre-installed on macOS/Linux; on Windows use WSL or Git Bash)
- AWS account with Bedrock model access (Nova Micro, Lite, and/or Pro)
- CDK bootstrap (one-time per account/region): `cdk bootstrap aws://<account-id>/<region>`

Works on macOS, Linux, and Windows (PowerShell) — no WSL required.
No Python packages needed to deploy — `deploy_all.py` uses only the standard library.

## Quick Start

### 1. Deploy (memory + all 5 agents)

```bash
# macOS/Linux
AWS_DEFAULT_REGION=us-east-1 python deploy_all.py
```

```powershell
# Windows PowerShell
$env:AWS_DEFAULT_REGION = "us-east-1"
python deploy_all.py
```

The script checks prerequisites, writes the deploy target, bootstraps CDK if
needed, stages the shared `lib/` and `memory_agent_base_cdk.py` into each agent
directory, and runs `agentcore deploy --yes`. That single deploy creates the
`team_memory` resource, grants the runtimes access to it, and injects
`MEMORY_TEAM_MEMORY_ID` into every agent — nothing to export or configure.

#### Using the legacy shell script (deploy-all.sh)

The shell script creates the Memory resource for you automatically:

```bash
cd ai-team-strands-memory
./deploy-all.sh
```

If you already have a Memory ID from a previous deployment, pass it to reuse:

```bash
export MEMORY_ID=mem-xxxxxxxxxxxxxxxx
export AWS_DEFAULT_REGION=us-east-1
./deploy-all.sh
```

To deploy a single agent:

```bash
./deploy-all.sh ai-gk
```

#### Understanding the deploy output

Prerequisites check:

```
Checking prerequisites...
  agentcore CLI: OK
  rsync: OK
  aws CLI: OK
  AWS Account: 123456789012
  AWS Region:  us-east-1
```

Per-agent deployment:

```
==========================================
  Deploying: ai-gk
==========================================
  Deploying from: /path/_build/ai-gk
  ✅ ai-gk: DEPLOYED
```

Summary:

```
==========================================
  Deployment Summary
==========================================
  Deployed: ai-gk ai-def ai-mid ai-fwd1 ai-fwd2
  Failed:   none
  Memory:   mem-xxxxxxxxxxxxxxxx
  Account:  123456789012
  Region:   us-east-1

All agents deployed successfully.
```

### 2. Local test

```bash
python3 ai-gk/test_local.py
python3 ai-gk/test_local.py --llm  # needs AWS credentials + MEMORY_ID
```

For real memory testing, set your Memory ID first:

```bash
export MEMORY_ID=mem-xxxxxxxxxxxxxxxx
python3 ai-gk/test_local.py --llm
```

### 3. Teardown

```bash
python destroy_all.py            # remove all 5 agents
python destroy_all.py ai-gk      # remove one agent
```

The memory resource is kept; remove its entry from `agentcore/agentcore.json`
and redeploy (or delete the CloudFormation stack) to delete it.

## Verify Your Deployment

Go to the Amazon Bedrock console → AgentCore → Runtime. Each agent should show status **Ready**. You should see 5 new agents with memory in their names.

### Get Your Agent ARNs

After deployment, click on each agent in the Runtime list to copy its **Runtime ARN**. Save all 5 ARNs — you'll need them to register your agents in the Player Portal.

### Confirm Memory Is Working

After playing a match with your memory-enabled agents, you can verify that Memory was actually active:

1. Open the **Amazon Bedrock AgentCore console**
2. In the left navigation pane, choose **Memory**
3. Click on your Memory resource (`AITeamMatchMemory`)
4. Scroll down to the **Observability** section

You should see:

| Metric | What to look for |
|--------|-----------------|
| Create events — API invocations | A non-zero count (e.g., 320). Each agent writes an event every tick, so 5 agents × ~64 ticks ≈ 320 events for a typical match. |
| Create events — Errors | Should be 0. Any errors here mean events failed to write. |
| Retrieve extracted memory | Will show 0 invocations — that's expected. This team uses Short-Term Memory (raw events), not long-term extracted memories. |

If the Create events count is zero after a match, your agents aren't writing to Memory. Check that the `MEMORY_ID` environment variable is set correctly on each agent runtime.

## Legacy scripts

`deploy-all.sh` / `deploy-all-windows.ps1` (with `create_memory.py` and
`memory_agent_base.py`) are the previous deployment path and still work.
Note the two paths manage **separate resources**: the legacy flow creates a
memory named `AITeamMatchMemory` outside CloudFormation, while this flow
creates `team_memory` inside the stack. Running both against one account
leaves two memory resources and two sets of agent runtimes.

## Debugging & Observability

### 1. Tail Live CloudWatch Logs
Each memory-enabled agent automatically streams execution logs and memory hooks to CloudWatch. You can tail live agent logs using the AWS CLI:

```bash
# General syntax:
aws logs tail /aws/bedrock-agentcore/runtime/<agent_runtime_name> --follow

# Examples for memory team positions:
aws logs tail /aws/bedrock-agentcore/runtime/ai_memory_gk_agent --follow
aws logs tail /aws/bedrock-agentcore/runtime/ai_memory_def_agent --follow
aws logs tail /aws/bedrock-agentcore/runtime/ai_memory_mid_agent --follow
aws logs tail /aws/bedrock-agentcore/runtime/ai_memory_fwd1_agent --follow
aws logs tail /aws/bedrock-agentcore/runtime/ai_memory_fwd2_agent --follow
```

Key log patterns to monitor:
- `[INFO] <POS> agent invoked for team X, controlling player Y` — Confirms invocation payload.
- `[INFO] LLM returned N commands: ['...']` — Confirms successful LLM inference with recalled memory.
- `[WARN] <POS> recovered malformed JSON from the model` — Indicates JSON recovery repaired non-standard output.
- `[WARN] LLM parse/sanitize failed, using fallback` — Indicates model output was unparseable or rejected by tactical guardrails.
- `[ERROR] <POS> agent error: ...` — Runtime error triggering layer-3 emergency fallback.

### 2. Metrics & Cost Tracking in Bedrock Console & Player Portal
In the **AWS Management Console (Bedrock / CloudWatch)** and **Agentic Football Player Portal**:
- **Memory Event Writes**: In Bedrock Console → Memory → Observability, check that `Create events` matches match ticks × 5 agents.
- **Invocation Count**: Verify that agents receive exactly 1 invocation per tick.
- **Latency & Timeouts**: Monitor round-trip execution latency including memory session manager retrieval.

### 3. Match Replay Commentary & Decision Debugging
When inspecting match replays in the portal:
- Verify adaptive behavior: agents adjusting marking or shooting targets after observing opponent patterns over multiple ticks.
- Match replay timestamps with CloudWatch logs and STM session memory records.
- Test decision and memory integration offline anytime with `python run_tests.py ai-team-strands-memory` or `python ai-gk/test_local.py --llm`.

