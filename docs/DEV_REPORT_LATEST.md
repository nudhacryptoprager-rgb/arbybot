# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-03-04T08:35:45Z
run_id: data/runs/ci_m5_gate_20260304_093531
mode: ONLINE (v3.2.10: SMOKE run isolation + NORM-only rolling policy)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, run_kind=NORMAL)
code_identity:
  primary: ts:2026-03-04T08:35:45.125798Z
  dirty: false
  desc: v3.2.10 SMOKE isolation: run_kind segmentation, NORM-only rolling, inspect_rolling v2.1.0

## 1) Scope (що і навіщо)
goal (Roadmap пункт): SMOKE run isolation - prevent non-production runs from polluting rolling metrics
change_summary:
  - ADD: run_kind field (NORMAL|SMOKE|COVERAGE) to configs, artifacts, aggregator
  - ADD: NORM-only rolling policy - SMOKE runs excluded from emit_to_aggregator_light()
  - ADD: ci_m5_0_gate.py detects run_kind=SMOKE in config, sets refresh_rolling=False
  - ADD: scripts/inspect_rolling.py v2.1.0 - window_chain_key vs latest_chain_key separation
  - ADD: quick_stats.chain_keys as sorted list for automation
  - ADD: tests/unit/test_smoke_run_isolation.py (6 tests)
  - FIX: config/real_scan_linea_smoke.yaml - pure connectivity (pairs: [], run_kind: SMOKE)
  - FIX: validate_universe.py - pool resolution warnings, run_kind display
  - EVIDENCE: ONLINE NORMAL run (ci_m5_gate_20260304_093531) updates rolling correctly
  - RESULT: 31 runs in window, 24 data runs, agg_status=PASS
  - TESTS: 1279 passed (includes 6 new SMOKE isolation tests)
touched_files:
  - config/real_scan_linea_smoke.yaml (run_kind: SMOKE, pairs: [])
  - strategy/jobs/run_scan_real.py (run_kind extraction)
  - strategy/artifacts.py (run_kind in config_params)
  - m4/fixtures.py (run_kind in run_summary_data)
  - m4/rolling_store.py (SMOKE exclusion, chain_keys in quick_stats)
  - scripts/ci_m5_0_gate.py (SMOKE detection, refresh_rolling=False)
  - scripts/inspect_rolling.py (v2.1.0 - chain_key separation)
  - scripts/validate_universe.py (pool checks, run_kind display)
  - tests/unit/test_smoke_run_isolation.py (NEW - 6 tests)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: 1279 passed, 1 skipped
py -3.11 scripts/check_repo_safety.py: RESULT: PASS (0 warnings)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1: RESULT: PASS
py -3.11 scripts/inspect_rolling.py --json: agg_status=PASS, runs_in_window=31, latest_chain_key=arbitrum_one
py -3.11 scripts/validate_universe.py --config config/real_minimal.yaml: STATUS: PASS (7 pairs, 2 DEXes)
py -3.11 scripts/validate_universe.py --config config/real_scan_linea_smoke.yaml: STATUS: PASS (0 pairs, SMOKE)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json  
  - data/runs/_rolling/m4_stability_agg.json
capstone_run_dir:
  - data/runs/ci_m5_gate_20260304_093531/reports (arbitrum_one, run_kind=NORMAL)
v3_2_10_evidence:
  - runs_in_window: 31
  - agg_status: PASS
  - data_runs: 24
  - chain_keys: ['arbitrum_one', 'linea'] (linea from historical, will age out)
  - window_chain_key: MIXED (historical pollution, expected)
  - latest_chain_key: arbitrum_one (new run correct)
  - latest run: run_kind=NORMAL, chain_id=42161
  - inspect_rolling v2.1.0: window_chain_key vs latest_chain_key separation
  - SMOKE isolation: emit_to_aggregator_light() skips SMOKE runs
  - tests: 1279 passed (6 new SMOKE isolation tests)

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  agg_reasons: []
  quality_warnings: ['MIXED_CHAIN_KEYS(arbitrum_one,linea)'] (historical, will age out)
  chain_keys: ['arbitrum_one', 'linea']
  data_run_rate: 0.7742
  runs_in_window: 31
  in_warmup: false
  effective_pass_rate: 0.7742
  run_context.run_dir_name: ci_m5_gate_20260304_093531
  inputs.chain_key: arbitrum_one
  inputs.run_kind: NORMAL
  inputs.config_path: config/real_minimal.yaml (POSIX)

run_summary_latest.json (ci_m5_gate_20260304_093531):
  schema_version: m4:run_summary:v2.0
  status: PASS
  profit_status: PASS
  drift_status: PASS
  quality_status: PASS
  quality_reasons: []
  run_context.run_timestamp: 2026-03-04T08:35:45Z
  run_kind: NORMAL
  inputs.run_mode: REGISTRY_REAL
  inputs.chain_key: arbitrum_one
  inputs.chain_id: 42161
  metrics:
    signals_count: 4
    total_net_usdc: 6.54

m4_stability_agg.json (quick_stats):
  runs_in_window: 31
  agg_status: PASS
  pass_rate: 1.0
  data_run_rate: 0.7742
  fragile_rate_p90: 0.0
  unique_pairs: 5
  unique_routes_cross_dex: 2
  total_net_usdc: 87.50
  chain_key: MIXED (historical linea runs in window)
  chain_keys: ['arbitrum_one', 'linea']

## 5) V3.2.10 Changes (SMOKE run isolation + NORM-only rolling)

### Core Changes

1. **run_kind classification** (NORMAL|SMOKE|COVERAGE):
   - Location: configs, run_scan_real.py, artifacts.py, fixtures.py
   - run_kind field added to: config YAML, stats, config_params, run_summary_data
   - Default: "NORMAL" (production runs)
   - Purpose: Classify runs for rolling segmentation

2. **NORM-only rolling policy** (m4/rolling_store.py):
   - emit_to_aggregator_light() skips SMOKE runs entirely
   - Prints: "[EMIT-AGG] SKIP SMOKE run_id=... (NORM-only rolling policy)"
   - Purpose: Prevent SMOKE/multi-chain connectivity runs from polluting rolling metrics

3. **ci_m5_0_gate.py SMOKE detection**:
   - Reads config YAML, detects run_kind=SMOKE
   - Sets refresh_rolling=False for SMOKE runs
   - Purpose: Double-guard against rolling pollution from gate runs

4. **inspect_rolling.py v2.1.0** (chain_key separation):
   - Splits chain_key into window_chain_key (from quick_stats) and latest_chain_key (from _latest.inputs)
   - JSON output: window_chain_key, latest_chain_key, chain_keys
   - Purpose: Operational clarity - distinguish aggregate vs current run

5. **quick_stats.chain_keys** (m4/rolling_store.py):
   - Added sorted list of all chain_keys in rolling window
   - Purpose: Machine-readable chain diversity for automation

### Config Changes

6. **config/real_scan_linea_smoke.yaml** (pure connectivity):
   - run_kind: SMOKE
   - pairs: [] (no pairs - connectivity only)
   - dexes: [] (optional)
   - scanner_cycles: 1
   - Purpose: RPC/chain connectivity check without quotes

### New Tests (6 total)

7. **tests/unit/test_smoke_run_isolation.py**:
   - test_smoke_run_not_added_to_aggregator
   - test_normal_run_added_to_aggregator
   - test_smoke_run_default_kind_is_normal
   - test_smoke_run_does_not_pollute_chain_keys
   - test_config_run_kind_smoke_value
   - test_truth_report_includes_run_kind

## 6) Roundtrip Status (current run)

roundtrip_summary:
  spread_signals: 4
  threshold_bps: 10
  pairs: WETH/USDT, WBTC/WETH, ARB/WETH, WBTC/USDC

Analysis:
  - 18 valid quotes fetched from 7 pairs
  - 4 spread signals passed 10bps threshold
  - Best spread: ARB/WETH 157.98bps (sushiswap_v3->uniswap_v3)
  - PASS status with positive PnL: total_net_usdc=6.54
  - Aggregate maintains: agg_status=PASS, pass_rate=1.0, runs_in_window=31

## 7) Rolling Window Final State

| Metric | Value | Threshold | Status |
|--------|-------|-----------|--------|
| agg_status | PASS | != FAIL | OK |
| agg_reasons | [] | - | OK |
| quality_warnings | ['MIXED_CHAIN_KEYS'] | - | OK (historical, will age out) |
| runs_in_window | 31 | >= 5 | OK |
| pass_rate | 1.0 | >= 0.8 | OK |
| data_run_rate | 0.7742 | >= 0.3 | OK |
| fragile_rate_p90 | 0.0 | <= 0.5 | OK |
| unique_pairs | 5 | >= 3 | OK |
| unique_routes_cross_dex | 2 | >= 2 | OK |
| window_chain_key | MIXED | - | HISTORICAL (linea in window) |
| latest_chain_key | arbitrum_one | - | CURRENT RUN OK |
| chain_keys | ['arbitrum_one', 'linea'] | - | linea will age out |

## 8) Session Goals Status

| Goal | Status | Evidence |
|------|--------|----------|
| run_kind classification | DONE | NORMAL\|SMOKE\|COVERAGE in configs/artifacts |
| NORM-only rolling policy | DONE | emit_to_aggregator_light() skips SMOKE |
| ci_m5_0_gate SMOKE detection | DONE | refresh_rolling=False for run_kind=SMOKE |
| inspect_rolling v2.1.0 | DONE | window_chain_key vs latest_chain_key |
| quick_stats.chain_keys | DONE | sorted list for automation |
| linea smoke pure connectivity | DONE | pairs: [], run_kind: SMOKE |
| validate_universe pool checks | DONE | pool resolution warnings |
| SMOKE isolation tests | DONE | 6 tests in test_smoke_run_isolation.py |
| ONLINE NORMAL run | DONE | ci_m5_gate_20260304_093531, run_kind=NORMAL |
| repository safety | DONE | check_repo_safety.py PASS |

## 9) M4 DoD Status

| DoD | Status | Evidence |
|-----|--------|----------|
| Core Truth (paper +PnL) | [OK] PROVEN | N=31 runs, total_net_usdc=$87.50 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, chain_keys=['arbitrum_one','linea'] |
| FRAGILE_P90_ELEVATED | [OK] RESOLVED | fragile_rate_p90=0.0 |
| M4.1 Time-Bound Window | [OK] ACHIEVED | runs_in_window=31 |
| Diversity gates | [OK] PASS | DIVERSITY_PAIRS 5>=4, DIVERSITY_ROUTES 2>=2 |
| SMOKE isolation | [OK] PROVEN | emit_to_aggregator_light() skips SMOKE runs |
| NORM-only rolling | [OK] ACTIVE | only NORMAL runs update rolling |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | slippage > spreads (market conditions) |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |

## 10) Next Steps

1. **Wait for linea runs to age out** - MIXED_CHAIN_KEYS will resolve in 24h
2. **Run linea SMOKE config** - verify pure connectivity (py scripts/ci_m5_0_gate.py --online --config config/real_scan_linea_smoke.yaml)
3. **Confirm rolling exclusion** - SMOKE runs should not appear in aggregator
4. **Consider aggregator reset** - if immediate clean state needed (optional)

## 5) Roundtrip Fix Details (v2.8.1)

### Bug Identified
```
BEFORE: net_pnl_bps = (gross_pnl_wei - gas_cost_wei) / amount_in * 10000
        = (50000 - 6057621785286) / 367647 * 10000
        = -203668019316.38 bps (trillions!)
        
PROBLEM: gross_pnl_wei is WBTC-wei (8 decimals)
         gas_cost_wei is ETH-wei (18 decimals)
         Subtracting them produces nonsense
```

### Fix Applied
```python
# engine/roundtrip.py line 298-307
# v2.8.1: net_pnl_bps from USD (not mixed wei)
notional_usd = (amount_in / (10 ** token_in_decimals)) * effective_token_price
result.net_pnl_bps = (result.net_pnl_usd / notional_usd) * 10000

# strategy/jobs/run_scan_real.py line 600-615
# v2.8.1: Build token_decimals from pairs_list or core_tokens
token_decimals = {}
if pairs_list:
    for p in pairs_list:
        token_decimals[p.token_in] = p.token_in_decimals
```

### Test Added
```python
# tests/unit/test_roundtrip.py
def test_net_pnl_bps_uses_usd_not_mixed_wei(self):
    """net_pnl_bps must be derived from USD, not mixed token-wei/ETH-wei."""
    # WBTC with 8 decimals
    # Before fix: net_pnl_bps=-1205999999995.0 (trillions!)
    # After fix: ~0.18 bps (from USD calculation)
    assert abs(result.net_pnl_bps) < 1000  # Key check: not billions
```

## 6) Quality Notes

- roundtrip net_pnl_bps тепер USD-канонічний (decimals-safe)
- roundtrip все ще < 0, причина: impact/fees (slippage 68-111 bps eats edge)
- $50 sizing test: no roundtrip candidates (spreads too narrow at lower size)
- LINK/USDC removed from hunting (inverted direction, price 1e23 nonsense)
- WSTETH alias added to core_tokens (symbol normalization for discovery/CLI)
  - Pool verification: uniswap_v3_ARB_WETH_500 liq=684124252408873178675578

log_evidence:
  - "unique_pairs: ['ARB/USDC', 'ARB/WETH', 'LINK/WETH', 'WBTC/USDC', 'WBTC/WETH', 'WETH/USDC', 'WETH/USDT', 'wstETH/WETH']"
  - "unique_routes: ['sushiswap_v3->uniswap_v3', 'uniswap_v3->sushiswap_v3', 'uniswap_v3->uniswap_v3']"

diversity_resolution:
  - BEFORE v2.5.2: unique_pairs=6 < 8 (DIVERSITY_PAIRS_LOW)
  - AFTER v2.5.2: unique_pairs=8 >= 8 (RESOLVED!)
  - DIVERSITY_ROUTES_FAIL: RESOLVED (v2.5.2 Directive #14)
  - DIVERSITY_PAIRS_LOW: RESOLVED (v2.5.2 Directive #15)

## 6) M4 DoD Status

| DoD | Status | Evidence |
|-----|--------|----------|
| Core Truth (paper +PnL) | [OK] PROVEN | N=30 runs, total_net_usdc=$80.96 |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, MIXED_CHAIN_KEYS warning |
| FRAGILE_P90_ELEVATED | [OK] RESOLVED | fragile_rate_p90=0.0 (was 0.33, goal <=0.30) |
| M4.1 Time-Bound Window | [OK] ACHIEVED | runs_in_window=30 |
| Diversity gates | [OK] PASS | DIVERSITY_PAIRS 5>=4, DIVERSITY_ROUTES 2>=2 |
| Multi-chain readiness | [OK] PROVEN | chain_keys=['arbitrum_one','linea'] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | LP fees > spreads (expected) |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.3 Preflight Evidence | [OK] v1.0.3 | chain-aware leg2, gas_sanity, quoter_v2 |

> **NOTIONAL_DRIFT v2.2.3**: Added target_usd_notional=250 and tokens_usd_price to config.
> NOTIONAL_DRIFT filter in spreads excludes quotes with >50% drift from spread evaluation.
> data_run_rate improved from 0.465 to 0.725 after 60min warm-up.

## 7) Contract Checks (коротко)
status/reasons consistency: OK (no FAIL_* with PASS status)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp, code_identity, no SHA tracking)
runtime artifacts not committed: OK
dual cross-dex routes: IMPLEMENTED (_find_all_cross_dex_spreads)
pair diversity: RESOLVED (8 pairs >= 8 target)

## 8) Blockers / Root Cause Analysis

### v2.2.0 BUG FIX: Roundtrip Direction Was BACKWARDS

**Problem Found:** The roundtrip simulation was using DEXes in the WRONG order:
- **Old (broken):** Leg1 on buy_dex (cheap), Leg2 on sell_dex (expensive)  
  - Result: WETH → USDC @ $1846 (sell low) → USDC → WETH @ $1851 (buy high) = **LOSS**
- **Fixed (v2.2.0):** Leg1 on sell_dex (expensive), Leg2 on buy_dex (cheap)
  - Result: WETH → USDC @ $1851 (sell high) → USDC → WETH @ $1846 (buy low) = **PROFIT**

**Code Fix:** `engine/roundtrip.py` lines 348-358:
```python
# v2.2.0 FIX: Correct roundtrip direction
# - Leg1: sell on sell_dex (HIGHER price = get MORE quote tokens)
# - Leg2: buy on buy_dex (LOWER price = get MORE base tokens per quote)
leg2_callback = leg2_quote_callback_factory(buy_quote)  # was sell_quote
result = simulate_roundtrip(sell_quote, buy_quote, ...)  # swapped args
```

### v2.8.0 Observability Improvements

Code changes for better diagnostics:
- **slippage_source**: Now `sqrtPriceAfter` (was `ticks_heuristic`) - measured from sqrt_price_x96
- **USD fields**: gross_pnl_usd, gas_cost_usd, net_pnl_usd added to roundtrip
- **unique_pairs_considered**: shows pair diversity (=3 in validation run)
- **best-per-pair**: only evaluates 1 best opportunity per pair (WETH/USDT, WBTC/USDC, WETH/USDC)
- **sort by net_profit_usd**: best opportunities evaluated first

These changes improve observability but don't change the root cause (LP fees > spreads).

### ROOT CAUSE: LP Fees Exceed Spreads

After fixing the direction bug, roundtrip STILL shows negative profit. Root cause:

**LP Fee Math:**
- V3 Pool fee tier 3000 = 0.30% per swap
- Roundtrip incurs fee on BOTH legs: 2 × 0.30% = 0.60% = **60 bps**
- Typical spread observed: 25-35 bps
- Net after fees: 25 - 60 = **-35 bps** (LOSS)

**Verification:**
- WETH/USDC spread: 25.4 bps
- Roundtrip gross_pnl observed: -37.69 bps  
- Matches: 25 bps spread - 60 bps fees = -35 bps ± slippage ✓

**Profitability Threshold:**
```
MIN_PROFITABLE_SPREAD = 2 × pool_fee_bps + gas_bps + margin
For 0.30% pools: MIN = 60 + 5 + 5 = ~70 bps
For 0.05% pools: MIN = 10 + 5 + 5 = ~20 bps
```

### Original Root Causes (Still Valid):

1. **Insufficient Spread Magnitude**
   - Typical spread: ~22-35 bps
   - Minimum for profitability: ~70 bps on standard fee pools
   - **Root**: Need spreads 2x larger than observed

2. **Trade Size Too Small** (partially addressed)
   - Increased from $250 → $1000 in real_nonstop.yaml
   - Impact: Higher absolute profit per trade
   
3. **Market Efficiency (Arbitrum L2)**
   - Low gas makes arb competitive
   - MEV bots capture opportunities quickly

4. **Pool Fee Tier Selection**
   - Most pairs use 3000 fee tier (0.30%)
   - Could target 500 fee tier pools (0.05%) for lower cost
   - Need: 20 bps spread vs 70 bps

## 9) Solutions / Proposals (M4.2 Path Forward)

### CRITICAL: Target Low-Fee Pools (Highest Priority)

**Option A: Target 0.05% Fee Tier Pools (RECOMMENDED)**
- Change pool discovery to prioritize fee_tier=500 pools
- Profitability threshold drops from ~70 bps to ~20 bps
- Impact: Many more opportunities become viable
- Implementation: Modify pair configs to prefer fee_tier 500
- Evidence: WBTC/WETH already has 500 tier active → check if profitable

**Option B: Multi-Hop Routes via 0.01% Pools**
- WETH/USDC has 0.01% (100) tier pools with deep liquidity
- Roundtrip fee: 2 × 0.01% = 2 bps total
- 25 bps spread - 2 bps fee = +23 bps profit!
- Implementation: Add fee_tier 100 to config, verify pool liquidity
- Risk: Concentrated liquidity pools may have higher slippage

### Other Options (Lower Priority)

**Option C: Increase Trade Size** (already done: $1000)
- Change `paper_size_usd: 250` → `paper_size_usd: 1000`
- Impact: Higher absolute profit, better signal/noise
- Status: IMPLEMENTED in real_nonstop.yaml

**Option D: Add 3rd DEX (Camelot V3)**
- May have different liquidity profiles
- Implementation: ~2-3 days
- Impact: More routes, may find untapped spreads

**Option E: Real Execution Test (M4.3)**
- Skip waiting for sim-profitable roundtrip
- Execute 1 real tiny trade ($10) to prove execution path
- Risk: Lose ~$0.50 max
- Benefit: Proves execution layer works

**Recommended Path:**
1. **IMMEDIATE:** Enable 500 fee tier pools for all pairs
2. **IMMEDIATE:** Check if any 100 fee tier pools are available
3. **RUN:** 30min scan with low-fee pools
4. **IF STILL NO PROFIT:** Consider Option E (real execution test)

## 10) 2h Scan Summary (ci_m5_gate_20260224_164942)

**Scan Parameters:**
- Duration: 2 hours
- Config: config/real_minimal.yaml
- Cycles: 1 per run
- Sleep: 20s between runs
- Total runs: 200

**Results:**
- runs_in_window: 200
- agg_status: WARN_QUALITY
- agg_reasons: [FRAGILE_P90_ELEVATED, DIVERSITY_PAIRS_LOW]
- data_run_rate: 0.905
- total_net_usdc: $553.94 (rolling window)

**Signal Distribution:**
- signals_per_run: 3 (avg after min_spread_bps=20 filter)
- unique_pairs: 5 (ARB/WETH, WBTC/USDC, WBTC/WETH, WETH/USDC, WETH/USDT)
- unique_routes: 2 (uniswap_v3->sushiswap_v3, sushiswap_v3->uniswap_v3)
- unique_routes_cross_dex: 2
- note: updated with v3.2.7 ONLINE run

**Sample Signal (typical):**
- pair: WBTC/USDC
- route: uniswap_v3 -> sushiswap_v3
- spread_bps: ~25
- size_usd: $250
- est_gross_usdc: $0.79
- truth_net_usdc: $0.79 (after gas)
- confidence: low

**Roundtrip Status (v2.8.1 fix deployed):**
- profit_truth_source: ONE_LEG_DIAGNOSTIC
- roundtrip_enabled: true (simulated)
- best_net_pnl_bps: -36.53 (WBTC/USDC)
- note: roundtrip still < 0; slippage/impact (68-111 bps) eats edge

**Conclusion:**
Paper profit positive (~$2.8/run) on ONE_LEG. Roundtrip unprofitable (-36 bps) due to impact costs.
net_pnl_bps calculation now USD-canonical (decimals-safe fix deployed).
Real roundtrip profitability requires leg2 re-quote which is likely to reduce/eliminate profit due to execution costs.
See Section 8 for root cause analysis and Section 9 for solutions.

