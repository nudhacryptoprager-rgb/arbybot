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
import time

# Load .env from repo root (so BASE_RPC/ALCHEMY_API_KEY are visible when run standalone)
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
    _ROOT = os.path.dirname(_HERE)
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    from core.env import load_root_dotenv  # type: ignore
    load_root_dotenv()
except Exception:
    pass


CHAIN_RPC_ENV = {
    # Order: *_URL legacy first, then canonical chain-scoped (matches core.rpc_urls),
    # then global primary, then Alchemy api-key fallback (handled below).
    "base": ["BASE_RPC_URL", "BASE_RPC", "ARBY_RPC_HTTP_PRIMARY"],
    "arbitrum_one": ["ARBITRUM_RPC_URL", "ARBITRUM_RPC", "ARBY_RPC_HTTP_PRIMARY"],
    "optimism": ["OPTIMISM_RPC_URL", "OPTIMISM_RPC", "ARBY_RPC_HTTP_PRIMARY"],
}

# Chain → normalized network name for core.rpc_urls resolver
_CHAIN_TO_NETWORK = {
    "base": "base",
    "arbitrum_one": "arbitrum",
    "optimism": "optimism",
}

# Public endpoints we refuse when ARBY_REQUIRE_ARCHIVE=1 is set
_PUBLIC_HOSTS = (
    "mainnet.base.org",
    "arb1.arbitrum.io",
    "rpc.linea.build",
    "rpc.mantle.xyz",
    "publicnode.com",
)


def _is_public_rpc(url: str) -> bool:
    low = (url or "").lower()
    return any(h in low for h in _PUBLIC_HOSTS)


def _resolve_rpc_url(chain: str, override: str | None) -> str | None:
    if override:
        return override
    # 0) Explicit fork-only override (use archive provider with higher rate limit)
    fork_override = os.environ.get("ARBY_FORK_RPC_URL", "").strip()
    if fork_override:
        print(f"[start_anvil_fork] using ARBY_FORK_RPC_URL override")
        return fork_override
    # 1) Prefer Alchemy for anvil fork (typically higher rate limit than dRPC free)
    #    This avoids 429 during fork bootstrap when BASE_RPC is dRPC free tier.
    api = os.environ.get("ALCHEMY_API_KEY", "").strip()
    net = _CHAIN_TO_NETWORK.get(chain)
    if api and net:
        try:
            _here = os.path.dirname(os.path.abspath(__file__))
            _root = os.path.dirname(_here)
            if _root not in sys.path:
                sys.path.insert(0, _root)
            from core.rpc_urls import build_alchemy_http_url  # type: ignore
            al = build_alchemy_http_url(net, api)
            if al:
                print(f"[start_anvil_fork] using Alchemy for fork (archive, higher rate limit)")
                return al
        except Exception as e:
            print(f"[start_anvil_fork] Alchemy url build failed: {e}", file=sys.stderr)
    # 2) Legacy / chain-scoped env fallback (may be dRPC, may rate-limit during fork)
    for key in CHAIN_RPC_ENV.get(chain, ["ARBY_RPC_HTTP_PRIMARY"]):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    # 3) Fallback: full resolver (public fallback)
    try:
        _here = os.path.dirname(os.path.abspath(__file__))
        _root = os.path.dirname(_here)
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from core.rpc_urls import resolve_rpc_http  # type: ignore
        url, prov, diag = resolve_rpc_http(network=net, env=os.environ)
        if url:
            print(f"[start_anvil_fork] resolved via core.rpc_urls: provider={prov} source={diag.get('source')}")
            return url
    except Exception as e:  # pragma: no cover - best effort
        print(f"[start_anvil_fork] core.rpc_urls fallback failed: {e}", file=sys.stderr)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Start Anvil fork for M7 simulation")
    parser.add_argument("--chain", default="base", choices=list(CHAIN_RPC_ENV))
    parser.add_argument("--port", type=int, default=8545)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--rpc-url", default=None, help="Upstream RPC URL for fork")
    parser.add_argument("--block", type=int, default=None, help="Pin fork to block number")
    parser.add_argument(
        "--fork-block-offset",
        type=int,
        default=int(os.environ.get("ARBY_FORK_BLOCK_OFFSET", "3")),
        help="When --block is not set, pin fork to (head - offset) to avoid reorg races (default: 3)",
    )
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
            f"Set one of {CHAIN_RPC_ENV.get(args.chain, [])}, or ALCHEMY_API_KEY + NETWORK, or use --rpc-url.",
            file=sys.stderr,
        )
        return 1

    # Archive requirement: public endpoints cannot fork at historical blocks
    if os.environ.get("ARBY_REQUIRE_ARCHIVE", "0") == "1" and _is_public_rpc(rpc_url):
        print(
            f"ERROR: ARBY_REQUIRE_ARCHIVE=1 and resolved RPC looks public ({rpc_url[:60]}...). "
            "Use Alchemy/dRPC archive endpoint (set BASE_RPC=... or ALCHEMY_API_KEY).",
            file=sys.stderr,
        )
        return 1
    if _is_public_rpc(rpc_url):
        print(
            f"[start_anvil_fork] WARNING: resolved RPC is a public endpoint ({rpc_url[:60]}...). "
            "Fork at historical blocks will likely fail with BlockOutOfRangeError. "
            "Set BASE_RPC=<alchemy/drpc archive> to fix.",
            file=sys.stderr,
        )

    # Resolve fork block: if --block not given, pin to head-offset via a quick eth_blockNumber call.
    fork_block: int | None = args.block
    if fork_block is None and args.fork_block_offset > 0:
        import urllib.request
        import json as _json
        head: int | None = None
        # Retry with exponential backoff to tolerate transient 429 from free RPC tiers.
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    rpc_url,
                    data=_json.dumps({
                        "jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": [],
                    }).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    payload = _json.loads(resp.read().decode("utf-8"))
                head_hex = payload.get("result")
                if isinstance(head_hex, str) and head_hex.startswith("0x"):
                    head = int(head_hex, 16)
                    break
            except Exception as e:
                wait = 2 ** attempt
                print(f"[start_anvil_fork] head probe attempt {attempt+1}/4 failed ({e}); retry in {wait}s",
                      file=sys.stderr)
                time.sleep(wait)
        if head is not None:
            fork_block = max(1, head - args.fork_block_offset)
            print(f"[start_anvil_fork] head={head} offset={args.fork_block_offset} -> fork_block={fork_block}")
        else:
            print("[start_anvil_fork] head probe exhausted retries; forking at latest (may race reorgs)",
                  file=sys.stderr)

    cmd = [
        anvil_path,
        "--fork-url", rpc_url,
        "--host", args.host,
        "--port", str(args.port),
    ]
    if fork_block is not None:
        cmd += ["--fork-block-number", str(fork_block)]
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
