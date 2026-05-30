"""Probe Maverick V2 factory to find pool pair lookup API."""
import httpx
from web3 import Web3

RPC = "https://base.publicnode.com"
MAV_FACTORY = "0x0a7e848aca42d879ef06507fca0e7b33a0a63c1e"

WETH   = "0x4200000000000000000000000000000000000006"
USDC   = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
cbETH  = "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22"
wstETH = "0xc1cba3fcea344f92d9239c08c0568f6f2f0ee452"
cbBTC  = "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf"


def eth_call(to: str, data: str) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"]}
    return httpx.post(RPC, json=body, timeout=8.0).json()


def sel(sig: str) -> str:
    return "0x" + Web3.keccak(text=sig).hex()[:8]


ta = WETH.lower()[2:].zfill(64)
tb = USDC.lower()[2:].zfill(64)

print("=== Two-address functions on WETH/USDC ===")
sigs = [
    "getPoolCountForTokens(address,address)",
    "poolsForTokenPair(address,address)",
    "getPoolsForPair(address,address)",
    "tokenPairPools(address,address)",
    "getPools(address,address)",
    "poolsForTokens(address,address)",
    "poolsByTokenPair(address,address)",
    "countOfPools(address,address)",
    "lookupByPair(address,address)",
    "poolsFor(address,address)",
]
for sig in sigs:
    s = sel(sig)
    r = eth_call(MAV_FACTORY, s + ta + tb)
    result = r.get("result", "")
    err = r.get("error", {}).get("message", "?")
    if result and result != "0x":
        print(f"  OK  {sig} [{s}]: {result[:80]}")
    else:
        print(f"  ERR {sig} [{s}]: {err}")

# Try with (address,address,uint256) offset
print()
print("=== Three-arg: (address,address,uint256) ===")
sigs3 = [
    "lookupPool(address,address,uint256)",
    "getPoolsForPair(address,address,uint256)",
    "poolsByTokenPair(address,address,uint256)",
    "poolsForTokens(address,address,uint256)",
    "tokenPairPools(address,address,uint256)",
]
offset = "0" * 64
for sig in sigs3:
    s = sel(sig)
    r = eth_call(MAV_FACTORY, s + ta + tb + offset)
    result = r.get("result", "")
    err = r.get("error", {}).get("message", "?")
    if result and result != "0x":
        print(f"  OK  {sig} [{s}]: {result[:80]}")
    else:
        print(f"  ERR {sig} [{s}]: {err}")

# Maverick V2 factory: try fetching first few pools by index
# The poolCount() = 107. Try to get pool at index via alternative method.
print()
print("=== Pool by index via different methods ===")
idx = "0" * 64
idx_sigs = [
    "poolByIndex(uint256)",
    "getPool(uint256)",
    "allPools(uint256)",
    "pools(uint256)",
    "poolAt(uint256)",
    "getPoolAt(uint256)",
    "poolAtIndex(uint256)",
]
for sig in idx_sigs:
    s = sel(sig)
    r = eth_call(MAV_FACTORY, s + idx)
    result = r.get("result", "")
    err = r.get("error", {}).get("message", "?")
    if result and len(result) >= 42:
        addr = "0x" + result[-40:]
        print(f"  OK  {sig} [{s}]: {addr}")
    else:
        print(f"  ERR {sig} [{s}]: {err}")
