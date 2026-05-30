"""Quick probe for Maverick V2 PoolCreated events using small block range."""
import httpx
from web3 import Web3

RPC = "https://base.publicnode.com"
MAV_FACTORY = "0x0a7e848aca42d879ef06507fca0e7b33a0a63c1e"

TOKENS = {
    "WETH":   "0x4200000000000000000000000000000000000006",
    "USDC":   "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "cbETH":  "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22",
    "wstETH": "0xc1cba3fcea344f92d9239c08c0568f6f2f0ee452",
    "cbBTC":  "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf",
    "EURC":   "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42",
    "AERO":   "0x940181a94a35a4569e4529a3cdfb74e38fd98631",
    "DAI":    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",
    "VIRTUAL":"0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b",
}
TOKEN_ADDR_TO_SYM = {v.lower(): k for k, v in TOKENS.items()}


def rpc(method, params, timeout=15):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return httpx.post(RPC, json=body, timeout=timeout).json()


cur_block = int(rpc("eth_blockNumber", [])["result"], 16)
print(f"Current block: {cur_block}")

# PoolCreated(address,address,address,uint256,uint256) -> common pattern
topic_sigs = [
    "PoolCreated(address,address,address,uint256,uint256)",
    "PoolCreated(address,address,address,uint64,uint256)",
    "PoolCreated(address,address,address)",
]

# Scan last 2000 blocks only
from_block = hex(cur_block - 2000)
to_block = hex(cur_block)

print(f"Scanning blocks {from_block} to {to_block}")
for sig in topic_sigs:
    topic = "0x" + Web3.keccak(text=sig).hex()
    params = [{"fromBlock": from_block, "toBlock": to_block,
               "address": MAV_FACTORY, "topics": [topic]}]
    r = rpc("eth_getLogs", params, timeout=15)
    logs = r.get("result", [])
    err_msg = r.get("error", {}).get("message", "empty")
    if logs:
        print(f"FOUND {len(logs)} logs for: {sig}")
        for log in logs[:3]:
            print(f"  topics: {log.get('topics', [])}")
            print(f"  data: {log.get('data', '')[:80]}")
        break
    else:
        print(f"EMPTY for {sig}: {err_msg}")

# Alternative: try to get tokenA/tokenB for a few candidate pool addresses
# from on-chain discovery. Let's scan by trying pools from base DeFiLlama or similar.
# Just test if the known Maverick V1 WETH/USDC pool address works on V2 ABI
print("\n=== Testing tokenA() on candidate addresses ===")

SEL_A = "0x" + Web3.keccak(text="tokenA()").hex()[:8]
SEL_B = "0x" + Web3.keccak(text="tokenB()").hex()[:8]

# These are potential Maverick V2 WETH/USDC pools from community sources
candidates = [
    "0x72e98ee7e5f6e8d8cd31a11f98e9f2b3c30f04ce",
    "0xec81f9bb71e8e6c22b1b3dc5cb3b9d93a69ec1f4",
    "0x7b7ec55d9b8c80e6d3f74b33bff53bbc13db785e",
    "0x63e9b7aef620eba74c32a7a1dfd02e1bab43a9ad",
    "0x1e79eb1a2aa2a3d08f23d1c54a0bcd77b10d98a3",
    "0x34a6d32f6d1ce6cb0bfb8c8fd7c5dd3c60bc9e2a",
    "0x8c3b96bdcb4a5f8d5e70b9e1c80d21fef4bf8c21",
]
for pool in candidates:
    r_a = rpc("eth_call", [{"to": pool, "data": SEL_A}, "latest"]).get("result", "")
    if r_a and len(r_a) >= 42:
        r_b = rpc("eth_call", [{"to": pool, "data": SEL_B}, "latest"]).get("result", "")
        tA = "0x" + r_a[-40:]
        tB = ("0x" + r_b[-40:]) if r_b and len(r_b) >= 42 else "?"
        sA = TOKEN_ADDR_TO_SYM.get(tA.lower(), tA[:12])
        sB = TOKEN_ADDR_TO_SYM.get(tB.lower() if tB != "?" else "", tB[:12])
        print(f"  {pool}: {sA}/{sB}")
    else:
        print(f"  {pool}: not a Maverick pool")
