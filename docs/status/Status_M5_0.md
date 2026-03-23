# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-23 (R39c — **EXECUTABLE_BEST_NEG distinction + route-level RCA.** 2259 tests PASS. EXECUTABLE_BEST_NEG separates proven-executable negative frontier from paper-only BEST_NEG. Sweep guard + post-aggregation fence + per-chain ranking all updated. Route-level economics in pair_trace.py + pair_level_rca.py.)
**Tests**: 2259 passed / 5 skipped
**Schema**: start:long_scan_summary:v1.14, m4:run_summary:v2.0, start:hot_loop_snapshot:v1.3
**Evidence**: R39c: EXECUTABLE_BEST_NEG + route-level RCA (2026-03-23). R39b: sweep field fix + chain_stats + pair_trace gas (2026-03-23). R39a: frontier fix + sweep guard + RCA (2026-03-23). R38: sweep size + blocker + LST suppression (2026-03-23). R37: artifact parity + frontier classification (2026-03-23). R36: sweep promotion + config expansion (2026-03-23). R35: stream fix (2026-03-23). R34: signal loss fix (2026-03-22). R33: multi-chain + reprieve (2026-03-21).
**Rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json,hot_loop_latest.json}`

---

## R39c — EXECUTABLE_BEST_NEG Distinction + Route-Level Economics RCA

R39c responds to lead's R39c directive: the current reports are a strong proxy for the **supported market surface**, not just pipeline health. Healthy chains (arb/mantle/linea/scroll) are market-economics-blocked. Base and partly zksync are infrastructure/quote-path constrained. The lead's key conclusion: filter relaxation does not unlock profit on healthy chains — the dominant blocker is market economics (spread < slippage + LP fee + gas).

### Market Surface Conclusion (R39c)
- **arb (6 RT)**: USDC/DAI -54 (nearest), WETH/USDC -749 (furthest). 59.3% exec rate. 0 OE gated. **Economics-blocked on all routes.**
- **mantle (2 RT)**: METH/WETH +1444 (LST pseudo-profit), WMNT/USDC -745. 100% exec rate. **Economics-blocked (non-LST).**
- **linea (2 RT)**: WSTETH/WETH +4434 (LST), WETH/WBTC -721. 100% exec rate. **Economics-blocked (non-LST).**
- **scroll (2 RT)**: WETH/USDC -1120, USDC/DAI -4196. 86.7% exec rate. MIXED_SOURCE 37.5%. **Economics + quote-quality.**
- **zksync (1 RT)**: WETH/USDC -876. 100% exec rate. NET_PROFIT 75%, SUSPECT_SPREAD 25%. **Economics-blocked + stability.**
- **base (0 RT)**: SLOT0_DIAGNOSTIC=68.8%, MIXED_SOURCE=28.0%, exec rate 5.0%. **Quote-path constrained — not market verdict.**

### Code Changes (R39c)
1. **strategy/chain_stats.py** — `EXECUTABLE_BEST_NEG` upgrade: when frontier is `BEST_NEG` but `measured_slippage_bps` and `measured_gas_bps` are both populated (not None), the reason upgrades to `EXECUTABLE_BEST_NEG`. This distinguishes proven-executable negative frontiers from paper/placeholder boundaries.
2. **strategy/long_scan_summary.py** — Post-aggregation fence updated: `EXECUTABLE_BEST_NEG` is now an acceptable reason for pnl < 0 (alongside `BEST_NEG`, `ALL_FAILED`, `ALL_SUSPECT_OUTLIER`). Per-chain frontier ranking now includes `sweep_best_frontier_reason` field.
3. **strategy/jobs/run_scan_real.py** — Sweep size promotion guard now accepts `EXECUTABLE_BEST_NEG` alongside `BREAKEVEN_FRONTIER` and `PROFITABLE`. Both primary and error paths updated.
4. **scripts/pair_level_rca.py** — Route-level economics: `extract_pair_trace()` now collects ALL RT results per pair (not just best) with `buy_dex→sell_dex` route detail, gross/net/slippage/gas/LP fee/real-quote. Console output adds "Route-level economics" section after sweep data.
4b. **strategy/pair_trace.py** — `build_pair_funnel_trace()` now collects route-level data (buy_dex, sell_dex, per-route economics) for every RT result, embedded in the truth_report's `pair_funnel_trace`.
5. **tests/unit/test_r38_changes.py** — +9 tests: chain_stats upgrade (4), post-fence (2), sweep guard (1), ranking field (1), route-level data (1). Existing sweep guard test updated. Total: 2259 tests.

---

## R39 — Frontier Contract Fix + Sweep Guard Field Fix + Chain Stats Truthiness + Pair Trace Gas

R39 responds to lead's two canonical scans. First (pre-R39 code): 36 runs, 159 signals, 59 RT, $254.60. Second (post-R39 rerun): 30 runs, 241 signals, 67 RT evaluated, 0 profitable RT, $420.82 diagnostic net USDC. The rerun exposed three additional bugs beyond the initial frontier fix.

### Fresh Evidence (post-R39 rerun, 2026-03-23T16:42:04Z)
| Chain | Runs | PASS | FAIL | Signals | RT Eval | Blocker | Sweep Frontier | BEQ Size |
|-------|------|------|------|---------|---------|---------|----------------|----------|
| arbitrum_one | 5 | 5 | 0 | 175 | 6 | OE_ECONOMICS | BREAKEVEN_FRONTIER | $2500 |
| mantle | 5 | 5 | 0 | 15 | 2 | OE_ECONOMICS | BREAKEVEN_FRONTIER | $25 |
| scroll | 5 | 5 | 0 | 20 | 2 | MIXED_SOURCE | BREAKEVEN_FRONTIER | $50 |
| zksync | 5 | 1 | 4 | 4 | 1 | OE_ECONOMICS | BREAKEVEN_FRONTIER | $50 |
| base | 5 | 3 | 2 | 5 | 0 | NO_SIGNAL | BEST_NEG | $5000 |
| linea | 5 | 0 | 5 | 22 | 2 | INFRA_FAIL | (no sweep) | — |

### Blocker Verdict: MIXED (updated from post-R39 rerun)
- **Healthy supported chains (arb/mantle/scroll)**: 5/5 pass, economics/slippage dominant. Not dead infrastructure.
- **base**: NO_SIGNAL, 3/5 pass. SLOT0_DIAGNOSTIC=68.8%, exec rate 5.0%. Surface-constrained.
- **zksync**: 1/5 pass. Economics + stability needed before market conclusions.
- **linea**: 0/5 pass. INFRA_FAIL. 22 signals but no sweep candidates reach RT. Pipeline gap.
- **LST pseudo-profits**: METH/WETH (mantle +1444 bps) and WSTETH/WETH (linea +4434 bps) are NOT real profitable RT. Must be excluded from headline frontier decisions.

### Code Changes (R39a + R39b)
1. **strategy/long_scan_summary.py** — Fixed frontier contract mismatch: sort key `x.get("sweep_best_net_pnl_bps") or -9999` treated 0.0 as falsy (Python truthiness: `0.0 or -9999 == -9999`), causing top-level to pick BEST_NEG from a worse chain while pnl=0.0. Fixed with `if v is not None else -9999`. Added post-aggregation consistency fence: if pnl==0.0 → force BREAKEVEN_FRONTIER.
2. **strategy/jobs/run_scan_real.py** — Sweep size promotion guarded by executable frontier check. **R39b field fix**: guard checked `measured_total_cost_bps`/`measured_slippage_bps` (don't exist) → always false → size stuck at config 150. Fixed to `best_total_cost_bps`/`best_slippage_bps`. Both primary and error paths updated.
3. **strategy/chain_stats.py** — **R39b truthiness fix**: `sweep.get("measured_gas_bps") or sweep.get("best_gas_bps")` treated 0.0 as falsy → mapped to None. Fixed with `if _var is not None else` pattern for all 4 measured fields (gas, fee, slippage, total_cost).
4. **strategy/pair_trace.py** — **R39b gas computation fix**: Old code used `net_pnl_usd + gas_cost_usd` as "notional" (wrong — sum of PnL + gas ≠ trade notional). For USDC/DAI: gas=2864.67 instead of 12.0. Now parses from `reject_reason` string first (`|gas=12.0|`), fallback to `abs(gross_usd / (gross_bps/10000))`.
5. **scripts/pair_level_rca.py** — `_rt_gas_bps()` now parses gas from `reject_reason` string (authoritative, computed with real notional in engine) before falling back to gross_pnl back-calculation. Fixes Gas column mismatch with live reject reasons.
6. **tests/unit/test_r38_changes.py** — +13 tests total: frontier consistency (3), sweep guard (4 including field name test), chain_stats truthiness (2), pair_trace gas (2), RCA gas parsing (3).
7. **tests/unit/test_pair_trace.py** — Added `gross_pnl_usd` to `_FakeRT` fixture.
8. **tests/unit/test_run_scan_real_purity.py** — max_lines bumped to 1650.
9. **tests/unit/test_nonstop_loop_artifacts.py** — Rolling artifact test allows .log files.

### Tests (+13)
- `TestFrontierContractConsistency`: breakeven vs BEST_NEG (3 tests)
- `TestSweepSizePromotionGuard`: executable/non-executable/BEST_NEG/zero_slippage (4 tests)
- `TestChainStatsSweepMeasured`: zero_slippage_preserved, none_falls_through (2 tests)
- `TestPairTraceGasFromRejectReason`: gas_parsed_from_reject_reason, gas_fallback (2 tests)
- `TestRcaGasBpsFromRejectReason`: parse/fallback/zero (3 tests)

---

## R38 — Sweep Size Promotion + Blocker Accuracy + LST Suppression + Artifact Parity + Event-Driven Loop

R38 responds to lead's 2-hour canonical online audit (282 runs, 2557 signals, 649 RT evaluated, 0 profitable, $4411.02 diagnostic net USDC).

### Blocker Verdict: MIXED (Step 1)
The project blocker is **mixed** — not a single classification:
- **Healthy chains (arb/mantle/scroll)**: 100% PASS, high signal volume. Blocker is pure economics/slippage, not infra. Pipeline is NOT the bottleneck here.
- **Signal-rich but unstable (linea)**: Good signal volume (243/47 runs) but 57% fail rate. Economics-blocked + infra instability.
- **Quote-path debt (base)**: SLOT0_DIAGNOSTIC dominance, NO_DATA rate 34%. Not a market verdict — infrastructure/adapter debt (Aerodrome needed).
- **Weak market data (zksync)**: 79% fail rate. Cannot draw market conclusions until stability improves.
M4.1 (simulate-only) operationally proven; M4.2 (stable profit) still open.

### Code Changes
1. **strategy/jobs/run_scan_real.py** — Final RT candidates now use sweep `best_size_usd` (from `dynamic_sweep`) instead of static `target_usd_notional`. Both primary + error paths updated. Falls back to config when sweep unavailable.
2. **strategy/jobs/run_scan_real.py** — LST-aware SUSPECT_ACCOUNTING: 50 bps threshold for LST/derivative pairs (WSTETH, METH, etc.) vs 500 bps generic. Fixed stale `SANE_RT_PNL_MAX` references to use imported constants.
3. **strategy/jobs/run_scan_real.py** — Fixed NoneType crash in `dynamic_sweep.results` chain (defensive `or {}` for None values).
4. **strategy/long_scan_summary.py** — `OE_ECONOMICS` blocker_reason updated: "economics-blocked (NET_PROFIT_TOO_LOW / SLIPPAGE_TOO_HIGH at real sizes)". Added `QUOTE_PATH_CONSTRAINED` reason entry.
5. **strategy/long_scan_summary.py** — Per-chain aliases: `pass_runs`, `signals_count`, `real_quote_count` alongside originals for consumer parity.
6. **m4/fixtures.py** — `blocker_classification` + `blocker_reason` computed per-run from `oe_rejection_funnel`. Cascade: ROUNDTRIP_PROFITABLE → NO_SIGNAL → QUOTE_PATH_BLOCKED (SLOT0>40%) → OE_ECONOMICS (NET_PROFIT>40%) → MIXED_SOURCE (>30%).
7. **strategy/live_stream.py** — `_LST_TOKENS` frozenset, `_is_lst_pair()` function, `_SANE_RT_PNL_MAX_BPS=500`, `_SANE_RT_PNL_MAX_BPS_LST=50`. SUSPECT_ACCOUNTING threshold is LST-aware.
8. **scripts/pair_level_rca.py** — LST column added to economics decomposition output.
9. **strategy/infra.py** — `DirtySetTracker.wait_for_dirty(timeout)`: event-driven wait using `threading.Event`. WS background threads `set()` the event on `newHeads`, orchestrator wakes immediately. `status()` reports `event_driven: true`.
10. **start.py** — Orchestrator loop: `time.sleep(sleep_seconds)` replaced with `dirty_tracker.wait_for_dirty(timeout=sleep_seconds)`. Falls back to `time.sleep()` when no tracker.
11. **docs/WORKFLOW.md** — Dashboard elevated to primary "Canonical Commands" section (before scanner).

### Tests (+20)
- `test_r38_changes.py`: LST detection (7), blocker classification cascade (8), per-chain aliases (2), blocker reason text (2), RCA LST parity (1)

### Per-Chain Blocker Taxonomy (R38, from lead's 2h canonical audit)
| Chain | Blocker Class | Specific | Action |
|-------|---------------|----------|--------|
| arbitrum_one | OE_ECONOMICS | Near-profit counterfactual only (USDC/DAI -53.96 bps); economics/slippage blocked | Sweep-optimal sizing now live; event-driven execution needed |
| mantle | OE_ECONOMICS | NET_PROFIT_TOO_LOW; LST pseudo-profits (METH/WETH) suppressed at 50 bps | Economics investigation; LST filter active |
| linea | OE_ECONOMICS | Signals exist but economics-blocked; LST pseudo-profits (WSTETH/WETH) suppressed | Economics investigation; LST filter active |
| zksync | OE_ECONOMICS | FAIL-heavy, weak market verdict | Stability track first |
| base | QUOTE_PATH_CONSTRAINED | SLOT0_DIAGNOSTIC dominance, few cross-dex pairs | Separate quote-path track; Aerodrome adapter |
| scroll | MIXED_SOURCE | OE rejects dominated by MIXED_SOURCE | Fix MIXED_SOURCE pairs or filter |

### Per-Chain Worktracks (Step 6)
Each chain now has an independent action track:

| Chain | Track | Priority | Next Action |
|-------|-------|----------|-------------|
| arbitrum_one | **ECONOMICS** | P0 | Event-driven re-quote at WS block, optimal sweep sizing, reduce slippage model |
| mantle | **ECONOMICS** | P1 | LST false-positive filter active; investigate NET_PROFIT on non-LST pairs |
| linea | **STABILITY+ECONOMICS** | P1 | Fix 57% fail rate (RPC reliability), then economics |
| scroll | **MIXED_SOURCE** | P2 | Identify and remove MIXED_SOURCE-dominated pairs, or fix quoter_v2 coverage |
| zksync | **STABILITY** | P2 | Fix 79% fail rate before drawing any economics conclusions |
| base | **QUOTE_PATH** | P3 | Aerodrome adapter; increase cross-DEX pair surface beyond current 3 |

### Quality-Ranked Pair Selection Policy (Step 7)
**Do NOT add more pairs blindly.** Current intent.txt expanded aggressively; many pairs produce only diagnostic data. Policy going forward:
- Pairs must have ≥2 DEXes with real (non-SLOT0) quotes before promotion to core
- Priority: pairs that reach RT evaluation → pairs with near-zero PnL → pairs with signals
- Use `scripts/pair_level_rca.py` to audit pair quality BEFORE adding to configs
- Remove or demote pairs that consistently produce SUSPECT_ACCOUNTING or MIXED_SOURCE rejects

### Selective Coverage Expansion Policy (Step 10)
Coverage expansion (new chains, new DEXes, new pairs) is paused until:
1. Healthy chains (arb/mantle) show RT net_pnl_bps > 0 at optimal sweep size
2. Unstable chains (zksync/linea) reach >80% pass rate
3. Base has Aerodrome adapter or equivalent cross-DEX surface
New pairs should be quality-ranked (Step 7) before admission.

---

## R37 — Artifact Parity + Frontier Classification + Stale-Claims Cleanup

R37 closes the lead's 10-point R36 audit. Code: `BREAKEVEN_FRONTIER` reason added to distinguish 0.0 bps sweep results from genuine negative PnL. `roundtrip_summary` promoted to run_summary top-level. `QUOTE_PATH_CONSTRAINED` blocker added for surface-limited chains (base). Per-chain blocker taxonomy refreshed from rolling artifacts. All stale doc claims cleaned.

R36 closes most recent code/config directives, but not all historical monitoring directives are fully closed yet. On healthy supported chains the dominant blocker is now market economics/slippage, while base and part of zksync remain infrastructure/quote-path constrained; therefore the project is beyond infra bring-up, but not yet at milestone profit closure.

### Code Changes
1. **engine/roundtrip.py** — `BREAKEVEN_FRONTIER` reason for 0.0 bps net_pnl (was classified as `BEST_NEG`). Distinguishes genuine negative frontier from breakeven/zero-quote.
2. **m4/fixtures.py** — `roundtrip_summary` added as top-level key in run_summary (alias of `metrics.roundtrip`) for parity with long_scan_latest.json.
3. **strategy/chain_stats.py** — `QUOTE_PATH_CONSTRAINED` blocker: no signals + few cross-dex pairs (<=3). Separates base (surface-limited) from generic NO_SIGNAL. Taxonomy docstring updated.
4. **docs/status/Status_M5_0.md** — Per-chain blocker taxonomy updated from fresh rolling data. Stale blocker classifications fixed (linea: INFRA_PARTIAL→OE_ECONOMICS, base: QUOTE_PATH_DIAGNOSTICS→QUOTE_PATH_CONSTRAINED, scroll: ECONOMICS_DEAD_POOLS→MIXED_SOURCE).
5. **docs/status/Status_M4.md** — "Pending: 6-chain scan" → completed. Stale R33 claims updated.

### Tests (+2: BREAKEVEN_FRONTIER + QUOTE_PATH_CONSTRAINED)

---

## R36 — Surface Expansion + Sweep Frontier Promotion

R36 closes the gap between "adapter implemented" and "adapter enabled in production configs". SyncSwap and iZiSwap adapters are now active in all applicable chain configs. Sweep frontier promotion ensures `best_size_usd` from dynamic sweep influences headline RT metrics. ZERO_QUOTE_FRONTIER distinction (`frontier_reason`) surfaced in long_scan_summary.

### Code Changes
1. **config/real_minimal.yaml** — +iziswap (arb), +same_dex_verification: true
2. **config/onboard_zksync_candidate.yaml** — +syncswap, +iziswap
3. **config/onboard_linea_stage1.yaml** — +syncswap_linea, +iziswap
4. **config/onboard_mantle_stage2.yaml** — +iziswap
5. **config/onboard_scroll_stage1.yaml** — +syncswap, +iziswap
6. **strategy/jobs/run_scan_real.py** — Sweep frontier promotion: when sweep `best_net_pnl_bps` > fixed-size RT, promote to `stats["roundtrip"]["best_net_pnl_bps"]` with `sweep_promoted=true`.
7. **strategy/chain_stats.py** — Track `sweep_best_frontier_reason` per chain (ALL_FAILED / BEST_NEG / PROFITABLE).
8. **strategy/long_scan_summary.py** — Surface `sweep_best_frontier_reason` at top level for downstream consumers.
9. **docs/ONBOARDING_MATRIX.md** — Added 9 entries (syncswap×3, iziswap×5, syncswap_linea×1) to Adapter Registry and Coverage Matrix.

### R36 Acceptance Criteria
| Criterion | Status | Evidence |
|-----------|--------|----------|
| New adapters in active configs | ✅ PASS | 5 configs updated (arb/zksync/linea/mantle/scroll) |
| same_dex_verification enabled | ✅ PASS | real_minimal.yaml |
| Sweep promotion implemented | ✅ PASS | run_scan_real.py `sweep_promoted` flag |
| ZERO_QUOTE_FRONTIER in summary | ✅ PASS | `sweep_best_frontier_reason` in long_scan_summary |
| ONBOARDING_MATRIX updated | ✅ PASS | 9 new rows in Coverage Matrix |
| Tests pass | ✅ PASS | 2211 passed, 5 skipped |
| ambient.py remains stub | ⚠️ KNOWN | Ambient adapter not claimed as production; stub only |

### Per-Chain Blocker Taxonomy (R36, updated R37 from fresh rolling)
| Chain | DEXes (R36) | Blocker Class | Specific Blocker | Action |
|-------|-------------|---------------|------------------|--------|
| arbitrum_one | 5 (uni+sushi+pcswap+camelot+izi) | OE_ECONOMICS | Gas $2.84 + slip 7-9x at $5 sweep best (-27.4 bps) | Economics/slippage investigation; event-driven execution |
| zksync | 4 (uni+pcswap+syncswap+izi) | OE_ECONOMICS | NET_PROFIT_TOO_LOW at probe; 0.0 bps frontier at $50 | Stability track (FAIL-heavy), then market conclusions |
| base | 3 (uni+sushi+pcswap) | QUOTE_PATH_CONSTRAINED | No syncswap/izi in dexes.yaml, surface limited, few cross-dex pairs | Separate quote-path track; Aerodrome adapter |
| mantle | 4 (agni+fusionx+stratum+izi) | OE_ECONOMICS | NET_PROFIT_TOO_LOW; 0.0 bps frontier at $50 | Economics investigation |
| linea | 4 (pcswap+lynex+syncswap_linea+izi) | OE_ECONOMICS | Signals exist, OE rejects; no sweep candidates reach RT | Economics investigation (was INFRA_PARTIAL, now PASS) |
| scroll | 5 (uni+sushi+nuri+syncswap+izi) | MIXED_SOURCE | OE rejects dominated by MIXED_SOURCE | Fix MIXED_SOURCE pairs or filter; then economics |

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

| Chain | Quality | DEXes (R36) | Blocker (R37 fresh) | Summary |
|-------|---------|-------------|---------------------|--------|
| arbitrum_one | SIGNAL_PRODUCING | 5 (uni+sushi+pcswap+camelot+izi) | OE_ECONOMICS | 5-DEX, 30+ cross-dex pairs, gas+slippage dominant (USDC/DAI gap=54bps) |
| zksync | SIGNAL_PRODUCING | 4 (uni+pcswap+syncswap+izi) | OE_ECONOMICS | 4-DEX, FAIL-heavy but signals exist, NET_PROFIT_TOO_LOW |
| scroll | SIGNAL_PRODUCING | 5 (uni+sushi+nuri+syncswap+izi) | MIXED_SOURCE | 5-DEX, MIXED_SOURCE rejection dominant |
| mantle | SIGNAL_PRODUCING | 4 (agni+fusionx+stratum+izi) | OE_ECONOMICS | 4-DEX, fragile pass, NET_PROFIT_TOO_LOW |
| linea | SIGNAL_PRODUCING | 4 (pcswap+lynex+syncswap_linea+izi) | OE_ECONOMICS | 4-DEX, 5/5 PASS (was INFRA_FAIL), no sweep candidates |
| base | INFRA_READY | 3 (uni+sushi+pcswap) | QUOTE_PATH_CONSTRAINED | Surface limited, no expansion in dexes.yaml |

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
