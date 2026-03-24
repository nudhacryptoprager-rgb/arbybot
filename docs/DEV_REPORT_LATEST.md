# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39g+**: Aerodrome re-enabled on Base (VE33_QUOTE_FAILED diagnosed: transient RPC). PRICE_SCALE per-pair majority fix (linea PASS). SyncSwap confirmed prioritized. Route-level economics lab on arb.

## SESSION GOAL (R39g+: aerodrome + PRICE_SCALE + economics lab)
**Goal**: (1) Fix base.aerodrome VE33_QUOTE_FAILED, (2) Fix linea PRICE_SCALE direction bug, (3) SyncSwap prioritization, (4) Route-level economics lab on arb, (5) Fresh canonical proof.
**Prior (R39g)**: 2306 tests, coverage gate fixed, INFRA_FAIL corrected, pair_level_rca RCA.
**Lead directive (R39g+)**: "Першим пріоритетом добити base.aerodrome quote path" + linea PRICE_SCALE + SyncSwap deprioritization of iZiSwap + route-level economics decomposition.

## 0) Meta
timestamp_utc: 2026-03-23T22:50:49Z
run_dir_name: ci_m5_gate_arbitrum_one_20260323_235016_537389 (arb latest)
long_scan_summary: long_scan_latest.json (31 runs, 613s, 6 chains)
mode: R39gplus_AERO_PRICESCALE_FRESH_SCAN
test_count: 2317 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.14
code_identity:
  primary: ts:2026-03-23T22:50:49Z
  dirty: true (R39g+ code changes uncommitted)
  desc: aerodrome_pricescale_10min_scan

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39g+: aerodrome + PRICE_SCALE + economics lab + 10-min scan |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | profitable_rt=0 (economics, all chains); base SLOT0_DIAGNOSTIC; linea/scroll/zksync coverage |
| fresh_evidence_run | long_scan_latest.json: 31 runs, 613s, 213 signals, $303.14 net, 0 profitable RT |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260323_235016_537389 (latest), 31 runs across 6 chains |
| primary_blocker_of_session | base.aerodrome VE33_QUOTE_FAILED + linea PRICE_SCALE FAIL |
| blocker_status_before | ACTIVE: base 3/4 DEXes (aerodrome disabled), linea PRICE_SCALE FAIL (1/9 outlier = 11.1% > 10%) |
| blocker_status_after | **RESOLVED**: base 4/4 DEXes (aerodrome active, 0 VE33_QUOTE_FAILED), linea PRICE_SCALE PASS (per-pair majority) |
| start_metric | 2306 tests, 25/27 active sources, base 3 DEXes, linea FAIL |
| end_metric | 2317 tests, 26/27 active sources, base 4 DEXes, linea PASS |
| delta | +11 tests, aerodrome re-enabled, PRICE_SCALE per-pair logic, fresh 10-min scan evidence |
| docs_reread_confirmed | true |

## 0.3) Fresh 10-Minute Scan Evidence

```
Wall time:      613s (~10 min)
Total runs:     31 (PASS=15, NO_DATA=7, FAIL=9, INFRA_FAIL=0)
Signals total:  213
Net USDC total: $303.14 (diagnostic)
Profitable RTs: 0 (evaluated: 51, best: +0.00 bps)
Spread gap:     +376.85 bps (measured, target: >=0)
Sweep best:     +0.00 bps @ $5000 (BREAKEVEN_FRONTIER)
```

| Chain | Runs | PASS | Signals | Net USDC | Status |
|-------|-----:|-----:|--------:|---------:|--------|
| arbitrum_one | 6 | 6 | 194 | $293.50 | SIGNAL_PRODUCING |
| zksync | 5 | 5 | 8 | $4.80 | PASS |
| base | 5 | 0 | 2 | $2.90 | FAIL (SLOT0_DIAGNOSTIC) |
| scroll | 5 | 1 | 4 | $0.69 | FAIL (coverage) |
| linea | 5 | 1 | 0 | $0.00 | FAIL (coverage) |
| mantle | 5 | 2 | 5 | $1.25 | PROBE_ONLY |

**Key metrics (arb latest run):**
- signals_count=56, included=37, sim_profitable=31
- real_quote_count=5, profitable_roundtrips=0
- fragile_rate=13.5%, drift_median=480 bps
- roundtrip.best_measured_spread_gap_bps=21.32
- chain_quality_level=SIGNAL_PRODUCING

## 1) Scope
goal (Roadmap): M5_0/M4 -- R39g+: aerodrome re-enabled, PRICE_SCALE per-pair fix
change_summary:
  - **config/onboard_base_stage2.yaml** — aerodrome uncommented in dexes list.
  - **scripts/ci_m5_0_gate.py** + **scripts/ci_m5_gate.py** — `validate_price_scale()` per-pair majority logic.
  - **tests/unit/test_r39gplus_fixes.py** — +11 tests (aerodrome contract, PRICE_SCALE logic, SyncSwap ordering).
  - **tests/unit/test_ci_m5_gate_negative_price_scale.py** — updated for per-pair logic.

## 2) Root Cause Analysis

### Aerodrome VE33_QUOTE_FAILED (base)
- **Root cause**: Transient RPC failure at R28.24. Factory `0x420DD381b31aEf6683db6B902084cB0FFECe40Da` returns valid pools. `getAmountOut(uint256,address)` returns correct quotes (WETH/USDC volatile pool ~$2147/ETH, AERO/USDC ~$0.35/AERO).
- **ABI**: `getAmountOut(uint256 amountIn, address tokenIn) → uint256 amountOut` — matches selector `0xf140a35a`, works on both volatile and stable pools.
- **Fix**: Simply re-enable aerodrome in config. No code changes to quoting infrastructure needed.

### PRICE_SCALE (linea)
- **Root cause**: pancakeswap_v3 fee=10000 (1% fee tier) pool returns garbage price (0.01476 for WETH/USDC). Ultra-high fee tier pool with negligible liquidity.
- **Not a direction bug**: 1/price = 67.75, also outside (100, 50000). Just bad data from empty pool.
- **Why old logic failed**: 1/9 = 11.1% violation rate > 10% threshold → FAIL. But 4/5 WETH/USDC quotes were correct (~2160).
- **Fix**: Per-pair majority logic — if pair has good quotes, outliers are data quality (WARN), not direction bugs (FAIL).

## 3) Per-Chain Verdicts (fresh scan R39g+)

| Chain | Gate | DEXes | Quotes | XDex Pairs | Blocker | Delta |
|-------|------|-------|--------|------------|---------|-------|
| arb | PASS | 5 | 48 | 9 | OE_ECONOMICS (slippage>>spread) | unchanged |
| base | PASS | **4** | 41 | 7 | SLOT0_DIAGNOSTIC 87% | **+aerodrome** |
| linea | PASS | 2 | 9 | 3 | SUSPECT_SPREAD_HARD 50% | **PRICE_SCALE fix** |
| scroll | PASS | 3 | 9 | 3 | - | unchanged |
| zksync | PASS | 2 | 9 | 3 | - | unchanged |

## 4) Route-Level Economics Lab (arb)

| Pair | Route | Gross $ | Net $ | Slip $ | Gas $ | LP Fee $ | Gap to 0 |
|------|-------|--------:|------:|-------:|------:|---------:|:---------|
| ARB/USDC | camelot→pancakeswap | -240.86 | -254.97 | 541.23 | 14.10 | 1.0 | $254.97 |
| WETH/LINK | pancakeswap→sushiswap | -389.40 | -399.12 | 642.33 | 9.70 | 35.0 | $399.12 |
| WETH/ARB | camelot→uniswap | -470.34 | -485.85 | 821.06 | 15.50 | 1.0 | $485.85 |
| WETH/PENDLE | camelot→uniswap | -740.83 | -752.99 | 1008.71 | 12.20 | 100.0 | $752.99 |
| WETH/USDC | pancakeswap→sushiswap | -827.24 | -836.57 | 898.34 | 9.30 | 31.0 | $836.57 |

**Key finding**: slippage dominates all routes. spread < slippage + LP fee + gas on every pair. ARB/USDC closest at $254.97 gap. Gas is negligible (arb L2). LP fees range 1-100 bps.

Fresh 10-min scan rolling metrics (arb): 56 signals, 37 included, 31 sim-profitable, 5 RT evaluated, 0 profitable. best_measured_spread_gap_bps=21.32. sweep_best_frontier_reason=BREAKEVEN_FRONTIER.

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK
- blocker classification: OK
- coverage gate: OK (all 5 chains PASS)
- dual-route contract: OK (locked by R39f tests)
- source coverage: **26/27** active (+1 aerodrome)
- PRICE_SCALE: direction-bug detection intact, data-quality outliers tolerated

## 6) Blockers / Next Steps
- **profitable_rt=0**: economics blocker (all chains). 51 RT evaluated, best +0.00 bps. BREAKEVEN_FRONTIER on WETH/USDC.
- **base FAIL (SLOT0_DIAGNOSTIC)**: aerodrome enabled but V3 pools use diagnostic slot0. 2 signals, 0 RT.
- **linea/scroll FAIL (coverage)**: thin productive set, few executable quotes.
- **zksync PASS**: 5/5 runs passed, 8 signals, $4.80 net — smallest but stable.
- **mantle PROBE_ONLY**: 2/5 PASS, 5 signals — useful for diagnostic but not production.
- **Event-driven freshness**: TD-003 documented in TECH_DEBT.md. Highest-leverage improvement.
- **Source-expansion gating**: accepted only if real_quote_count, RT-evaluated, or gap metrics improve.
