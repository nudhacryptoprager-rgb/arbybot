#!/usr/bin/env python3
"""
Diagnostic: verify RPC endpoints before a soak run.

Checks (for a given chain):
  1. HTTP resolves via core.rpc_urls
  2. HTTP responds to eth_chainId  (chain_id match)
  3. HTTP is ARCHIVE-capable       (eth_getBalance at head-1000 must not 'missing trie node' / BlockOutOfRange)
  4. WS  resolves and accepts newHeads subscription (returns at least 1 head in <timeout>s)
  5. (optional) Flashblocks preconf WS reachable (Base only)

Exit codes:
  0 = PASS (all green)
  1 = FAIL archive
  2 = FAIL ws
  3 = FAIL chain_id mismatch
  4 = FAIL resolve (no url)

Usage:
  py -3.11 scripts/check_rpc_endpoints.py --chain base
  py -3.11 scripts/check_rpc_endpoints.py --chain arbitrum_one --ws-timeout 10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

# Make repo root importable
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Load .env from repo root so BASE_RPC / ALCHEMY_API_KEY etc. are visible
try:
    from core.env import load_root_dotenv  # type: ignore
    load_root_dotenv()
except Exception:
    pass

from core.rpc_urls import resolve_rpc_http, resolve_rpc_ws, classify_provider  # noqa: E402


_CHAIN_TO_NETWORK = {
    "base": "base",
    "arbitrum_one": "arbitrum",
    "arbitrum": "arbitrum",
    "linea": "linea",
    "mantle": "mantle",
    "optimism": "optimism",
    "scroll": "scroll",
    "zksync": "zksync",
}

_CHAIN_TO_ID = {
    "base": 8453,
    "arbitrum_one": 42161,
    "arbitrum": 42161,
    "linea": 59144,
    "mantle": 5000,
    "optimism": 10,
    "scroll": 534352,
    "zksync": 324,
}

_FLASHBLOCKS_WS = {
    "base": "wss://mainnet-preconf.base.org",
}


def _rpc(url: str, method: str, params: list, timeout: float = 8.0) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_http_archive(url: str, archive_depth: int) -> tuple[bool, str]:
    """Test archive by reading balance of 0x000..dead at head-archive_depth."""
    try:
        head_resp = _rpc(url, "eth_blockNumber", [])
        head_hex = head_resp.get("result")
        if not isinstance(head_hex, str):
            return False, f"eth_blockNumber malformed: {head_resp}"
        head = int(head_hex, 16)
        target = max(1, head - archive_depth)
        target_hex = hex(target)
        # Dead address is safe; should always return '0x0' on archive, error on non-archive.
        r = _rpc(url, "eth_getBalance", ["0x000000000000000000000000000000000000dEaD", target_hex])
        if "error" in r:
            return False, f"archive probe failed at block {target}: {r['error']}"
        return True, f"archive OK: head={head}, probed block={target}"
    except Exception as e:
        return False, f"archive probe exception: {e}"


def check_chain_id(url: str, expected: int) -> tuple[bool, str]:
    try:
        r = _rpc(url, "eth_chainId", [])
        cid_hex = r.get("result")
        if not isinstance(cid_hex, str):
            return False, f"eth_chainId malformed: {r}"
        cid = int(cid_hex, 16)
        if cid != expected:
            return False, f"chain_id mismatch: got {cid}, expected {expected}"
        return True, f"chain_id OK: {cid}"
    except Exception as e:
        return False, f"chain_id probe exception: {e}"


def check_ws_newheads(ws_url: str, timeout: float) -> tuple[bool, str]:
    """Subscribe to newHeads and wait for first head within timeout."""
    try:
        from websocket import create_connection  # type: ignore
    except Exception:
        return False, "websocket-client not installed (pip install websocket-client)"
    t0 = time.time()
    try:
        ws = create_connection(ws_url, timeout=timeout)
        ws.settimeout(timeout)
        ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_subscribe", "params": ["newHeads"]}))
        # First response = subscription ack
        ack = json.loads(ws.recv())
        if "error" in ack:
            ws.close()
            return False, f"subscribe rejected: {ack['error']}"
        # Wait for first head notification
        first = json.loads(ws.recv())
        ws.close()
        elapsed = time.time() - t0
        num = first.get("params", {}).get("result", {}).get("number")
        return True, f"newHeads OK: first head {num} in {elapsed:.2f}s"
    except Exception as e:
        return False, f"ws exception after {time.time()-t0:.2f}s: {e}"


def check_flashblocks(chain: str, timeout: float) -> tuple[bool, str]:
    ws_url = _FLASHBLOCKS_WS.get(chain)
    if not ws_url:
        return True, "flashblocks: N/A for this chain"
    return check_ws_newheads(ws_url, timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="RPC endpoint diagnostic")
    parser.add_argument("--chain", required=True, choices=list(_CHAIN_TO_ID.keys()))
    parser.add_argument("--archive-depth", type=int, default=2000,
                        help="Blocks below head to probe for archive capability (default: 2000)")
    parser.add_argument("--ws-timeout", type=float, default=15.0,
                        help="Seconds to wait for first newHeads (default: 15)")
    parser.add_argument("--require-flashblocks", action="store_true",
                        help="Fail if flashblocks preconf WS is unreachable (Base only)")
    args = parser.parse_args()

    network = _CHAIN_TO_NETWORK[args.chain]
    expected_cid = _CHAIN_TO_ID[args.chain]
    env = dict(os.environ)

    print("=" * 60)
    print(f"RPC Endpoint Check: chain={args.chain} network={network} chain_id={expected_cid}")
    print("=" * 60)

    from core.rpc_urls import print_rpc_env_contract

    print_rpc_env_contract(args.chain, env=env)
    print()

    # Resolve
    from core.rpc_urls import is_public_rpc_url, iter_dedicated_http_providers

    http_url, http_prov, http_diag = resolve_rpc_http(chain_id=expected_cid, network=network, env=env)
    ws_url, ws_prov, ws_diag = resolve_rpc_ws(chain_id=expected_cid, network=network, env=env)

    dedicated = iter_dedicated_http_providers(args.chain, env=env)
    if is_public_rpc_url(http_url) and dedicated:
        pick = dedicated[0]
        for label, url in dedicated:
            if classify_provider(url) == "alchemy":
                pick = (label, url)
                break
        http_url, http_prov = pick[1], classify_provider(pick[1])
        http_diag = {**http_diag, "source": "dedicated_pool_override", "label": pick[0]}
        if len(dedicated) > 1:
            print(f"Note: default HTTP was public; using dedicated pool ({len(dedicated)} providers)")
    elif is_public_rpc_url(http_url):
        print("[FAIL] HTTP resolve: only public RPC configured; set BASE_RPC_PRIMARY or ALCHEMY_API_KEY")
        return 4

    if not http_url:
        print(f"[FAIL] HTTP resolve: {http_diag}")
        return 4
    if not ws_url:
        print(f"[FAIL] WS resolve:   {ws_diag}")
        return 4

    from m9.graph_arb.provider_router import _mask

    print(f"HTTP: provider={http_prov} source={http_diag.get('source')} url={_mask(http_url)}")
    print(f"WS:   provider={ws_prov} source={ws_diag.get('source')} url={_mask(ws_url)}")
    if len(dedicated) > 1:
        print(f"Secondary HTTP candidates: {len(dedicated) - 1} (A/B via rpc_provider_ab_test.py)")
    print()

    overall = True
    exit_code = 0

    # 1) chain_id
    ok, msg = check_chain_id(http_url, expected_cid)
    print(f"[{'OK' if ok else 'FAIL'}] chain_id: {msg}")
    if not ok:
        overall = False
        exit_code = 3

    # 2) archive
    ok, msg = check_http_archive(http_url, args.archive_depth)
    print(f"[{'OK' if ok else 'FAIL'}] archive:  {msg}")
    if not ok:
        overall = False
        if exit_code == 0:
            exit_code = 1
        print("      -> anvil fork and rpc_fork sim will fail at historical blocks.")
        print("      -> Set BASE_RPC=<alchemy/drpc archive> or ALCHEMY_API_KEY.")

    # 3) WS newHeads
    ok, msg = check_ws_newheads(ws_url, args.ws_timeout)
    print(f"[{'OK' if ok else 'FAIL'}] newHeads: {msg}")
    if not ok:
        overall = False
        if exit_code == 0:
            exit_code = 2

    # 4) Flashblocks (optional)
    ok_fb, msg_fb = check_flashblocks(args.chain, args.ws_timeout)
    label = "OK" if ok_fb else "WARN"
    if args.require_flashblocks and not ok_fb:
        label = "FAIL"
        overall = False
        if exit_code == 0:
            exit_code = 2
    print(f"[{label}] flashblocks: {msg_fb}")

    print()
    print("=" * 60)
    if overall:
        print("RESULT: PASS — endpoints ready for soak")
    else:
        print(f"RESULT: FAIL (exit={exit_code}) — fix before running soak")
    print("=" * 60)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
