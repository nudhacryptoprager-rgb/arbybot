#!/usr/bin/env python3
"""
Start Anvil fork for M7 simulation backend.

E1.12.4A: Standalone bootstrap — NOT embedded in hot lane loop.

Usage:
    python scripts/start_anvil_fork.py                        # Base mainnet
    python scripts/start_anvil_fork.py --chain arbitrum_one   # Arbitrum
    python scripts/start_anvil_fork.py --port 8546            # Custom port
    python scripts/start_anvil_fork.py --block 12345678       # Pinned block

Requires:
    - Foundry `anvil` in PATH  (curl -L https://foundry.paradigm.xyz | bash && foundryup)
    - RPC URL:  uses BASE_RPC_URL / ARBY_RPC_HTTP_PRIMARY env vars
      or --rpc-url flag

The script starts Anvil as a subprocess and blocks until interrupted.
After start, set ARBY_SIM_BACKEND=anvil and (optionally) ARBY_ANVIL_RPC_URL.
"""

import argparse
import os
import shutil
import subprocess
import sys


CHAIN_RPC_ENV = {
    "base": ["BASE_RPC_URL", "ARBY_RPC_HTTP_PRIMARY"],
    "arbitrum_one": ["ARBITRUM_RPC_URL", "ARBY_RPC_HTTP_PRIMARY"],
    "optimism": ["OPTIMISM_RPC_URL", "ARBY_RPC_HTTP_PRIMARY"],
}


def _resolve_rpc_url(chain: str, override: str | None) -> str | None:
    if override:
        return override
    for key in CHAIN_RPC_ENV.get(chain, ["ARBY_RPC_HTTP_PRIMARY"]):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Anvil fork for M7 simulation")
    parser.add_argument("--chain", default="base", choices=list(CHAIN_RPC_ENV))
    parser.add_argument("--port", type=int, default=8545)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--rpc-url", default=None, help="Upstream RPC URL for fork")
    parser.add_argument("--block", type=int, default=None, help="Pin fork to block number")
    parser.add_argument("--auto-impersonate", action=argparse.BooleanOptionalAction, default=True,
                        help="Enable --auto-impersonate (default: on, use --no-auto-impersonate to disable)")
    parser.add_argument("--steps-tracing", action="store_true", default=False)
    args = parser.parse_args()

    # Check anvil is installed
    anvil_path = shutil.which("anvil")
    if not anvil_path:
        print("ERROR: `anvil` not found in PATH. Install Foundry: https://getfoundry.sh", file=sys.stderr)
        return 1

    rpc_url = _resolve_rpc_url(args.chain, args.rpc_url)
    if not rpc_url:
        print(
            f"ERROR: No RPC URL for chain={args.chain}. "
            f"Set one of {CHAIN_RPC_ENV.get(args.chain, [])} or use --rpc-url.",
            file=sys.stderr,
        )
        return 1

    cmd = [
        anvil_path,
        "--fork-url", rpc_url,
        "--host", args.host,
        "--port", str(args.port),
    ]
    if args.block is not None:
        cmd += ["--fork-block-number", str(args.block)]
    if args.auto_impersonate:
        cmd += ["--auto-impersonate"]
    if args.steps_tracing:
        cmd += ["--steps-tracing"]

    print(f"Starting Anvil fork: chain={args.chain}, port={args.port}")
    print(f"  RPC: {rpc_url[:60]}...")
    print(f"  cmd: {' '.join(cmd)}")
    print(f"\nSet env: ARBY_SIM_BACKEND=anvil  ARBY_ANVIL_RPC_URL=http://{args.host}:{args.port}")
    print("Press Ctrl+C to stop.\n")

    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode
    except KeyboardInterrupt:
        print("\nAnvil stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
