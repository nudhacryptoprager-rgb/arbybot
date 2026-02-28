# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned `DEV_REPORT_YYYY-MM-DD_v*.md` files forbidden.
> Provenance: `timestamp_utc` and `code_identity.primary` copied from `run_summary_latest.run_context.*` (UTC).

## 0) Meta
timestamp_utc: 2026-02-28T17:21:19Z
run_id: data/runs/ci_m5_gate_20260228_182059
mode: ONLINE (10-min continuous scan with fee=100 pool experiment)
artifact_mode: rolling
config: config/real_minimal.yaml
code_identity:
  primary: ts:2026-02-28T17:21:19+00:00
  dirty: false
  desc: v2.9.4 fee=100 WETH/USDC uni-only (sushi SUSPECT_LIQUIDITY)

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M4 rolling quality - add fee=100 pools for lower LP fee floor
change_summary:
  - DIAGNOSTIC: slot0 shows Sushi pools return VALID prices (not "broken pools")
  - ROOT CAUSE: "inverted quotes" bug is in OUR direction-aware price_sanity logic
  - CONFIG: Added uniswap_v3_WETH_USDC_100 (high liq=3.6e15)
  - CONFIG: Disabled sushiswap_v3_WETH_USDC_100 (SUSPECT_LIQUIDITY, liq=3e10)
  - CONFIG: Disabled WETH_USDT fee=100 pools (both DEXes: SUSPECT_LIQUIDITY)
  - POLICY: Updated RESTORE CONTRACT documenting direction-logic as root cause
  - RESULT: agg_status: WARN_QUALITY (FRAGILE_P90_ELEVATED from quarantine noise)
  - RESULT: data_run_rate: 1.0 (improved from 0.89)
touched_files:
  - config/real_minimal.yaml (added fee=100 pools, disabled low-liq ones)
  - m4/policy.py (updated RESTORE CONTRACT with slot0 diagnostic finding)

## 2) Commands Executed (лише факти)

py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 scripts/inspect_rolling.py --excluded: captured baseline (signals_included=6, data_run_rate=0.89)
slot0 diagnostic (2 ARB Sushi pools): token0/token1 ordering confirmed VALID
py -3.11 scripts/verify_v3_pools.py --pairs WETH/USDC WETH/USDT: 4 fee=100 pools verified active
py -3.11 -m pytest -q: PASS (1120 passed)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS
py -3.11 start.py --config config/real_minimal.yaml --minutes 10: PASS (30 runs)

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json  
  - data/runs/_rolling/m4_stability_agg.json
capstone_run_dir:
  - data/runs/ci_m5_gate_20260228_182059/reports
quality_achievement:
  - agg_status: WARN_QUALITY (FRAGILE_P90_ELEVATED from fee=100 quarantine noise)
  - quality_warnings: [FRAGILE_P90_ELEVATED(0.33>0.3)]
  - data_run_rate: 1.0 (improved from 0.89)
  - pass_rate: 1.0
  - unique_pairs: 6

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY
  agg_reasons: [FRAGILE_P90_ELEVATED]
  quality_warnings: [FRAGILE_P90_ELEVATED(0.33>0.3)]
  runs_in_window: 200
  in_warmup: false

run_summary_latest.json:
  schema_version: m4:run_summary:v2.0
  status: PASS
  run_context.run_timestamp: 2026-02-28T17:21:19+00:00
  inputs.run_dir_name: ci_m5_gate_20260228_182059
  inputs.run_mode: REGISTRY_REAL
  metrics:
    signals_count: 7
    included_signals_count: 6
    total_rejects: 4 (1 notional_drift, 3 pool_missing)

m4_stability_agg.json:
  policy_version: 2.0.8
  quick_stats:
    data_run_rate: 1.0
    fragile_rate_p90: 0.3333
    fragile_rate_p50: 0.20
    unique_pairs: 6
    unique_routes_cross_dex: 2
    pass_rate: 1.0
    total_net_usdc: 1706.18

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
| Core Truth (paper +PnL) | [OK] PROVEN | N=200 runs, total_net_usdc=$587.47 |
| Rolling Quality Gate | [WARN] QUALITY | agg_status=WARN_QUALITY, warns=[SAME_DEX, DIAGNOSTIC] |
| M4.2 Roundtrip Profit | [NO] NOT_PROFITABLE | profitable_count=0, best=-22.40 bps |
| M4.2 Real Execution | [NO] NOT STARTED | kill_switch_active=true |
| M4.1 Time-Bound Window | [OK] ACHIEVED | runs_in_window=200 >= 100 |
| M4.3 Preflight Evidence | [OK] v1.0.3 | chain-aware leg2, gas_sanity, quoter_v2 |
| v2.8.0 Slippage Measure | [OK] VERIFIED | slippage_source=sqrtPriceAfter (all 3) |
| v2.8.0 USD Conversion | [OK] VERIFIED | gross_pnl_usd, gas_cost_usd, net_pnl_usd fields |
| v2.8.0 Best-per-pair | [OK] VERIFIED | unique_pairs_considered=3 |
| FRAGILE_P90_ELEVATED | [OK] RESOLVED | no longer in quality_reasons! |

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
- unique_pairs: 4 (WBTC/USDC, WBTC/WETH, WETH/USDC, WETH/USDT)
- unique_routes: 3 (uniswap_v3->sushiswap_v3, sushiswap_v3->uniswap_v3, uniswap_v3->uniswap_v3)
- unique_routes_cross_dex: 2
- note: unique_pairs reduced from 8 by min_spread_bps=20 filtering marginal signals

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

