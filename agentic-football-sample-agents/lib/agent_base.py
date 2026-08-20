from __future__ import annotations
import json
from typing import Callable, TYPE_CHECKING
from strands import Agent
from strands.models import BedrockModel

from parsing import parse_commands
from state import summarize_state
from fallback import FallbackConfig, build_last_resort

if TYPE_CHECKING:
    from rules import RoleRules


def create_agent(
    system_prompt: str,
    model_id: str = "us.amazon.nova-micro-v1:0",
    max_tokens: int = 150,
    temperature: float = 0.0,
) -> Agent:
    """Create a Strands Agent with the given system prompt and inference parameters."""
    try:
        model = BedrockModel(
            model_id=model_id, max_tokens=max_tokens, temperature=temperature
        )
    except TypeError:
        try:
            model = BedrockModel(
                model_id=model_id,
                inference_config={"maxTokens": max_tokens, "temperature": temperature},
            )
        except TypeError:
            model = BedrockModel(model_id=model_id)
    return Agent(model=model, system_prompt=system_prompt)


def create_invoke_handler(
    app,
    agent: Agent,
    my_player_id: int,
    position_label: str,
    fallback_fn: Callable[[dict, int, int], list[dict]],
    fallback_cfg: FallbackConfig,
    role_rules: RoleRules | None = None,
):
    """Create and register the @app.entrypoint invoke handler.

    Three layers of error handling, from best to worst:
      1. LLM response → parse into commands (→ sanitize if role_rules)
      2. fallback_fn(game_state, team_id, my_player_id) → rule-based commands (→ sanitize if role_rules)
      3. last-resort command from fallback_cfg → single safe command
    """
    log = app.logger
    last_resort = build_last_resort(fallback_cfg, my_player_id)

    @app.entrypoint
    async def invoke(payload, context):
        effective_rules = role_rules  # always bound for the exception path
        try:
            prompt = payload.get("prompt", "{}")
            prompt_data = json.loads(prompt) if isinstance(prompt, str) else prompt

            game_state = prompt_data.get("gameState", {})
            team_id = prompt_data.get("teamId", 0)

            # Honor myPlayers from payload if present, otherwise use configured player ID
            my_players = prompt_data.get("myPlayers", [my_player_id])
            effective_pid = my_players[0] if my_players else my_player_id

            # Coaching: extract latest teamChat instruction, classify its posture,
            # and modulate the rules so coaching isn't vetoed by the sanitizer.
            from coach import update_coaching

            coach_line, effective_rules = update_coaching(game_state, role_rules)

            state_summary = (
                summarize_state(
                    game_state,
                    team_id,
                    effective_pid,
                    position_label,
                    tactical=(role_rules is not None),
                )
                + coach_line
            )
            log.info(
                f"{position_label} agent invoked for team {team_id}, controlling player {effective_pid}"
            )

            response = agent(state_summary)
            response_text = str(response)

            def on_recovered(raw: str) -> None:
                # The model wrote Python-flavoured JSON (usually `True`/`False`/`None`).
                # We recovered it rather than dropping the command and falling back —
                # logged so you can see how often your model does this.
                log.warn(
                    f"{position_label} recovered malformed JSON from the model: {raw[:200]}"
                )

            commands = parse_commands(
                response_text, team_id, effective_pid, on_recovered
            )
            if effective_rules is not None and commands:
                from rules import sanitize_commands

                commands = sanitize_commands(
                    commands, game_state, team_id, effective_pid, effective_rules
                )

            if commands:
                log.info(
                    f"LLM returned {len(commands)} commands: "
                    f"{[c.get('commandType') for c in commands]}"
                )
                yield json.dumps(commands)
            else:
                log.warn(
                    f"LLM parse/sanitize failed, using fallback. Response: {response_text[:200]}"
                )
                commands = fallback_fn(game_state, team_id, effective_pid)
                if effective_rules is not None and commands:
                    from rules import sanitize_commands

                    commands = sanitize_commands(
                        commands, game_state, team_id, effective_pid, effective_rules
                    )
                if not commands:
                    cmd = dict(last_resort)
                    cmd["teamId"] = team_id
                    cmd["playerId"] = effective_pid
                    commands = [cmd]
                log.info(f"Fallback returned {len(commands)} commands")
                yield json.dumps(commands)

        except Exception as e:
            log.error(f"{position_label} agent error: {e}")
            try:
                raw_prompt = payload.get("prompt", "{}") if isinstance(payload, dict) else "{}"
                prompt_data = (
                    json.loads(raw_prompt)
                    if isinstance(raw_prompt, str)
                    else (raw_prompt if isinstance(raw_prompt, dict) else (payload if isinstance(payload, dict) else {}))
                )
                team_id = prompt_data.get("teamId", 0)
                my_players = prompt_data.get("myPlayers", [my_player_id])
                effective_pid = my_players[0] if my_players else my_player_id
                commands = fallback_fn(
                    prompt_data.get("gameState", {}),
                    team_id,
                    effective_pid,
                )
                if effective_rules is not None and commands:
                    from rules import sanitize_commands

                    commands = sanitize_commands(
                        commands,
                        prompt_data.get("gameState", {}),
                        team_id,
                        effective_pid,
                        effective_rules,
                    )
                if not commands:
                    cmd = dict(last_resort)
                    cmd["teamId"] = team_id
                    cmd["playerId"] = effective_pid
                    commands = [cmd]
                yield json.dumps(commands)
            except Exception:
                cmd = dict(last_resort)
                cmd["teamId"] = 0  # best guess when payload parsing also failed
                cmd["playerId"] = (
                    effective_pid if "effective_pid" in locals() else my_player_id
                )
                yield json.dumps([cmd])

    return invoke
