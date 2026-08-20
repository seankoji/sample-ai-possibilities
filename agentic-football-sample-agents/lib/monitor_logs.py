import json
import re
import subprocess
import sys
import time

LOG_GROUPS = {
    "GK (0)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_gk_agent-b25ePZGB95-DEFAULT",
    "DEF (1)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_def_agent-eqjrqCAoUC-DEFAULT",
    "LM (2)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_mid_agent-zfxfrq4dd9-DEFAULT",
    "RM (3)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_fwd1_agent-lIG5eFDZXJ-DEFAULT",
    "ST (4)": "/aws/bedrock-agentcore/runtimes/TeamStrandsDiamond_ai_diamond_fwd2_agent-5qJkmsFtw1-DEFAULT",
}

def scan_agent_logs(seconds_back=30):
    start_time = int((time.time() - seconds_back) * 1000)
    print(f"=== CLOUDWATCH LOG MONITOR (Last {seconds_back}s) ===")
    
    total_events = 0
    anomalies = []
    contradictions = []
    stats = {
        role: {
            "fast_path": 0,
            "fallback": 0,
            "llm": 0,
            "recovered_json": 0,
            "contradictions": 0,
            "errors": 0,
            "commands": {},
        }
        for role in LOG_GROUPS
    }
    
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
            raw_msg = ev.get("message", "")
            msg = raw_msg
            # If structured JSON log, unpack message field
            if raw_msg.strip().startswith("{"):
                try:
                    parsed = json.loads(raw_msg)
                    msg = parsed.get("message", raw_msg)
                except Exception:
                    pass

            # Check for errors / exceptions
            if "ERROR" in msg or "Exception" in msg or "Traceback" in msg:
                stats[role]["errors"] += 1
                anomalies.append(f"[{role} ERROR]: {msg[:160]}")
            
            # Check for recovered malformed JSON
            if "recovered malformed JSON" in msg:
                stats[role]["recovered_json"] += 1
                contradictions.append(f"[{role} RECOVERED_JSON]: {msg[:160]}")

            # Check for LLM parse/sanitize fallback (tactical contradiction)
            if "LLM parse/sanitize failed" in msg or "using fallback" in msg:
                stats[role]["contradictions"] += 1
                stats[role]["fallback"] += 1
                contradictions.append(f"[{role} CONTRADICTION/FALLBACK]: {msg[:160]}")

            # Check fast-path vs LLM vs fallback executions
            cmd_types = re.findall(r"'(MOVE_TO|PASS|SHOOT|PRESS_BALL|MARK|INTERCEPT|GK_DISTRIBUTE|SET_STANCE)'", msg)
            if not cmd_types:
                cmd_types = re.findall(r'"(MOVE_TO|PASS|SHOOT|PRESS_BALL|MARK|INTERCEPT|GK_DISTRIBUTE|SET_STANCE)"', msg)
            
            if "Fast-path returned" in msg:
                stats[role]["fast_path"] += 1
                for c in cmd_types:
                    stats[role]["commands"][c] = stats[role]["commands"].get(c, 0) + 1
            elif "LLM returned" in msg:
                stats[role]["llm"] += 1
                for c in cmd_types:
                    stats[role]["commands"][c] = stats[role]["commands"].get(c, 0) + 1
            elif "Fallback returned" in msg:
                stats[role]["fallback"] += 1

    print(f"Total Log Events: {total_events}")
    for role, st in stats.items():
        cmd_summary = ", ".join(f"{k}×{v}" for k, v in sorted(st["commands"].items())) or "idle"
        print(f"  {role:<7}: FastPath={st['fast_path']:<2} | LLM={st['llm']:<2} | Fallback={st['fallback']:<2} | Cmds: [{cmd_summary}]")
        
    if contradictions:
        print("\n🔍 Contradictions / Sanitizer Corrections:")
        for c in contradictions[:5]:
            print(f"  - {c}")

    if anomalies:
        print("\n⚠️ Anomalies / Errors:")
        for a in anomalies[:5]:
            print(f"  - {a}")
    elif not contradictions and total_events > 0:
        print("  ✓ Zero errors, clean tactical execution.")

if __name__ == "__main__":
    secs = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    scan_agent_logs(secs)
