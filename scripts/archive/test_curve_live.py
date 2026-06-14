"""Test all curve_stable pools from bridge inventory with live RPC calls.

For each pool, tries both int128 (5e0d443f) and uint256 (4fb08c5e) selectors
using the coin indices from adapter_metadata.yaml. Reports which work.
"""
import json
import os
import httpx
from m9.graph_arb.adapter_metadata import load_adapter_metadata

TOKEN_DECIMALS = {
    "USDC": 6,
    "USDbC": 6,
    "DAI": 18,
    "crvUSD": 18,
    "WETH": 18,
    "wstETH": 18,
    "cbETH": 18,
    "AERO": 18,
    "UNKNOWN_0xeb4663": 18,
}

rpc = os.environ.get("BASE_RPC", "https://base.publicnode.com")
meta = load_adapter_metadata("config/adapter_metadata.yaml")

with open("data/tmp/m9_depth_enriched_bridge.json") as f:
    inv = json.load(f)

curve_routes = [r for r in inv.get("active_routes", []) if r.get("adapter_type") == "curve_stable"]

print(f"Testing {len(curve_routes)} curve_stable routes vs live RPC: {rpc}")
print()

working = []
failing = []

for r in curve_routes:
    pair_id = r.get("pair_id", "")
    pool = r.get("pool_address", "").lower()
    parts = pair_id.split("_")
    s0, s1 = (parts[0], parts[1]) if len(parts) == 2 else ("?", "?")

    idx_in, idx_out = meta.curve_indices(pool, s0, s1, "base")
    if idx_in is None or idx_out is None:
        print(f"  SKIP {pair_id:18s} {pool[:16]}: missing indices")
        continue

    dec_in = TOKEN_DECIMALS.get(s0, 18)
    amount = 10 ** dec_in  # 1 unit of token_in

    ii = idx_in.to_bytes(32, "big").hex()
    io = idx_out.to_bytes(32, "big").hex()
    am = amount.to_bytes(32, "big").hex()

    results = {}
    for sel, sname in [("5e0d443f", "int128"), ("4fb08c5e", "uint256")]:
        calldata = "0x" + sel + ii + io + am
        payload = {
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": pool, "data": calldata}, "latest"],
        }
        resp = httpx.post(rpc, json=payload, timeout=10).json()
        result = resp.get("result", "0x")
        err = resp.get("error")
        if err:
            results[sname] = f"REVERT({err.get('code','')})"
        elif len(result) >= 66:
            out = int(result[2:66], 16)
            results[sname] = f"OK={out}"
        else:
            results[sname] = f"short={result!r}"

    ok_sel = [s for s, v in results.items() if v.startswith("OK")]
    status = "✓" if ok_sel else "✗"
    working_sel = ok_sel[0] if ok_sel else None
    print(
        f"  {status}  {pair_id:18s} {pool[:16]}  "
        f"i={idx_in},{idx_out}  "
        f"int128={results.get('int128','?')}  uint256={results.get('uint256','?')}"
    )
    if ok_sel:
        working.append((pool, pair_id, working_sel))
    else:
        failing.append((pool, pair_id))

print()
print(f"Working: {len(working)}, Failing: {len(failing)}")
if failing:
    print("Failing pools (should be quarantined):")
    for pool, pair in failing:
        print(f"  {pool}  {pair}")
