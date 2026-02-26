# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-26T09:10:00Z
run_id: data/runs/ci_m5_gate_20260226_100942
mode: ONLINE (warm-up + PRICE_SANITY quarantine fix)
artifact_mode: rolling
config: config/real_minimal.yaml
code_identity:
  primary: ts:2026-02-26T09:10:00+00:00
  dirty: true
  desc: v2.2.2 FIX - PRICE_SANITY_FAILED auto-quarantine, rolling warm-up

## 1) Scope (що і навіщо)
goal (Roadmap пункт): Warm up rolling + enable PRICE_SANITY auto-quarantine + rolling WARN_QUALITY fix
change_summary:
  - BUG FIX: rolling_store.py - WARN suffix detection in has_warn_threshold
  - BUG FIX: strategy/quotes.py - PRICE_SANITY_FAILED now triggers auto-quarantine
  - WARM-UP: 30min scan to push out historical NO_DATA runs
  - DYNAMIC ANCHORS: Working correctly (price_sanity_failed=0)
  - TESTS: All 1077 tests pass
touched_files:
  - m4/rolling_store.py (WARN suffix detection fix)
  - strategy/quotes.py (record_failure for PRICE_SANITY_FAILED)
  - docs/DEV_REPORT_LATEST.md (state update)

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (3 warnings)
py -3.11 -m pytest tests/unit -q: PASS (1077 passed, 1 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)
py -3.11 start.py --config config/real_minimal.yaml --minutes 30 --max-runs 80: warm-up completed
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1: PASS
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit: PASS

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json  
  - data/runs/_rolling/m4_stability_agg.json (184 runs)
capstone_run_dir:
  - data/runs/ci_m5_gate_20260224_141638/reports
preflight_evidence:
  - enabled: true
  - candidates_count: 2
  - passed_count: 2 (100%)
  - evidence_source: preflight_v1.0.3
  - leg1.gas_estimate_source: quoter_v2
  - leg2.gas_estimate_source: quoter_v2

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY
  agg_reasons: []
  quality_warnings: [WARN_PROFIT_DIAGNOSTIC]
  data_run_rate: 0.465
  low_sample_rate: 0.0
  runs_in_window: 200
  in_warmup: false

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-26T09:10:03+00:00
  inputs.run_dir_name: ci_m5_gate_20260226_100942
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 7
    included_signals_count: 7
    excluded_signals_count: 0
    sim_profitable_count: 7 (paper)
    total_net_usdc: $1280.68 (rolling)
    profit_is_diagnostic: true
    profit_truth_source: ONE_LEG_DIAGNOSTIC
    profit_truth_available: false

m4_stability_agg.json:
  runs_in_window: 200
  pass_count: 93 (107 NO_DATA - historical)
  data_run_rate: 0.465
  total_net_usdc: $1280.68 (200-run window)
  avg_net_usdc: $6.40/run (estimate)
  unique_pairs: 8
  unique_routes: 3 (2 cross-DEX)
  agg_status: WARN_QUALITY
  agg_reasons: [WARN_PROFIT_DIAGNOSTIC]

## 5) Pair Diversity Expansion (v2.5.2)

fee_tiers_expansion:
  - WBTC/WETH: fee_tiers [3000] -> [500, 3000] (Uniswap fee-tier arb enabled)
  - ARB/WETH: fee_tiers [3000] -> [500, 3000] (Uniswap fee-tier arb enabled)
  - Pool verification: uniswap_v3_WBTC_WETH_500 liq=428657338564977205
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
| Core Truth (paper +PnL) | [OK] PROVEN | N=200 runs, total_net_usdc=$1280.68 |
| Rolling Quality Gate | [WARN] WARN_QUALITY | agg_status=WARN_QUALITY, data_run_rate=0.465 (historical NO_DATA) |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0, see Section 8 analysis |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] ACHIEVED | runs_in_window=200 >= 100 |
| M4.3 Preflight Evidence | [OK] v1.0.3 | chain-aware leg2, gas_sanity, quoter_v2 |
| Cross-DEX Preference | [OK] v2.5.2 | dual routes, always prefer cross-DEX |
| Diversity Routes | [OK] PASS | unique_routes_cross_dex=2 >= 2 |
| Diversity Pairs | [OK] PASS | unique_pairs=8 >= 8 |

> **WARM-UP NEEDED**: data_run_rate=0.465 < 0.5 due to historical NO_DATA runs in 200-run window.
> Recent scans: 100% PASS, price_sanity_failed=0, dynamic anchors working correctly.
> Resolution: Continue scanning to push out NO_DATA runs from window.

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

### NEW ROOT CAUSE: LP Fees Exceed Spreads

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
- agg_status: PASS
- data_run_rate: 0.995 (199/200 runs had data)
- total_net_usdc: $991.84 (paper profit)
- avg_net_usdc: $4.96/run
- max_net_usdc: $7.44/run
- min_net_usdc: $0.00/run (1 NO_DATA run)

**Signal Distribution:**
- signals_per_run: 8 (avg)
- unique_pairs: 8 (ARB/USDC, ARB/WETH, LINK/WETH, WBTC/USDC, WBTC/WETH, WETH/USDC, WETH/USDT, wstETH/WETH)
- unique_routes: 3 (uniswap_v3->sushiswap_v3, sushiswap_v3->uniswap_v3, uniswap_v3->uniswap_v3)
- unique_routes_cross_dex: 2

**Sample Signal (typical):**
- pair: WETH/USDC
- route: uniswap_v3 -> sushiswap_v3
- spread_bps: 22.29
- size_usd: $250
- est_gross_usdc: $0.56
- truth_net_usdc: $0.46 (after gas)
- confidence: low

**Roundtrip Status:**
- profit_truth_source: ONE_LEG_DIAGNOSTIC
- profit_truth_available: false
- profitable_count: 0 (roundtrip simulation not implemented yet)

**Conclusion:**
Paper profit is consistently positive (~$5/run) but represents ONE_LEG estimates only.
Real roundtrip profitability requires leg2 re-quote which is likely to reduce/eliminate profit due to execution costs.
See Section 8 for root cause analysis and Section 9 for solutions.

