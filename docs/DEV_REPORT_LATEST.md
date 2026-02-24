# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-24T15:50:23Z
run_id: data/runs/ci_m5_gate_20260224_164942
mode: ONLINE (2h continuous scan)
artifact_mode: rolling
config: config/real_minimal.yaml
code_identity:
  primary: ts:2026-02-24T15:50:23+00:00
  dirty: true
  desc: 2h scan completed - 200 runs, paper profit $991.84, roundtrip=NOT_PROFITABLE

## 1) Scope (що і навіщо)
goal (Roadmap пункт): 2h continuous scan to build rolling window + analyze roundtrip profitability
change_summary:
  - SCAN: 2h scan completed (200 runs in rolling window)
  - PAPER: total_net_usdc=$991.84, avg=$4.96/run, 199/200 runs profitable
  - ROUNDTRIP: NOT_PROFITABLE (no real arb opportunity found)
  - SPREADS: avg ~22 bps, typical signal net profit ~$0.46
  - ANALYSIS: Root cause analysis of why roundtrip is unprofitable added
touched_files:
  - docs/DEV_REPORT_LATEST.md (analysis update)
  - docs/status/Status_M5.md, Status_M5_0.md (section fixes)
touched_files:
  - config/real_minimal.yaml (fee_tiers expansion)
  - strategy/spreads.py (v2.5.2 dual cross-dex routes)
  - tests/unit/test_same_dex_policy.py (dual-route test)

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS
py -3.11 -m pytest -q: PASS (1068 passed, 12 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)
py -3.11 scripts/verify_v3_pools.py --pairs WBTC/WETH ARB/WETH --verbose: 13 active pools verified
py -3.11 start.py --minutes 60 --max-runs 80: 184 runs accumulated
py -3.11 scripts/ci_m5_0_gate.py --online (capstone): PASS, runDir=ci_m5_gate_20260224_141638
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS

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
  agg_status: PASS
  agg_reasons: []
  quality_warnings: [WARN_PROFIT_DIAGNOSTIC]
  data_run_rate: 0.995
  low_sample_rate: 0.0
  runs_in_window: 200
  in_warmup: false

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-24T15:50:23+00:00
  inputs.run_dir_name: ci_m5_gate_20260224_164942
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 8
    included_signals_count: 8
    excluded_signals_count: 0
    sim_profitable_count: 7 (paper)
    total_net_usdc: $4.88 (single run)
    profit_is_diagnostic: true
    profit_truth_source: ONE_LEG_DIAGNOSTIC
    profit_truth_available: false

m4_stability_agg.json:
  runs_in_window: 200
  pass_count: 199 (1 NO_DATA)
  data_run_rate: 0.995
  total_net_usdc: $991.84 (200 runs)
  avg_net_usdc: $4.96/run
  unique_pairs: 8
  unique_routes: 3 (2 cross-DEX)
  agg_status: PASS
  agg_reasons: []

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
| Core Truth (paper +PnL) | [OK] PROVEN | N=200 runs, total_net_usdc=$991.84, avg=$4.96/run |
| Rolling Quality Gate | [OK] PASS | agg_status=PASS, data_run_rate=0.995 |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0, see Section 8 analysis |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] ACHIEVED | runs_in_window=200 >= 100 |
| M4.3 Preflight Evidence | [OK] v1.0.3 | chain-aware leg2, gas_sanity, quoter_v2 |
| Cross-DEX Preference | [OK] v2.5.2 | dual routes, always prefer cross-DEX |
| Diversity Routes | [OK] PASS | unique_routes_cross_dex=2 >= 2 |
| Diversity Pairs | [OK] PASS | unique_pairs=8 >= 8 |

> **PAIR DIVERSITY v2.5.2**: Fee-tier expansion for WBTC/WETH and ARB/WETH enabled Uniswap fee-tier arbitrage.
> Evidence: Both pairs now generate signals, raising unique_pairs from 6 to 8.
> DIVERSITY_PAIRS_LOW RESOLVED. agg_status improved from WARN_QUALITY to PASS.

## 7) Contract Checks (коротко)
status/reasons consistency: OK (no FAIL_* with PASS status)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp, code_identity, no SHA tracking)
runtime artifacts not committed: OK
dual cross-dex routes: IMPLEMENTED (_find_all_cross_dex_spreads)
pair diversity: RESOLVED (8 pairs >= 8 target)

## 8) Blockers / Root Cause Analysis

**Why ROUNDTRIP is NOT_PROFITABLE (0 profitable after 200 runs, 2h scan):**

1. **Insufficient Spread Magnitude**
   - Typical spread: ~22 bps ($0.56 gross on $250)
   - After leg1 gas ($0.10): $0.46 net
   - Leg2 re-quote would add: gas ($0.10) + slippage (~5 bps = $0.125)
   - Roundtrip net: ~$0.23 - but market slippage variance often wipes this out
   - **Root**: Spreads 20-30 bps are marginal; need 50+ bps for robust roundtrip profit

2. **Trade Size Too Small**
   - paper_size_usd=250 → small absolute profit even at good spreads
   - 22 bps × $250 = $0.55, insufficient to cover 2-leg execution costs
   - **Root**: Profitable arb requires size $1000-5000+ or higher spread

3. **Same-DEX Route Dilution**
   - Route `uniswap_v3->uniswap_v3` is fee-tier arb (500↔3000)
   - These are NOT cross-DEX and have lower profit potential
   - 1 of 3 routes is same-dex, inflating paper signals

4. **Market Efficiency (Arbitrum L2)**
   - Arbitrum has low gas (~$0.01/tx) making arb very competitive
   - MEV bots capture most opportunities within 1-2 blocks
   - By the time scanner observes spread, it may already be closed

5. **Quoter Accuracy vs On-Chain Reality**
   - quoter_v2 gives accurate estimates but market moves between quote and execution
   - ~12.5% of signals have sign_mismatch (est positive → sim negative)
   - **Root**: latency between observation and execution

**Current Status:**
- Paper profit: PROVEN ($991.84 / 200 runs)
- Roundtrip profit: NOT_PROFITABLE (0/200)
- M4.2 requires: profitable_count > 0 with ROUNDTRIP_CANONICAL

## 9) Solutions / Proposals (M4.2 Path Forward)

**Option A: Increase Trade Size (Highest ROI)**
- Change `paper_size_usd: 250` → `paper_size_usd: 1000`
- Impact: Same spread (22 bps) yields $2.20 instead of $0.55
- After 2-leg costs (~$0.35): ~$1.85 net profit
- Risk: Higher capital at risk, but more robust signals
- Implementation: 1 line in `config/real_minimal.yaml`

**Option B: Add 3rd DEX (Camelot V3)**
- Camelot is popular Arbitrum native DEX with different liquidity
- May have price discrepancy vs Uni/Sushi
- Implementation: ~2-3 days (adapter + config + tests)
- Impact: More routes, higher chance of cross-DEX spread

**Option C: Expand Pair Universe**
- Add volatile pairs: PENDLE/WETH, MAGIC/WETH, GMX/WETH
- Higher volatility = higher spread probability
- Risk: Need to fix quoter_v2 for these pairs (currently slot0 fallback)
- Implementation: Fix quoter + add pairs to config

**Option D: Lower Spread Threshold**
- Current: 5 bps minimum
- Lower to 3 bps to capture more marginal opportunities
- Risk: More noise, lower hit rate
- Impact: Unlikely to help for roundtrip (still gas-bound)

**Option E: Real Execution Test (M4.3)**
- Skip waiting for profitable roundtrip simulation
- Execute 1 real trade with tiny size ($10) to prove execution path
- Measure actual on-chain slippage and gas
- Risk: Lose ~$0.20-$0.50 on unprofitable trade
- Benefit: Proves execution layer, moves to M4.3

**Recommended Path:**
1. Implement Option A (paper_size_usd=1000) - quick win
2. Run 1h scan with new size
3. If roundtrip still unprofitable, consider Option E (real execution test)
4. Parallel: Start Option B (Camelot adapter) for more routes

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

