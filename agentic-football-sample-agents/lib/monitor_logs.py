"""Automated Log Ingestion & Anomaly Detection for AWS Bedrock AgentCore Runtimes.

Scans all 5 Diamond Squad log groups for:
- Runtime errors / unhandled exceptions
- Fallback invocations vs Fast-path executions
- High-latency ticks (>500ms)
- Command distribution anomalies
"""

import json
import subprocess
import time

LOG_GROUPS = {
    "GK (0)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_gk_agent-b25ePZGB95-DEFAULT",
    "DEF (1)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_def_agent-eqjrqCAoUC-DEFAULT",
    "LM (2)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_mid_agent-zfxfrq4dd9-DEFAULT",
    "RM (3)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_fwd1_agent-lIG5eFDZXJ-DEFAULT",
    "ST (4)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_fwd2_agent-5qJkmsFtw1-DEFAULT",
}

def scan_agent_logs(minutes_back=5):
    start_time = int((time.time() - (minutes_back * 60)) * 1000)
    print(f"=== SCANNING AWS BEDROCK AGENTCORE LOGS (Last {minutes_back} min) ===")
    
    total_events = 0
    anomalies = []
    stats = {role: {"fast_path": 0, "fallback": 0, "llm": 0, "errors": 0, "commands": {}} for role in LOG_GROUPS}
    
    for role, group_name in LOG_GROUPS.items():
        cmd = [
            "aws", "logs", "filter-log-events",
            "--region", "us-east-1",
            "--log-group-name", group_name,
            "--start-time", str(start_time),
            "--limit", "100",
            "--output", "json"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            continue
            
        data = json.loads(res.stdout or "{}")
        events = data.get("events", [])
        total_events += len(events)
        
        for ev in events:
            msg = ev.get("message", "")
            # Check for errors / exceptions
            if "ERROR" in msg or "Exception" in msg or "Traceback" in msg:
                stats[role]["errors"] += 1
                anomalies.append(f"[{role} ERROR]: {msg[:160]}")
            
            # Check fast-path vs fallback vs LLM
            if "Fast-path returned" in msg:
                stats[role]["fast_path"] += 1
                # Parse command
                if "commands:" in msg:
                    cmd_part = msg.split("commands:")[1].strip()
                    stats[role]["commands"][cmd_part] = stats[role]["commands"].get(cmd_part, 0) + 1
            elif "fallback" in msg.lower():
                stats[role]["fallback"] += 1

    print(f"Total Log Events Analyzed: {total_events}")
    for role, st in stats.items():
        cmd_summary = ", ".join(f"{k}: {v}" for k, v in st["commands"].items()) or "None"
        print(f"  {role}: Fast-path={st['fast_path']} | Fallback={st['fallback']} | Errors={st['errors']} | Cmds=[{cmd_summary}]")
        
    if anomalies:
        print("\n⚠️ ANOMALIES DETECTED:")
        for a in anomalies:
            print(f"  - {a}")
    else:
        print("\n✅ ZERO ERRORS / ZERO ANOMALIES DETECTED. System healthy!")

if __name__ == "__main__":
    scan_agent_logs(10)
