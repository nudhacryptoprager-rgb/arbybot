#!/usr/bin/env python3
"""Launch 60m M8 sniper soak with productive RPC bootstrap (detached-friendly)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    from core.env import load_root_dotenv
    from core.rpc_urls import apply_productive_rpc_env, print_rpc_env_contract

    load_root_dotenv()
    env = apply_productive_rpc_env("base")
    env["ARBY_SNIPER_ENABLE"] = "1"
    # Discovery-only soak: phase2 enricher on 43200-block lookback stalls on dRPC 429.
    env["ARBY_SNIPER_PAPER"] = "0"
    print_rpc_env_contract("base", env=env)
    print("ARBY_SNIPER_PAPER=0 (discovery-only; no per-event enricher)")

    cmd = [
        sys.executable,
        str(_REPO / "scripts" / "sniper_smoke_run.py"),
        "--chain",
        "base",
        "--duration-minutes",
        "60",
        "--skip-self-test",
        "--skip-preflight",
        "--blocks-back",
        "43200",
    ]
    return int(subprocess.call(cmd, env=env, cwd=str(_REPO)))


if __name__ == "__main__":
    sys.exit(main())
