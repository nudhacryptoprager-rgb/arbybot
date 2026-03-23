# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-23 (R35 — **User-visible stream fix + evidence discipline.** R35 follow-up resolved the user-visible stream regression: the hot-loop frontier is no longer empty. Diagnostic reprieve rows now preserve pair, route, spread_bps, reject_reason, and net frontier PnL. Route-identity normalization in dynamic_sweep_runtime.py, dashboard diagnostic fallback, QUOTE_PATH_BLOCKED sweep override, hot_loop canonical guard. Fresh 6-chain canonical scan: 24 runs, 16 diagnostic_pairs across 6 chains. 2162 tests PASS.)
**Tests**: 2162 passed / 5 skipped
**Schema**: start:long_scan_summary:v1.14, m4:run_summary:v2.0, start:hot_loop_snapshot:v1.3
**Evidence**: R35: canonical 6-chain scan (2026-03-23T08:06:35Z). R34: stream signal loss fix (2026-03-22). R33: multi-chain + reprieve (2026-03-21).
**Rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json,hot_loop_latest.json}`

---

## R35 — User-Visible Stream Fix + Evidence Discipline

R35 follow-up resolved the user-visible stream regression. The hot-loop frontier is no longer empty: diagnostic reprieve rows now preserve pair, route, spread_bps, reject_reason, and net frontier PnL. Remaining blockers are downstream economics and real-quote roundtrip truth, not stream serialization.

### Code Changes
1. **strategy/dynamic_sweep_runtime.py** — Route identity normalization: after `sweep_roundtrip_sizes()`, `sr.buy_dex`/`sr.sell_dex` overwritten with OE opportunity’s original direction. Root cause of empty live_stream fields.
2. **monitoring/dashboard.html** — When `verified_pairs=[]`, shows diagnostic frontier as primary panel ("Best Available Frontier") instead of empty table.
3. **strategy/chain_stats.py** — QUOTE_PATH_BLOCKED sweep override: `has_sweep_evidence` guard prevents misclassification when `runs_with_sweep > 0`.
4. **strategy/rolling_outputs.py** — Hot loop canonical guard: require `summary_file` containing `_rolling` to write to HOT_LOOP_LATEST.

### R35 Acceptance Criteria (all PASS)
| Criterion | Status | Evidence |
|-----------|--------|----------|
| `diagnostic_pairs` non-empty, multi-chain | ✅ PASS | 16 entries across 6 chains (arb=5, linea=3, mantle=2, scroll=3, zksync=3) |
| rows have pair/route/spread_bps/reject_reason | ✅ PASS | e.g. USDC/DAI=39.65, WETH/PENDLE=26.63, WETH/WBTC=8.21 bps |
| `runs_with_sweep > 0` | ✅ PASS | arb=4, mantle=4, scroll=4, base=3, zksync=1 |
| `arb blocker != QUOTE_PATH_BLOCKED` | ✅ PASS | arb=OE_ECONOMICS (sweep override working) |
| `blocker_classification` non-null all chains | ✅ PASS | arb/zksync/scroll=OE_ECONOMICS, base/linea=INFRA_FAIL, mantle=MIXED_SOURCE |
| dashboard shows diagnostic frontier | ✅ PASS | "Best Available Frontier (Diagnostic)" panel populated |

### Chain Quality (R35 fresh 6-chain canonical scan, 2026-03-23)
| Chain | Runs | Blocker | Sweep Runs | Signals |
|-------|------|---------|------------|--------|
| arbitrum_one | 4 | OE_ECONOMICS | 4 | 109 |
| zksync | 4 | OE_ECONOMICS | 1 | 3 |
| base | 4 | INFRA_FAIL | 3 | 4 |
| mantle | 4 | MIXED_SOURCE | 4 | 12 |
| linea | 4 | INFRA_FAIL | 0 | 19 |
| scroll | 4 | OE_ECONOMICS | 4 | 16 |

---

## R34 — Fix Stream-to-Analysis Signal Loss

R33 same-session scan proved stream-to-analysis signal loss: top_signals are present in hot_loop and spread_signals are present in truth reports, but live_stream.verified_pairs/diagnostic_pairs are empty because reprieve-only paths crash in run_scan_real.py (token_decimals/rt_top_n unbound) and live_stream.py still builds rows only from roundtrip_results.

### Code Changes (17 new tests)
1. **strategy/jobs/run_scan_real.py** — Hoisted `token_decimals = {}` before `if opps_list:` block (was causing UnboundLocalError on reprieve path).
2. **strategy/jobs/run_scan_real.py** — Hoisted `_rt_top_n` default before conditional (same pattern).
3. **strategy/jobs/run_scan_real.py** — Reworked except block to preserve sweep_reprieve_count/stats/dynamic_sweep and attempt live_stream recovery.
4. **strategy/live_stream.py** — Full rewrite with 3-tier row building: RT → dynamic_sweep → sweep_candidates (reprieve).
5. **strategy/rolling_outputs.py** — `_serialize_live_stream` uses `per_chain["last_live_candidates"]` as fallback (survives after `_clear_active_run`).
6. **strategy/artifacts.py** — `_build_roundtrip_summary` propagates error, sweep_reprieve_count, sweep_reprieve_stats.

### R34 Acceptance Criteria (all PASS)
| Criterion | Status | Evidence |
|-----------|--------|----------|
| `diagnostic_pairs` non-empty | ✅ PASS | 5 entries (USDC/DAI, WETH/PENDLE, WETH/WBTC, etc.) |
| `sweep_reprieve_count > 0` in truth | ✅ PASS | 13 in ci_m5_gate_arbitrum_one_20260322_101413_617724 |
| `runs_with_sweep > 0` in long_scan | ✅ PASS | 2 |
| No `roundtrip.error` in fresh scan | ✅ PASS | `error: None` |

---

## R33 — Start.py Extraction + Reprieve Runtime Validation

### Code Changes (7 files, 25 new tests)
1. **strategy/roundtrip_selection.py** — `select_sweep_reprieve_candidates()`: NET_PROFIT_TOO_LOW rejects with both legs quoter_v2 + cross-DEX get promoted to sweep for wide-size frontier re-check.
2. **strategy/jobs/run_scan_real.py** — Sweep reprieve wiring: when `eligible_opps` empty, reprieve candidates are passed to `run_sweep()`.
3. **start.py** — 4 new per-chain stats: `last_truth_verdict`, `last_quote_source_summary`, `last_oe_rejection_funnel`, `blocker_evidence`. Auto-computed `_compute_blocker_evidence()` with 6-value taxonomy.
4. **strategy/quotes.py** — Quoter_v2 skip cache: after 3 consecutive failures, quoter_v2 is bypassed for 10 minutes.
5. **m4/fixtures.py** — truth_verdict is PRIMARY operator field, placed first in run_summary.
6. **scripts/pair_level_rca.py** — `_rt_gas_bps()` fixes latent bug (gas always 0 in counterfactuals), `_print_oe_funnel()`.
7. **strategy/quote_metrics.py** — `quoter_v2_skipped` counter.

### Tests (+25: 8 sweep reprieve, 10 blocker taxonomy, 7 skip cache)

### Blocker Taxonomy (auto-computed)
Priority: ROUNDTRIP_PROFITABLE > INFRA_FAIL > NO_SIGNAL > QUOTE_PATH_BLOCKED > OE_ECONOMICS > MIXED_SOURCE

---

## R31 — OE Bottleneck Diagnosis + truth_verdict + quote_source_summary

### Architectural Changes (3 new artifact fields)
1. **truth_verdict**: 4-value domain [NO_DATA, ROUNDTRIP_PROFITABLE, DIAGNOSTIC_PROFIT_ONLY, NO_PROFIT]
2. **quote_source_summary**: Per-DEX:fee breakdown of executable/diagnostic/quoter_v2_failed
3. **oe_rejection_funnel**: Total/gated/rejected/reasons from OE gate

### 43-Run Evidence (R31)
| Metric | Value |
|--------|-------|
| Signals total | 308 |
| Net USDC (diag) | $560.16 |
| Profitable RT | 0 |
| truth_verdict | DIAGNOSTIC_PROFIT_ONLY |
| Pass chains | arbitrum_one, linea, scroll |
| Fail chains | zksync, base, mantle |

### OE Rejection Funnel (arb primary)
NET_PROFIT_TOO_LOW: 118 (57%), SUSPECT_SPREAD_HARD: 46 (22%), MIXED_SOURCE: 21 (10%), NOTIONAL_DRIFT: 19 (9%)

### Key RCA Finding
Primary blocker = **economics at $10 probe** (NET_PROFIT_TOO_LOW = 57%), NOT quoter failures (quoter_v2 success rate = 91.7%).

---

## Historical Summary (R29-R28 — condensed)

### R29 — Fixed-Size Doctrine Removed
- **Canonical sweep**: $1–$10,000 (19-point log ladder)
- **Three size layers**: Discovery probe (pool inclusion), Spread seed (signal filter), Executable sweep (profit truth)
- **Sweep evidence**: 54 runs, 0 profitable RT, best gap 0.0 bps (zero-quote at extreme sizes)

### R29 cont'd — Quotes RPC Extraction
- **strategy/quote_rpc.py**: Extracted low-level RPC helpers (quotes.py 2006→1658 lines)
- **Evidence**: 72 runs, 0 profitable RT, best -25.38 bps

### R28.30 — Funnel Normalization
- **6-stage filter funnel**: discovery → quote → spread → engine → selection → roundtrip
- **Signal-loss RCA**: base = quote-path blocked, arb = economics + mixed coverage, linea = slippage

### R28.29 — Lead Audit: Dedup + Discovery Contract
- **env_flag_enabled**: Canonical in core/env.py
- **read_slot0_v3 dedup**: Removed from strategy/infra.py
- **39 discovery productivity tests**

### R28.28 — God-File Extraction
- **run_scan_real.py**: 1724→1371 lines (-20.5%)
- **5 new modules**: scan_universe, roundtrip_selection, dynamic_sweep_runtime, execution_probe, live_stream

### R28.26 — Suppression Layer Isolation
- **4-layer ladder (L0-L3)**: Quarantine=0 impact, runtime_disabled=perf cache, 0 profitable RT all layers
- **Finding**: Suppression NOT cause of zero profitability

### R28.25 — Lead Audit: Filter-Layer RCA
- **10-step fix**: Config alignment (150 USD/5 bps), suppression reform (probation 60s), roundtrip_truth_status
- **235 pool universe → 63 usable quotes (27%)**

### Earlier Rounds (R28.24-R25)
Detailed in git history. Key milestones: hot re-quote loop (R28.11), truth contract (R28.13), benchmark chain (R28.14), execution infra (R28.15), phase visibility (R28.16), 3-tier signal classification (R28.17), LIQUIDITY_ZERO gate (R28.18).

---

## Architecture Contract

> **Static-looking scans are caused by cache-backed discovery and a tiny surviving route surface; live-market target requires real-time quote refresh plus event-driven hot re-quote, not full registry RPC refresh every cycle.**

THREE refresh cadences:
1. **QUOTES/BLOCKS** (live RPC every cycle) — ✅ Working
2. **HOT RE-QUOTE** (event-driven target) — ❌ Timer-based, not WebSocket
3. **REGISTRY/DISCOVERY** (periodic cold refresh) — ❌ Cache-backed

---

## Chain Quality Classification

| Chain | Quality | Blocker | Summary |
|-------|---------|---------|---------|
| arbitrum_one | SIGNAL_PRODUCING | OE_ECONOMICS | 4-DEX, 30 cross-dex pairs, routes_swept=13+, NET_PROFIT_TOO_LOW dominant |
| linea | SIGNAL_PRODUCING | INFRA_FAIL | 2-DEX, 3/4 runs fail, sweep not active |
| scroll | SIGNAL_PRODUCING | OE_ECONOMICS | 3-DEX, accepted-fail, sweep active |
| mantle | SIGNAL_PRODUCING | MIXED_SOURCE | 2-DEX, all runs pass, sweep active |
| zksync | SIGNAL_PRODUCING | OE_ECONOMICS | 2-DEX, 3/4 runs fail, sweep partial |
| base | INFRA_READY | INFRA_FAIL | 3-DEX, >50% fail rate |

**Rollout Queue**: arb → linea → zksync → base → mantle → scroll

---

## Operational Contracts

```powershell
# Offline gate (deterministic)
py -3.11 scripts/ci_m5_0_gate.py --offline --strict

# Online gate (requires RPC)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1

# Unit tests
py -3.11 -m pytest tests/unit -q

# Full CI pipeline
py -3.11 scripts/ci_full_pipeline.py --mode ci
```

---

## Core Truth Statement

> **M5_0 validates artifact schemas/invariants, multicall, failover, provenance.**
> M4 execution gate is separate for profit.
> R32: Sweep reprieve connects wide-ladder to OE re-check for NET_PROFIT_TOO_LOW.
> R31: truth_verdict, quote_source_summary, oe_rejection_funnel — artifact clarity.
> R29: 19-point sweep ladder replaces fixed-size doctrine.
> All chains: `profitable_roundtrips=0` on current evidence.
