#!/usr/bin/env python3
"""Apply productive RPC env (Alchemy primary, dRPC secondary) without printing secrets."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def main() -> int:
    from core.env import load_root_dotenv
    from core.rpc_urls import apply_productive_rpc_env, print_rpc_env_contract

    p = argparse.ArgumentParser(description="Bootstrap productive RPC environment")
    p.add_argument("--chain", default="base")
    p.add_argument(
        "cmd",
        nargs=argparse.REMAINDER,
        help="Optional command after -- to run with env applied",
    )
    args = p.parse_args()
    load_root_dotenv()
    try:
        env = apply_productive_rpc_env(args.chain)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print_rpc_env_contract(args.chain, env=env)

    if args.cmd:
        if args.cmd[0] == "--":
            args.cmd = args.cmd[1:]
        if not args.cmd:
            return 0
        return int(subprocess.call(args.cmd, env=env, cwd=str(_REPO)))

    print("Productive RPC env ready. Example: py -3.11 scripts/bootstrap_productive_rpc_env.py -- check ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
