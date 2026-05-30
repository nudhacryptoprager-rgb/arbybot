"""Find Maverick V2 pool creation events from factory on Base chain.

Uses eth_getLogs with PoolCreated event signature to enumerate pools.
Then checks tokenA/tokenB for pools matching our token universe.
"""
import httpx
from web3 import Web3

RPC = "https://base.publicnode.com"
MAV_FACTORY = "0x0a7e848aca42d879ef06507fca0e7b33a0a63c1e"
MAV_POOL_INFO = "0x67b70f73bee50ab48f0e8d75b94d4f6dced6ad72"

# Our token universe
TOKENS = {
    "WETH":   "0x4200000000000000000000000000000000000006",
    "USDC":   "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "cbETH":  "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22",
    "wstETH": "0xc1cba3fcea344f92d9239c08c0568f6f2f0ee452",
    "cbBTC":  "0xcbb7c0000ab88b473b1f5afd9ef808440eed33bf",
    "EURC":   "0x60a3e35cc302bfa44cb288bc5a4f316fdb1adb42",
    "AERO":   "0x940181a94a35a4569e4529a3cdfb74e38fd98631",
    "DAI":    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",
    "USDC":   "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    "VIRTUAL":"0x0b3e328455c4059eeb9e3f84b5543f74e24e7e1b",
    "BRETT":  "0x532f27101965dd16442e59d40670faf5ebb142e4",
    "TOSHI":  "0xac1bd2486aaf3b5c0fc3fd868558b082a531b2b4",
    "DEGEN":  "0x4ed4e862860bed51a9570b96d89af5e1b0efefed",
}

TOKEN_ADDR_TO_SYM = {v.lower(): k for k, v in TOKENS.items()}


def rpc_call(method: str, params: list) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return httpx.post(RPC, json=body, timeout=15.0).json()


def eth_call(to: str, data: str) -> str:
    r = rpc_call("eth_call", [{"to": to, "data": data}, "latest"])
    return r.get("result", "")


def sel(sig: str) -> str:
    return "0x" + Web3.keccak(text=sig).hex()[:8]


# Get current block
block_r = rpc_call("eth_blockNumber", [])
cur_block = int(block_r["result"], 16)
print(f"Current block: {cur_block}")

# Maverick V2 launched on Base around block ~12M. Let's search recent blocks (~500k)
# PoolCreated event topic - try common event signatures
pool_created_sigs = [
    "PoolCreated(address,address,address,uint256,uint256)",
    "PoolCreated(address,address,address,uint64,uint256,uint256)",
    "PoolCreated(address,address,address,uint8,uint256,int32)",
    "PoolCreated(address,address,uint256,address)",
    "PoolCreated(address,address,address)",
]

print("\n=== Pool creation event topics ===")
for sig in pool_created_sigs:
    topic = "0x" + Web3.keccak(text=sig).hex()
    print(f"  {sig[:50]:50s} {topic[:12]}")

# Try to get logs with different topics
# Search last 50000 blocks (about 2 weeks)
from_block = hex(max(0, cur_block - 50000))
to_block = hex(cur_block)

print(f"\n=== Scanning blocks {from_block} to {to_block} for PoolCreated events ===")
for sig in pool_created_sigs[:3]:
    topic = "0x" + Web3.keccak(text=sig).hex()
    params = [{
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": MAV_FACTORY,
        "topics": [topic]
    }]
    r = rpc_call("eth_getLogs", params)
    logs = r.get("result", [])
    err = r.get("error", {})
    if logs:
        print(f"  FOUND {len(logs)} logs for: {sig}")
        for log in logs[:5]:
            print(f"    tx={log.get('transactionHash','?')[:16]} data={log.get('data','?')[:40]}")
        break
    elif err:
        print(f"  ERR {sig[:40]}: {err.get('message','?')[:60]}")
    else:
        print(f"  EMPTY: {sig[:40]}")

# Alternative: use tokenA()/tokenB() on known pool addresses from on-chain sources
# Let's try directly fetching some pools from the Maverick public subgraph or explorer
# Actually let's try getting the pool count and then fetching specific pools

# Check if there's a factory registry or lens contract
print()
print("=== Try factory lens/registry ===")
lens_sigs = ["lens()", "registry()", "poolLens()", "poolRegistry()"]
for sig in lens_sigs:
    s = sel(sig)
    result = eth_call(MAV_FACTORY, s)
    if result and result != "0x" and len(result) >= 42:
        addr = "0x" + result[-40:]
        print(f"  {sig}: {addr}")
    else:
        print(f"  {sig}: no result")

# Final: try direct pool address for WETH/USDC that might be known
# From Maverick docs/mainnet: common pools
# Try calling tokenA() on some candidate addresses
print()
print("=== Known Maverick V2 WETH/USDC candidates ===")
# These are candidate pool addresses from public sources
candidates = [
    "0x3a8fb94a3148175cae37da80fb44ff4d3d0da4e2",
    "0xfce0a33db3f0e1bfe0b3eb7fd5f0d1e99e73fdab",
    "0x2f8a14be41bdf0fc42c71ea3a5a01b8c7498b4ea",
    "0x94b0e4b89e01a33a2b0dddce47c51e3a64f29c74",
]
sel_tokenA = sel("tokenA()")
sel_tokenB = sel("tokenB()")
for pool in candidates:
    r_a = eth_call(pool, sel_tokenA)
    r_b = eth_call(pool, sel_tokenB)
    if r_a and len(r_a) >= 42:
        tA = "0x" + r_a[-40:]
        tB = "0x" + r_b[-40:] if r_b and len(r_b) >= 42 else "?"
        symA = TOKEN_ADDR_TO_SYM.get(tA.lower(), tA[:12])
        symB = TOKEN_ADDR_TO_SYM.get(tB.lower() if tB != "?" else "", tB[:12])
        print(f"  {pool}: tokenA={symA} tokenB={symB}")
    else:
        print(f"  {pool}: not a Maverick pool (no tokenA)")
