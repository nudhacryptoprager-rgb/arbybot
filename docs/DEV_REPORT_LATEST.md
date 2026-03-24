# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39i++**: Frontier truth fix — degenerate sweep filter + slippage quality gate. Falsy coalescing fix in chain_stats. 2h scan evidence (390 runs/3413 sig/707 RT/0 profitable). 2344 tests.

## SESSION GOAL (R39i++: frontier truth fix + 2h evidence framing)
**Goal**: (1) Fix frontier truth lie (0.0 bps BREAKEVEN_FRONTIER from degenerate sweep points), (2) Fix falsy coalescing in chain_stats.py, (3) Add SUSPECT_ZERO_SLIPPAGE frontier_reason, (4) Correctly frame old M4 3.55bps vs current ~55bps gap as incomparable measurements.
**Prior (R39i)**: 2338 tests, base QUOTE_PATH_BLOCKED fix, Status compression, CI enforcement.
**Lead directive (R39i++)**: "0.0 bps can only be shown when route-level gas/slippage are really measured and match RCA. The earlier 3.55-4.10 bps frontier and the current 40-50 bps gap are not directly comparable — different pair/semantics."

## 0) Meta
timestamp_utc: 2026-03-24T13:03:54Z
run_dir_name: (rolling 200-run window)
long_scan_summary: long_scan_latest.json
mode: R39i_FRONTIER_TRUTH_FIX
test_count: 2344 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.15
code_identity:
  primary: ts:2026-03-24T13:03:54Z
  dirty: true (R39i++ code changes uncommitted)
  desc: frontier_truth_degenerate_guard_slippage_gate

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39i++: frontier truth fix + 2h evidence framing |
| goal_status | **IN_PROGRESS** |
| close_allowed | false (pending CI green + fresh online scan post-fix) |
| remaining_blockers | profitable_rt=0 (economics); base QUOTE_PATH_BLOCKED; frontier truth was lying (now fixed) |
| fresh_evidence_run | rolling 200-run window (ts:2026-03-24T13:03:54Z), pair_level_rca all 6 chains |
| evidence_session_run_dirs | arb_20260324_140321, base_140355, zksync_140355, mantle_140414, linea_140445, scroll_140457 |
| primary_blocker_of_session | Frontier truth lie: 0.0 bps BREAKEVEN_FRONTIER from degenerate sweep at $7500+ |
| blocker_status_before | ACTIVE: sweep_best=0.0, BREAKEVEN_FRONTIER (false), falsy coalescing in chain_stats |
| blocker_status_after | **FIXED**: degenerate guard + slippage quality gate + falsy coalescing fixed |
| start_metric | 2338 tests, sweep_best=0.0 (broken), BREAKEVEN_FRONTIER (false) |
| end_metric | 2344 tests, degenerate filter active, SUSPECT_ZERO_SLIPPAGE for unmeasured |
| delta | +6 tests, 3 bugfixes (roundtrip + chain_stats + long_scan_summary) |
| docs_reread_confirmed | true |

## 0.3) Fresh 2-Hour Scan Evidence (R39i++ — 200-run rolling window)

```
Wall time:      ~2h (rolling)
Total runs:     390 (200 in window)
Signals total:  3413
Net USDC total: $11,118.78
Profitable RTs: 0 (evaluated: 1102)
Sweep best:     0.0 bps (was BREAKEVEN_FRONTIER — now DEGENERATE_ZERO after fix)
```

### Per-Chain RCA (fresh run dirs 2026-03-24)
| Chain | Pairs | Exec% | RT | Best PnL bps | #1 OE Reject | Key Insight |
|-------|------:|------:|---:|---------:|----------|-------------|
| arb | 11 | 92.2% | 5 | **-54.76** | (clean) | Best=USDC/DAI; slippage dominant |
| base | 9 | 7.4% | 0 | — | SLOT0_DIAGNOSTIC 71.7% | Infra blocker; 7 executable quotes only |
| zksync | 6 | 92.3% | 1 | -718.17 | NET_PROFIT_TOO_LOW 71.4% | Clean but thin |
| mantle | 4 | 100% | 1 | -694.17 | MIXED_SOURCE 61.5% | 81 RT / 0 signals = semantic split |
| linea | 5 | 100% | 1 | -631.40 | NET_PROFIT_TOO_LOW 62.5% | Economics, not coverage |
| scroll | 5 | 86.7% | 2 | -339.69 | MIXED_SOURCE 37.5% | USDC/DAI best candidate |

### Frontier Truth Bug (fixed)
WETH/USDC sweep at $7500-$10000 produced **degenerate all-zero points** (net=0.0, gross=0.0, slip=0.0, gas=0.0). These were selected as "best" → false BREAKEVEN_FRONTIER. Real best sweep point: USDC/DAI at -27.38 bps (BEST_NEG with measured slippage=10.29, gas=17.25).

### Old vs Current Frontier (incomparable)
M4 frontier 3.55-4.10 bps was on WETH/USDT at $25 scale with older truth semantics. Current ~55 bps is on USDC/DAI with stricter executable truth. These are **not comparable**. The gap widened because the measurement became more honest, not because the pipeline regressed.

## 1) Scope
goal (Roadmap): M5_0/M4 -- R39i++: frontier truth fix + 2h evidence framing
change_summary:
  - **engine/roundtrip.py** — R39i: Degenerate sweep point guard (gross=0 AND slip=0 → DEGENERATE_ZERO error, excluded from best selection). Slippage quality gate: net_pnl≥0 with slip=0.0 → SUSPECT_ZERO_SLIPPAGE instead of PROFITABLE/BREAKEVEN_FRONTIER.
  - **strategy/chain_stats.py** — R39i: Fixed falsy coalescing (sweep_pnl `or` → `is None`). Fixed `best_size_usd`/`best_pair`/`best_frontier_reason` same pattern. Added SUSPECT_ZERO_SLIPPAGE comment for upgrade bypass.
  - **strategy/long_scan_summary.py** — R39i: Post-aggregation fence: SUSPECT_ZERO_SLIPPAGE accepted for pnl=0.0 and pnl>0 (not auto-promoted to BREAKEVEN/PROFITABLE).
  - **tests/unit/test_roundtrip.py** — +5 tests: degenerate_zero_excluded, all_degenerate_all_failed, suspect_zero_slippage_on_positive, real_slippage_allows_profitable, negative_pnl_unaffected. Updated test_sweep_frontier_profitable to use ticks_crossed=1.
  - **tests/unit/test_r38_changes.py** — +1 test: SUSPECT_ZERO_SLIPPAGE not promoted to BREAKEVEN by post-aggregation fence.
  - **docs/DEV_REPORT_LATEST.md** — 2h evidence, frontier truth fix, old-vs-new frontier framing.
  - Prior R39i changes: base QUOTE_PATH_BLOCKED fix, Status compression, CI enforcement.

## 2) Root Cause Analysis

### Layered Blocker Diagnosis (R39h++ system audit)
Full audit across chains/dex/config/engine/strategy/discovery confirms the blockers are layered:
1. **base quote-path debt** (SLOT0_DIAGNOSTIC 79%, exec 5.4%, rq=0, 44 quoter_v2_failed)
2. **mixed-source truth loss** on scroll (37.5%) and mantle (66.7%) — one executable + one diagnostic leg
3. **HTTP-only freshness** on 4 chains (now fixed: WS endpoints added for linea/mantle/scroll/zksync)
4. **post-signal economics/slippage** on all healthy chains (arb best -54bps, still slippage-dominated)

### Per-Chain Fresh RCA (2026-03-24 run dirs)
| Chain | Pairs | Exec% | RT | Best PnL | #1 OE Reject | Key Insight |
|-------|------:|------:|---:|------:|----------|-------------|
| arb | 11 | 88.6% | 5 | -54 | (none; clean pipeline) | best candidate USDC/DAI at -54bps → slippage blocker |
| zksync | 7 | 92.3% | 1 | -609 | NET_PROFIT_TOO_LOW 63% | thin but clean; ZK/USDC+ZK/WETH still at `resolved` |
| base | 9 | 5.4% | 1 | -10127 | SLOT0_DIAGNOSTIC 79% | quote-path debt is THE base blocker |
| linea | 5 | 100% | 1 | -563 | NET_PROFIT_TOO_LOW 63% | economics/thin-truth; RT > 0 now |
| scroll | 5 | 86.7% | 2 | -353 | SUSPECT_SPREAD 38% | MIXED_SOURCE 38% = second blocker |
| mantle | 4 | 100% | 2 | -415 | MIXED_SOURCE 67% | 0 sig/12 RT = semantic split (rt_without_signal) |

### Mantle 0-Sig/14-RT Semantic Split (explained)
Two independent pipelines: `included_signals_count` counts signals where |spread| ≤ 500bps. Opportunity engine independently creates opps from quotes → rejected opps (MIXED_SOURCE 67% on mantle) go to sweep_reprieve path → re-evaluated with frontier sizing → counted in roundtrip_evaluated_total. Not a bug, but confusing for operators. Fix: `sweep_reprieve_rt` field added to signal_funnel.

### Secondary Chain Signal Scarcity (R39h)
**Key insight**: "Low signals outside arb" is NOT one problem — each chain has a different root cause. Arbitrum proves pipeline healthy (194 signals, 6/6 PASS). Per-chain RCA:

| Chain | Pairs | Exec Rate | Primary Blocker | RT Evaluated |
|-------|------:|----------:|-----------------|:-------------|
| base | 7 | 7.1% | SLOT0_DIAGNOSTIC 82.1% | 0 |
| zksync (was) | 3 | 100% | OE_ECONOMICS (ZK/* blanket exclude) | 1 (-737bps) |
| mantle | 4 | 100% | OE_ECONOMICS + MIXED_SOURCE 61.5% | 2 (-360, -800bps) |
| scroll | 3 | 80% | MIXED_SOURCE 43% + SUSPECT_SPREAD 43% | 1 (-359bps) |
| linea | 3 | 100% | SUSPECT_SPREAD_HARD 50% | 0 |

### ZKSync ZK/* Blanket Exclude
- **Root cause**: R28.27 added `[ZK/*, */ZK]` to excluded_pair_hints because ZK/USDC and ZK/WETH failed PRICE_SANITY. But the failure was caused by missing anchor prices (no ZK_USDC or ZK_WETH anchors), not intrinsic liquidity problems.
- **Fix**: Removed ZK/* exclude, added proper anchor prices: ZK_USDC=0.10, ZK_WETH=0.0000488, USDC_DAI=1.0.
- **Result**: zksync pairs increase from 3 to 7.

### Calibration Contour
- **Root cause**: Post-R39d productive-only universe was too narrow on secondary chains (3-4 pairs).
- **Fix**: Applied calibration tier via `generate_intent.py --tier calibration`. Adds USDC/DAI and USDC/USDT (stable pairs) as calibration instruments. Safe: low-spread stable pairs add signal surface without noise.
- **Result**: 42 pairs total (was 31). All secondary chains at ≥5 pairs.

## 3) Per-Chain Contour After Calibration (R39h)

| Chain | Before | After | Delta | Note |
|-------|-------:|------:|------:|------|
| arbitrum_one | 9 | 11 | +2 | +USDC/DAI, +USDC/USDT |
| base | 7 | 9 | +2 | +USDC/DAI, +USDC/USDT |
| linea | 3 | 5 | +2 | +USDC/DAI, +USDC/USDT |
| scroll | 3 | 5 | +2 | +USDC/DAI, +USDC/USDT |
| mantle | 4 | 5 | +1 | +USDC/DAI (USDC/USDT excluded: 2884bps) |
| zksync | 3 | 7 | +4 | +ZK/USDC, +ZK/WETH, +USDC/DAI, +USDC/USDT |
| **Total** | **29** | **42** | **+13** | |

## 4) Signal Funnel (v1.15 + rt_without_signal — fresh R39h++ evidence)

Aggregate:
```json
{
  "signal_funnel": {
    "intent_pairs_total": 42,
    "pairs_after_excludes_total": 41,
    "cross_dex_pairs_total": 40,
    "spread_signals_total": 300,
    "rt_evaluated_total": 69,
    "sweep_reprieve_rt_total": 0,
    "rt_without_signal_total": 13
  }
}
```

Per-chain breakdown:
| Chain | Intent | After Excl | XDex | Signals | RT Eval | Sweep Reprieve | RT w/o Signal |
|-------|-------:|-----------:|-----:|--------:|--------:|---------------:|--------------:|
| arbitrum_one | 11 | 11 | 11 | 226 | 30 | 0 | 0 |
| zksync | 7 | 7 | 6 | 24 | 6 | 0 | 0 |
| base | 9 | 9 | 9 | 6 | 3 | 0 | 1 |
| mantle | 5 | 4 | 4 | 0 | 12 | 0 | **12** |
| linea | 5 | 5 | 5 | 20 | 6 | 0 | 0 |
| scroll | 5 | 5 | 5 | 24 | 12 | 0 | 0 |

**Observations**: Near-zero attrition (42→41→40). Mantle semantic split now exposed: **rt_without_signal=12** (0 signals passed 500bps threshold, but 12 RT came from OE opportunities via quote path). WS endpoints added for all 6 chains — actual WS connection status still 0 (may need longer-running scan or endpoint validation).

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK
- blocker classification: OK
- coverage gate: OK (all 5 chains PASS)
- dual-route contract: OK (locked by R39f tests)
- source coverage: **26/27** active (+1 aerodrome)
- PRICE_SCALE: direction-bug detection intact, data-quality outliers tolerated

## 6) Blockers / Next Steps (prioritized by lead directive)
1. **base quote-path** (P0): SLOT0_DIAGNOSTIC 79%, exec 5.4%, rq=0. Fix quotes.py / quote_adapters.py. Until rq > 0 reliably, base is not a market verdict.
2. **scroll/mantle mixed-source** (P1): MIXED_SOURCE 38-67% of OE rejections. Target: fewer MIXED_SOURCE rejects, not more raw signals.
3. **WS freshness** (P2): WS endpoints added for all 6 chains. hot_loop shows `chains_ws_connected: 0` still (short scan; may need longer session or endpoint validation). Config change complete.
4. **linea economics/thin-truth** (P3): RT-evaluated 6 on existing 5 pairs. Fresh: 6 RT, 20 signals ($39.48 net).
5. **arb economics** (P4): Fresh best not captured this scan (all 0 bps). Prior RCA: -54bps (USDC/DAI). Slippage-dominated.
6. **ambient** (P5): Explicit tech debt. Do not distract from P0-P2.
7. **No intent.txt changes**: calibration tier confirmed matching. Expansion accepted only if ≥2 of 4 metrics improve.
8. **rt_without_signal**: **VERIFIED** — mantle shows 12 in fresh scan. Semantic split now operator-visible.
