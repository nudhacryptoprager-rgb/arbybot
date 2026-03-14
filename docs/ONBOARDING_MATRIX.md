# Chain-by-Chain Onboarding Matrix

> **Policy**: Full universe preserved. Staged chain onboarding via configs/adapters, NOT by removing pairs/chains.
> **Strategy**: Additive rollout — each chain progresses through stage configs as adapter/factory layer matures.
> **Updated**: 2026-03-14 (R27)

## Adapter Registry Status

| adapter_type | Class | Module | Status |
|-------------|-------|--------|--------|
| `uniswap_v3` | `UniswapV3Adapter` | `dex/adapters/uniswap_v3.py` | PRODUCTION |
| `algebra` | `AlgebraAdapter` | `dex/adapters/algebra.py` | PRODUCTION |
| `ve33` | — | — | NOT IMPLEMENTED |

## Coverage Matrix

| Chain | DEX | adapter_type | Factory | Quoter | Fee Tiers | Adapter Ready | Executable | Blocker |
|-------|-----|-------------|---------|--------|-----------|---------------|------------|---------|
| **arbitrum_one** | uniswap_v3 | uniswap_v3 | 0x1F98… | quoter_v2: 0x61fF… | 100,500,3000,10000 | YES | YES | — |
| **arbitrum_one** | sushiswap_v3 | uniswap_v3 | 0x1af4… | quoter_v2: 0x0524… | 100,500,3000,10000 | YES | YES | — |
| **arbitrum_one** | camelot_v3 | algebra | 0x1a3c… | quoter: 0x0Fc7… | dynamic | YES | EXCLUDED | Not in productive contour: remove from exclusion to enable |
| **arbitrum_one** | pancakeswap_v3 | uniswap_v3 | 0x0BFb… | quoter_v2: 0xB048… | 100,500,2500,10000 | YES | YES | — |
| **zksync** | uniswap_v3 | uniswap_v3 | 0x8FdA… | quoter_v2: 0x8Cb5… | 100,500,3000,10000 | YES | YES | — |
| **zksync** | pancakeswap_v3 | uniswap_v3 | 0x1BB7… | quoter_v2: 0x3d14… | 100,500,2500,10000 | YES | YES | — |
| **base** | uniswap_v3 | uniswap_v3 | 0x3312… | quoter_v2: 0x3d4e… | 100,500,3000,10000 | YES | YES | — |
| **base** | sushiswap_v3 | uniswap_v3 | 0xc35D… | quoter_v2: 0xb1E8… | 100,500,3000,10000 | YES | YES | — |
| **base** | pancakeswap_v3 | uniswap_v3 | 0x0BFb… | quoter_v2: 0xB048… | 100,500,2500,10000 | YES | YES | — |
| **base** | aerodrome | ve33 | 0x420D… | — | — | NO | NO | `ve33` adapter not implemented |
| **mantle** | agni_v3 | uniswap_v3 | 0x2578… | quoter_v2: 0xc4aa… | 100,500,2500,10000 | YES | YES | — |
| **mantle** | stratum | ve33 | 0x061F… | — | — | NO | NO | `ve33` adapter not implemented |
| **linea** | lynex_v3 | algebra | 0x622b… | quoter: 0xcE82… | dynamic | YES | PARTIAL | Algebra path not stabilized for production |
| **linea** | pancakeswap_v3 | uniswap_v3 | 0x0BFb… | quoter_v2: 0xB048… | 100,500,2500,10000 | YES | YES | — |
| **scroll** | nuri_v3 | uniswap_v3 | 0xAAA3… | quoter_v2: 0xAAAE… | 100,500,3000,10000 | YES | EXCLUDED | Config mismatch: dexes.yaml says uniswap_v3/quoter_v2 but coverage_intent_scroll.yaml excludes as algebra-incompatible |
| **scroll** | sushiswap_v3 | uniswap_v3 | 0x46B3… | quoter_v2: 0xe43c… | 100,500,3000,10000 | YES | YES | Single executable DEX → ECOSYSTEM_BLOCKED |

## Contract Mismatches (must resolve)

1. **scroll/nuri_v3**: `config/dexes.yaml` declares `adapter_type: uniswap_v3` with `quoter_v2`, but `config/coverage_intent_scroll.yaml` excludes it claiming algebra-incompatible. One of them is wrong. Resolution: verify on-chain whether nuri_v3 quoter responds to QuoterV2 ABI, then align both configs.

## Additive Rollout Order

| Priority | Chain | Stage | Criteria for Next Stage |
|----------|-------|-------|------------------------|
| 1 | **arbitrum_one** | NORMAL (primary) | Exit gate: 5 consecutive PASS, signals>=4, cross_dex>=3, drift<=0.20 |
| 2 | **zksync** | COVERAGE → candidate | drift_rejection_rate_median < 0.25, all DEXes executable |
| 3 | **base** | COVERAGE → candidate | ve33 adapter (aerodrome) implemented, mixed-source noise < 10% |
| 4 | **mantle** | COVERAGE only | ve33 adapter (stratum) implemented → cross-DEX surface available |
| 5 | **linea** | COVERAGE only | lynex_v3 Algebra path stabilized → cross-DEX pair with pancakeswap_v3 |
| 6 | **scroll** | monitoring_only | nuri_v3 contract mismatch resolved, 2nd executable DEX confirmed |

## Stage Config Naming Convention

Each chain has up to 3 stage configs:
- `onboard_<chain>_stage1.yaml` — single known-good DEX, COVERAGE mode, relaxed thresholds
- `onboard_<chain>_stage2.yaml` — all executable DEXes enabled, COVERAGE mode, production thresholds
- `onboard_<chain>_candidate.yaml` — full universe, candidate for NORMAL promotion

All stage configs preserve the full chain universe (intent.txt pairs). They differ ONLY in which DEXes are active and what thresholds apply.
