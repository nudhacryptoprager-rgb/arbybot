#!/usr/bin/env python3
import json, subprocess, sys, time
from pathlib import Path
PID = int(sys.argv[1]) if len(sys.argv) > 1 else 20604
CK = Path("data/tmp/m8_hint_refresh_checkpoint_baseline.json")
HINTS = Path("data/runs/_rolling/m8_external_pool_hints_latest.json")
DEADLINE_S = int(sys.argv[2]) if len(sys.argv) > 2 else 5100

def alive(pid):
    return str(pid) in subprocess.run(["tasklist","/FI",f"PID eq {pid}"],capture_output=True,text=True).stdout

def artifact_done():
    if not HINTS.is_file():
        return False
    h = json.loads(HINTS.read_text(encoding="utf-8"))
    m = h.get("metrics") or {}
    ts = str(h.get("generated_at_utc") or "")
    return m.get("fetch_async") is True and ts > "2026-06-15T21:00:00Z"

deadline = time.time() + DEADLINE_S
last = -1
while time.time() < deadline:
    if CK.is_file():
        ck = json.loads(CK.read_text(encoding="utf-8"))
        idx = int(ck.get("next_token_index") or 0)
        if idx != last:
            print("progress", idx, "/753 hints=", ck.get("hints_collected"), "alive=", alive(PID), flush=True)
            last = idx
    if artifact_done():
        print("ARTIFACT_DONE")
        sys.exit(0)
    if not alive(PID) and not CK.is_file():
        print("REFRESH_FINISHED")
        sys.exit(0)
    if not alive(PID):
        print("PROCESS_EXIT")
        sys.exit(2)
    time.sleep(120)
print("POLL_TIMEOUT")
sys.exit(1)
