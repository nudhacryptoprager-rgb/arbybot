"""Quick script to probe Maverick V2 factory on Base for pool discovery."""
import httpx
from web3 import Web3

RPC = "https://base.publicnode.com"
MAV_FACTORY = "0x0a7e848aca42d879ef06507fca0e7b33a0a63c1e"
ZERO = "0x" + "0" * 40

TOKENS = {
    "WETH":   "0x4200000000000000000000000000000000000006",
    "USDC":   "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "cbETH":  "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22",
    "wstETH": "0xc1cba3fcea344f92d9239c08c0568f6f2f0ee452",
    "cbBTC":  "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf",
    "EURC":   "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42",
    "AERO":   "0x940181a94a35a4569e4529a3cdfb74e38fd98631",
    "DAI":    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",
}


def eth_call(to: str, data: str) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_call", "params": [{"to": to, "data": data}, "latest"]}
    r = httpx.post(RPC, json=body, timeout=8.0)
    return r.json()


def sel(sig: str) -> str:
    return "0x" + Web3.keccak(text=sig).hex()[:8]


# --- probe no-arg functions ---
print("=== Probing no-arg functions ===")
no_arg_sigs = [
    "poolCount()",
    "numberOfPools()",
    "numPools()",
    "poolsLength()",
    "allPoolsLength()",
    "getPoolCount()",
]
for sig in no_arg_sigs:
    s = sel(sig)
    r = eth_call(MAV_FACTORY, s)
    result = r.get("result", "")
    err = r.get("error", {}).get("message", "")
    if result and result != "0x":
        print(f"  {sig} [{s}]: {result}")
    else:
        print(f"  {sig} [{s}]: {err or 'empty'}")

# --- probe lookup with (tokenA, tokenB, tickSpacing) combos ---
print()
print("=== Probing lookup(address,address,uint64,uint8) ===")
WETH = TOKENS["WETH"]
USDC = TOKENS["USDC"]
# Try different tick spacings: 1, 10, 60, 200, fee params
for ts in [1, 10, 60, 200, 1000]:
    for kind in [0, 1, 2, 3]:
        ta = WETH.lower()[2:].zfill(64)
        tb = USDC.lower()[2:].zfill(64)
        ts_hex = hex(ts)[2:].zfill(64)
        kind_hex = hex(kind)[2:].zfill(64)
        s = sel("lookup(address,address,uint64,uint8)")
        data = s + ta + tb + ts_hex + kind_hex
        r = eth_call(MAV_FACTORY, data)
        result = r.get("result", "")
        if result and len(result) >= 42:
            addr = "0x" + result[-40:]
            if addr.lower() != ZERO:
                print(f"  lookup(WETH,USDC,{ts},{kind}): {addr}")

# --- try tokenAPools / poolsByToken ---
print()
print("=== Probing tokenAPools / poolsByToken ===")
for sig in ["tokenAPools(address)", "poolsByToken(address)", "getPoolsByToken(address)"]:
    s = sel(sig)
    ta = WETH.lower()[2:].zfill(64)
    r = eth_call(MAV_FACTORY, s + ta)
    result = r.get("result", "")
    err = r.get("error", {}).get("message", "")
    print(f"  {sig} [{s}]: {result[:80] if result else err}")

# --- try to get pool at index ---
print()
print("=== Probing pools(uint256) / allPools(uint256) ===")
for sig in ["pools(uint256)", "allPools(uint256)", "pool(uint256)"]:
    s = sel(sig)
    idx = hex(0)[2:].zfill(64)
    r = eth_call(MAV_FACTORY, s + idx)
    result = r.get("result", "")
    err = r.get("error", {}).get("message", "")
    if result and len(result) >= 42:
        addr = "0x" + result[-40:]
        print(f"  {sig} [{s}]: {addr}")
    else:
        print(f"  {sig} [{s}]: {err or 'empty'}")
