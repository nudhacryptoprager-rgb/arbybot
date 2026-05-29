"""
Discover Curve pool coin indices via eth_call coins(uint256).

For each curve_stable pool in the bridge inventory, calls pool.coins(0), pool.coins(1),
etc. until the call reverts, building a {token_address: index} map.

Outputs a YAML snippet ready to paste into config/adapter_metadata.yaml.

Usage:
    py -3.11 scripts/discover_curve_indices.py

Requires BASE_RPC env var or uses publicnode fallback.
"""
from __future__ import annotations

import json
import os
import sys

import httpx

RPC_URL = os.environ.get("BASE_RPC", "https://base.publicnode.com")

# Selector for coins(uint256) — used by Curve StableSwap-NG and CryptoSwap
COINS_SELECTOR_UINT = "c6610657"
# Selector for coins(int128) — used by older Curve pools
COINS_SELECTOR_INT128 = "23746eb8"

# Token address -> symbol lookup (built from known bridge inventory tokens)
KNOWN_TOKENS: dict[str, str] = {
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": "USDC",
    "0x4200000000000000000000000000000000000006": "WETH",
    "0x417ac0e078398c154edfadd9ef675d30be60af93": "crvUSD",
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": "USDbC",
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": "DAI",
    "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22": "cbETH",
    "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf": "cbBTC",
    "0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b": "VIRTUAL",
    "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4": "TOSHI",
    "0x940181a94a35a4569e4529a3cdfb74e38fd98631": "AERO",
    "0x6921b130d297cc43754afba22e5eac0fbf8db75b": "doginme",
    "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42": "EURC",
    "0x9e1028f5f1d5ede59748ffcee5532509976840e0": "COMP",
    "0xd07379a755a8f11b57610154861d694b2a0f615a": "DEGEN",
}


def eth_call(to: str, data: str) -> str | None:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    resp = httpx.post(RPC_URL, json=payload, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        return None
    result = body.get("result", "0x")
    if not result or result == "0x" or len(result) < 66:
        return None
    return result


def get_coin(pool: str, index: int, use_uint: bool = True) -> str | None:
    """Return coin address at index, or None on revert."""
    selector = COINS_SELECTOR_UINT if use_uint else COINS_SELECTOR_INT128
    idx_bytes = index.to_bytes(32, "big").hex()
    result = eth_call(pool, f"0x{selector}{idx_bytes}")
    if result is None:
        return None
    # Result is 32-byte ABI-encoded address — last 20 bytes
    raw = result[2:] if result.startswith("0x") else result
    addr = "0x" + raw[-40:].lower()
    if addr == "0x" + "0" * 40:
        return None
    return addr


def discover_pool(pool_address: str) -> dict[str, int] | None:
    """Return {token_address: index} for up to 8 coins, or None on total failure."""
    coins: dict[str, int] = {}
    for i in range(8):
        addr = get_coin(pool_address, i, use_uint=True)
        if addr is None:
            # Try int128 fallback
            addr = get_coin(pool_address, i, use_uint=False)
        if addr is None:
            break
        coins[addr.lower()] = i
    return coins if coins else None


def main() -> None:
    inv_path = "data/tmp/m9_depth_enriched_bridge.json"
    if not os.path.exists(inv_path):
        print(f"ERROR: {inv_path} not found", file=sys.stderr)
        sys.exit(1)

    d = json.load(open(inv_path))
    active = d.get("active_routes", [])
    curve_pools = {
        r["pool_address"].lower()
        for r in active
        if "curve" in str(r.get("dex_id", "")) and r.get("pool_address")
    }

    print(f"Discovering coin indices for {len(curve_pools)} curve_stable pools")
    print(f"RPC: {RPC_URL}\n")

    yaml_lines: list[str] = []
    failed: list[str] = []

    for pool_addr in sorted(curve_pools):
        print(f"  {pool_addr} ...", end=" ", flush=True)
        coins = discover_pool(pool_addr)
        if not coins:
            print("FAILED (no coins returned)")
            failed.append(pool_addr)
            continue

        # Map addresses to symbols
        named: dict[str, int] = {}
        unknown: dict[str, int] = {}
        for addr, idx in coins.items():
            sym = KNOWN_TOKENS.get(addr)
            if sym:
                named[sym] = idx
            else:
                unknown[addr] = idx

        print(f"OK  {list(coins.items())}")

        # Build YAML snippet
        yaml_lines.append(f'      "{pool_addr}":')
        yaml_lines.append(f'        pool_kind: "stable"')
        yaml_lines.append(f'        coin_indices:')
        for addr, idx in sorted(coins.items(), key=lambda x: x[1]):
            sym = KNOWN_TOKENS.get(addr, f"UNKNOWN_{addr[:8]}")
            yaml_lines.append(f'          {sym}: {idx}')
        yaml_lines.append("")

    print("\n\n# -----------------------------------------------------------------------")
    print("# Paste the following into config/adapter_metadata.yaml")
    print("# under: curve: > base: > pools:")
    print("# -----------------------------------------------------------------------")
    for line in yaml_lines:
        print(line)

    if failed:
        print(f"\n# FAILED pools (will remain in quarantine): {failed}", file=sys.stderr)


if __name__ == "__main__":
    main()
