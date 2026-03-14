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
| **arbitrum_one** | camelot_v3 | algebra | 0x1a3c… | quoter: 0x0Fc7… | dynamic | YES | CANDIDATE (verified R27.1) | Verified online: `ci_m5_gate_20260314_101735` (4-DEX PASS, 14 signals, $14.61) |
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
| **scroll** | nuri_v3 | uniswap_v3 | 0xAAA3… | quoter_v2: 0xAAAE… | 100,500,3000,10000 | YES | VERIFIED (R27.1) | Verified online: `ci_m5_gate_20260314_102036` (3 signals, quoter_v2 confirmed) |
| **scroll** | sushiswap_v3 | uniswap_v3 | 0x46B3… | quoter_v2: 0xe43c… | 100,500,3000,10000 | YES | YES | Single executable DEX → ECOSYSTEM_BLOCKED |

## Contract Mismatches (resolved R27)

1. **scroll/nuri_v3**: ~~`coverage_intent_scroll.yaml` excluded nuri_v3 as algebra-incompatible~~ — **RESOLVED R27, VERIFIED R27.1**. Trust anchor (`dexes.yaml`) declares `adapter_type: uniswap_v3` with `quoter_v2`. Config aligned; online proof: `ci_m5_gate_20260314_102036` (3 cross-DEX signals). Note: 1 PASS = adapter/quoter proof, NOT exit from ECOSYSTEM_BLOCKED.
2. **arbitrum_one/camelot_v3**: Adapter ready (algebra/PRODUCTION), **VERIFIED R27.1**: `ci_m5_gate_20260314_101735` (4-DEX PASS, 14 signals, $14.61, camelot contributing to cross_dex=27).

## Additive Rollout Order

| Priority | Chain | Stage | Criteria for Next Stage |
|----------|-------|-------|------------------------|
| 1 | **arbitrum_one** | NORMAL (primary) | Exit gate: 5 consecutive PASS, signals>=4, cross_dex>=3, drift<=0.20 |
| 2 | **zksync** | COVERAGE → candidate | drift_rejection_rate_median < 0.25, all DEXes executable |
| 3 | **base** | COVERAGE → candidate | ve33 adapter (aerodrome) implemented, mixed-source noise < 10% |
| 4 | **mantle** | COVERAGE only | ve33 adapter (stratum) implemented → cross-DEX surface available |
| 5 | **linea** | COVERAGE only | lynex_v3 Algebra path stabilized → cross-DEX pair with pancakeswap_v3 |
| 6 | **scroll** | monitoring_only | nuri_v3 verified R27.1 (adapter/quoter proof), needs sustained evidence for promotion |

## Stage Config Naming Convention

Each chain has up to 3 stage configs:
- `onboard_<chain>_stage1.yaml` — single known-good DEX, COVERAGE mode, relaxed thresholds
- `onboard_<chain>_stage2.yaml` — all executable DEXes enabled, COVERAGE mode, production thresholds
- `onboard_<chain>_candidate.yaml` — full universe, candidate for NORMAL promotion

All stage configs preserve the full chain universe (intent.txt pairs). They differ ONLY in which DEXes are active and what thresholds apply.
