#!/usr/bin/env python3
"""Temporary script to analyze verified pools for cross-DEX status."""
import json
from collections import defaultdict

with open('data/runs/_cache/verified_pools.json') as f:
    data = json.load(f)

pairs = defaultdict(lambda: {'uniswap_v3': [], 'sushiswap_v3': []})
for pool in data['verified_pools']:
    pair = pool['pair']
    dex = pool['dex']
    if pool['active']:
        pairs[pair][dex].append(pool['fee'])

print('=== Cross-DEX Analysis ===')
for pair, dexes in pairs.items():
    uni_fees = dexes['uniswap_v3']
    sushi_fees = dexes['sushiswap_v3']
    status = 'CROSS-DEX' if uni_fees and sushi_fees else 'UNI-ONLY' if uni_fees else 'SUSHI-ONLY' if sushi_fees else 'NONE'
    print(f'{pair}: {status} | uniswap_v3={uni_fees or []}  sushiswap_v3={sushi_fees or []}')

print('\n=== Correct Pool Addresses for real_minimal.yaml ===')
for pool in data['verified_pools']:
    if pool['active'] and pool['fee'] in [500, 3000]:  # Only standard fee tiers
        key = f"{pool['dex']}_{pool['pair'].replace('/', '_')}_{pool['fee']}"
        print(f"  {key}: \"{pool['pool']}\"  # liquidity={int(pool['liquidity'])}")

print('\n=== Anchor Prices (token_out/token_in) ===')
Q96 = 2**96
for pool in data['verified_pools']:
    if pool['active'] and pool['fee'] == 3000:
        sqrtPriceX96 = int(pool['sqrtPriceX96'])
        price = (sqrtPriceX96 / Q96) ** 2
        pair = pool['pair']
        base = pool['base']
        quote = pool['quote']
        # price is token1/token0 (quote/base in V3 convention)
        # For PENDLE/WETH: price = WETH per PENDLE
        print(f"{pool['dex']} {pair}: {quote}/{base}={price:.8f}")
