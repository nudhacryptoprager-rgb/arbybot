"""Find SushiSwap V3 pools on Arbitrum via Factory contract.

Generates JSON whitelist for pool addresses.

Usage:
  python scripts/find_sushi_pools.py                    # Print to stdout
  python scripts/find_sushi_pools.py --output FILE     # Save to JSON file
  python scripts/find_sushi_pools.py --update-config   # Update config/real_minimal.yaml
"""
from web3 import Web3
import os
import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

# RPC
rpc = os.environ.get('ARBY_RPC_HTTP_PRIMARY', 'https://arb1.arbitrum.io/rpc')
w3 = Web3(Web3.HTTPProvider(rpc))

# SushiSwap V3 Factory on Arbitrum
FACTORY = '0x1af415a1EbA07a4986a52B6f2e7dE7003D82231e'

# Tokens on Arbitrum
TOKENS = {
    'WETH': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
    'USDC': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831',
    'USDT': '0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9',
    'WBTC': '0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f',
    'ARB': '0x912CE59144191C1204E64559FE8253a0e49E6548',
    'LINK': '0xf97f4df75117a78c1A5a0DBb814Af92458539FB4',
    'wstETH': '0x5979D7b546E38E414F7E9822514be443A4800529',
    'GMX': '0xfc5A1A6EB076a2C7aD06eD22C90d7E710E35ad0a',
    'DAI': '0xDA10009cBd5D07dd0CeCc66161FC93D7c9000da1',
}

# Factory ABI (getPool function)
ABI = [{
    'inputs': [
        {'name': 'tokenA', 'type': 'address'},
        {'name': 'tokenB', 'type': 'address'},
        {'name': 'fee', 'type': 'uint24'}
    ],
    'name': 'getPool',
    'outputs': [{'name': 'pool', 'type': 'address'}],
    'stateMutability': 'view',
    'type': 'function'
}]

factory = w3.eth.contract(address=Web3.to_checksum_address(FACTORY), abi=ABI)

# Pairs to check
PAIRS = [
    ('WETH', 'USDC'),
    ('WETH', 'USDT'),
    ('WBTC', 'WETH'),
    ('ARB', 'WETH'),
    ('LINK', 'WETH'),
    ('wstETH', 'WETH'),
    ('GMX', 'WETH'),
    ('ARB', 'USDC'),
    ('WBTC', 'USDC'),
    ('DAI', 'USDC'),
]

FEES = [100, 500, 3000, 10000]

print('SushiSwap V3 Pools on Arbitrum:')
print('=' * 60)

found_pools = []
for base, quote in PAIRS:
    for fee in FEES:
        try:
            pool = factory.functions.getPool(
                Web3.to_checksum_address(TOKENS[base]),
                Web3.to_checksum_address(TOKENS[quote]),
                fee
            ).call()
            if pool != '0x0000000000000000000000000000000000000000':
                bps = fee // 100
                print(f'  sushiswap_v3_{base}_{quote}_{fee}: "{pool}"  # {bps/100}%')
                found_pools.append((base, quote, fee, pool))
        except Exception as e:
            print(f'  ERROR {base}/{quote} fee={fee}: {e}')

print()
print(f'Found {len(found_pools)} SushiSwap V3 pools')
print()

# Now check Uniswap V3 Factory
UNISWAP_FACTORY = '0x1F98431c8aD98523631AE4a59f267346ea31F984'
uni_factory = w3.eth.contract(address=Web3.to_checksum_address(UNISWAP_FACTORY), abi=ABI)

print('Uniswap V3 Pools on Arbitrum:')
print('=' * 60)

uni_pools = []
for base, quote in PAIRS:
    for fee in FEES:
        try:
            pool = uni_factory.functions.getPool(
                Web3.to_checksum_address(TOKENS[base]),
                Web3.to_checksum_address(TOKENS[quote]),
                fee
            ).call()
            if pool != '0x0000000000000000000000000000000000000000':
                bps = fee // 100
                print(f'  uniswap_v3_{base}_{quote}_{fee}: "{pool}"  # {bps/100}%')
                uni_pools.append((base, quote, fee, pool))
        except Exception as e:
            print(f'  ERROR {base}/{quote} fee={fee}: {e}')

print()
print(f'Found {len(uni_pools)} Uniswap V3 pools')

# Find pairs with pools on BOTH DEXes
print()
print('=' * 60)
print('PAIRS WITH POOLS ON BOTH DEXES:')
print('=' * 60)

sushi_pairs = {(b, q, f) for b, q, f, _ in found_pools}
uni_pairs = {(b, q, f) for b, q, f, _ in uni_pools}
common = sushi_pairs & uni_pairs

for b, q, f in sorted(common):
    sushi = next(p for bb, qq, ff, p in found_pools if (bb, qq, ff) == (b, q, f))
    uni = next(p for bb, qq, ff, p in uni_pools if (bb, qq, ff) == (b, q, f))
    print(f'{b}/{q} fee={f}:')
    print(f'  uniswap_v3_{b}_{q}_{f}: "{uni}"')
    print(f'  sushiswap_v3_{b}_{q}_{f}: "{sushi}"')

print()
print(f'Total pairs with both DEXes: {len(common)}')

# Generate JSON whitelist
whitelist = {
    "schema_version": "1.0.0",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "chain": "arbitrum_one",
    "chain_id": 42161,
    "factories": {
        "uniswap_v3": UNISWAP_FACTORY,
        "sushiswap_v3": FACTORY,
    },
    "tokens": TOKENS,
    "pools": {},
    "pairs_with_both_dexes": [],
}

# Add all pools
for base, quote, fee, pool in found_pools:
    key = f"sushiswap_v3_{base}_{quote}_{fee}"
    whitelist["pools"][key] = pool

for base, quote, fee, pool in uni_pools:
    key = f"uniswap_v3_{base}_{quote}_{fee}"
    whitelist["pools"][key] = pool

# Add common pairs
for b, q, f in sorted(common):
    sushi = next(p for bb, qq, ff, p in found_pools if (bb, qq, ff) == (b, q, f))
    uni = next(p for bb, qq, ff, p in uni_pools if (bb, qq, ff) == (b, q, f))
    whitelist["pairs_with_both_dexes"].append({
        "base": b,
        "quote": q,
        "fee": f,
        "uniswap_v3": uni,
        "sushiswap_v3": sushi,
    })

# Parse arguments
parser = argparse.ArgumentParser(description="Find V3 pools on Arbitrum")
parser.add_argument("--output", "-o", help="Output JSON file path")
args, _ = parser.parse_known_args()

if args.output:
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(whitelist, f, indent=2)
    print(f"\nWhitelist saved to: {output_path}")
else:
    # Save to docs/artifacts by default
    default_path = Path(__file__).parent.parent / "docs" / "artifacts" / "pool_whitelist.json"
    default_path.parent.mkdir(parents=True, exist_ok=True)
    with open(default_path, "w") as f:
        json.dump(whitelist, f, indent=2)
    print(f"\nWhitelist saved to: {default_path}")
