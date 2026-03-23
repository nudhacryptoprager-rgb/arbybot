# Status: M4 (DEX-DEX Atomic Execution)

**Status**: **M4.1 SIMULATE-ONLY CLOSED** (N≥100 REGISTRY_REAL runs with profit, agg_status=PASS)  
**Updated**: 2026-03-23 (R39b — **Sweep guard field fix + chain_stats truthiness + pair_trace gas.** Post-R39 rerun: 30 runs, 241 sig, 67 RT, 0 profitable, $420.82. 2250 tests PASS.)  
**Policy**: DIVERSITY_PAIRS_TARGET=4 (adjusted for min_spread_bps=10 filter)  
**Infra Evidence**: see [Status_M5_0.md](Status_M5_0.md) for multicall/failover/WS proof  
**Profit Truth**: `profit_is_diagnostic=true`, `profit_truth_source=ONE_LEG_DIAGNOSTIC`. R29 (3): paper_size_usd now annotated as `seed_diagnostic` — separate from executable sweep truth.  
**Primary blocker**: Economics (gas+slippage) remain chain-specific. R39b: sweep guard field names fixed (was dead code), chain_stats 0.0 truthiness fixed, pair_trace gas computation fixed. R39a: `BREAKEVEN_FRONTIER` enforced via post-aggregation fence. R38: sweep size promotion + LST suppression. R37: `BREAKEVEN_FRONTIER` distinguished from genuine negative. On healthy chains (arb/mantle/scroll) blocker is market economics. On base: NO_SIGNAL/surface-constrained. On zksync: 1/5 pass + economics. On linea: 0/5 INFRA_FAIL. `profitable_roundtrips=0` persists.

## [!] M4.1 Simulate-Only DoD **MET** (historical)

**M4.1 DoD ACHIEVED** (per Roadmap.md L130-145, achieved pre-R28.17):
- ✅ N = 100 REGISTRY_REAL runs with `net_usdc > 0`
- ✅ `agg_status = PASS` sustained
- ✅ `profit_is_diagnostic = true` (accepted for simulate-only)
- ✅ `total_net_usdc = $1142.02` (cumulative paper profit, historical)

**Current State (R33)**:
- Rolling: runs_in_window=200+, unique_pairs=13+
- **No chain is positive control** — all chains have best_net_pnl_bps < 0
- R33: Reprieve validated — linea/scroll/mantle now select NET_PROFIT_TOO_LOW rejects for sweep
- R33: blocker_classification auto-computed (base=QUOTE_PATH_BLOCKED, zksync=INFRA_FAIL)
- Policy: `intent.txt` = business intent; pool-level quarantine/runtime_disabled handles filtering

**M4.2 (roundtrip) Remains**:
- Requires market arb opportunity (`roundtrip.profitable_count > 0`)
- Non-deterministic, depends on market conditions
- Currently blocked: all chains have best_net_pnl_bps < 0

---

> [!] **ROLLING STABILITY (2026-03-23 R37)**: **Artifact parity + frontier classification.** `BREAKEVEN_FRONTIER` reason (0.0 bps ≠ BEST_NEG). `roundtrip_summary` in run_summary top-level. `QUOTE_PATH_CONSTRAINED` for base. Per-chain taxonomy refreshed from rolling. Stale doc claims cleaned. 2213 tests PASS.
> [!] **ROLLING STABILITY (2026-03-23 R36)**: **Surface expansion + sweep frontier promotion.** SyncSwap + iZiSwap enabled in 5 active chain configs (arb: 4→5, zksync: 2→4, linea: 2→4, mantle: 3→4, scroll: 3→5). Sweep `best_net_pnl_bps` promoted to headline RT when better than fixed-size. `sweep_best_frontier_reason` surfaced (ALL_FAILED vs BEST_NEG). `same_dex_verification: true` on arbitrum. ONBOARDING_MATRIX updated (9 entries). 2213 tests PASS. 6-chain canonical scan: DONE (30 runs, 207 signals).
> [!] **ROLLING STABILITY (2026-03-23 R35)**: **User-visible stream fix + evidence discipline.** Route-identity normalization in dynamic_sweep_runtime.py resolved empty live_stream. QUOTE_PATH_BLOCKED sweep override (arb→OE_ECONOMICS). Hot_loop canonical guard hardened. Dashboard diagnostic fallback. Fresh 6-chain canonical scan: 24 runs / 6 chains / 163 signals / 0 profitable RT / 16 diagnostic_pairs. 2162 tests PASS.
> [!] **ROLLING STABILITY (2026-03-21 R33)**: **start.py extraction completed.** start.py 2236→753 lines (4 modules: run_artifact_extract.py, chain_stats.py, long_scan_summary.py, rolling_outputs.py). eligible_opps scoping bug fixed (was UnboundLocalError silently caught). OE→reprieve contract fixed (_rejected_opportunities). Fresh 10-min multi-chain scan: reprieve validated (linea=6, scroll=3, mantle=3 selected). blocker_classification/blocker_reason materialized from evidence. --allow-partial-chains flag added for single-chain verification. 2137 tests PASS.
> [!] **ROLLING STABILITY (2026-03-20 R29 (3))**: **Fixed-size doctrine removed.** CANONICAL_SWEEP_SIZES_USD widened: 7-point [50–250] → 19-point [1–10000]. top_routes 3→15. Three decoupled size layers (discovery_probe, spread_seed, executable_sweep). Fresh 54-run canonical scan: 654.8s wall / 54 included signals / 49 RT evaluated / 0 profitable RT / best -28.70 bps (fixed-size). Sweep frontier: arb true minimum -16.89 bps at $25 (was -31.75 at $150). Gap_to_zero: 0.0 bps at $2500 (zero-quote) → true gap -16.89 bps at $25.
> R29 cont'd: staged `quotes.py` extraction landed (`quote_rpc.py` added; `quotes.py` 2006→1658). Same-session canonical run: 72 runs / 647.8s / 78 included signals / 57 RT evaluated / 0 profitable RT. `/api/hot` matched `long_scan_latest.json` in the same session.
> R28.28: God-file extraction: run_scan_real.py 1724→1371 lines, 5 modules, 38 tests. 2017 PASS.
> R28.27: Cap isolation toggles + same-DEX override + diagnostics + 4 chain fixes. 1979 tests.
> R28.22-cont-2: Per-chain NO_USD_PRICE fixes (+14 tokens), zombie quarantine fix, 97.7-min bundle (406 runs). base 0→54 signals.
> R28.21: Cache freshness observability, all chains cache-backed (rpc=0), 0 profitable RT. Removed stale positive-control claims.
> R28.20: Lead post-verification directive (10 issues, 10 fix steps). warm_pool_cache+start.py tooling fixes. reject_histogram+reject_samples in truth artifacts. actionable_signals_count. mantle/scroll configs. Fresh 54-run online verification: 0 profitable RT confirmed.
> R28.19: best_net_pnl_bps sane filter fix (base 8e16 contamination blocked). +8 regression tests. Reject visibility in truth_report roundtrip_summary.
> R28.18: Code fixes for scroll price-truth blocker + promotion contract enforcement + fresh 10-min online evidence.
> R28.17: Truth-quality discipline. SUSPECT_ACCOUNTING state added. Accumulation guard rejects insane PnL. 3-tier signal classification. All chains reset to non-profitable.
> R28.15: Live execution infrastructure implemented (simulator.py, dex_dex_executor.py, providers.py) but dormant in production. Scanner wiring done. +38 tests.
> R28.11 Turn 2: Hot re-quote loop + WebSocket dirty-set invalidation — dual-cycle architecture.
> Earlier rounds: see Status_M5_0.md for full history.

**Economics Snapshot (2026-03-20, R29 (3) — from 54-run long_scan, 654.8s, WIDE FRONTIER):**
| Metric | Value | Source |
|--------|-------|--------|
| `arb sweep_best_size_usd` | $2500 (zero-quote) | long_scan R29(3) frontier_ranking |
| `arb true_optimum` | **-16.89 bps at $25** | sweep curve U-shaped: gas=3.84, slip=7.32, fee=10.00 |
| `arb old_fixed_$150` | -31.75 bps | same sweep curve (improvement: +14.86 bps) |
| `arb best_net_pnl_bps (RT)` | -28.70 bps | long_scan R29(3) (fixed-size RT eval) |
| `mantle sweep_best` | $250 / 0.0 bps (zero-quote) | long_scan R29(3) (WMNT/USDT) |
| `base sweep_best` | $10000 / 0.0 bps (zero-quote) | long_scan R29(3) (WETH/VIRTUAL) |
| `zksync sweep_best` | $25 / -209.87 bps | long_scan R29(3) (WETH/WBTC) |
| `linea sweep_best` | — (no sweep data) | no cross-DEX RT candidates |
| `scroll sweep_best` | — (no sweep data) | accepted_fail, no real RT |
| `total_profitable_roundtrips` | 0 | long_scan R29(3) (all chains) |
| `benchmark_chain` | None | long_scan R29(3) (no chain qualifies) |

**Rollout Queue (R29 (3) — 54-run bundle, wide frontier verified):**
| Priority | Chain | Status | Sweep Evidence |
|----------|-------|--------|----------------|
| 1 | arbitrum_one | ECONOMICS_GAS_SLIPPAGE | true min -16.89 bps at $25 (was -31.75 at $150), 4 RT eval, gap improved ~15 bps |
| 2 | linea | ECONOMICS_CONTROL | no sweep data (no cross-DEX RT candidates) |
| 3 | zksync | THIN_SURFACE_ECONOMICS | $25 / -209.87 bps, significant gap |
| 4 | base | QUOTE_PATH_BLOCKED | $10000/0.0 = zero-quote, 0 signals |
| 5 | mantle | LIQUIDITY_QUALITY | $250/0.0 = zero-quote, fragile pass |
| 6 | scroll | NO_REAL_RT | no sweep data, accepted_fail |

## Executor Onboarding Checklist (2026-03-04)

**Pre-session reading (MANDATORY for Claude executor):**

| Document | Path | Purpose |
|----------|------|---------|
| Agent Rules | `AGENTS.md` | Role, output format, artifact policy |
| Roadmap | `Roadmap.md` | Milestone goals, priorities |
| Docs Policy | `docs/DOCS_POLICY.md` | Version/timestamp rules |
| Workflow | `docs/WORKFLOW.md` | Commands, CI gates, review loop |
| DEV Report Format | `docs/DEV_REPORT_CANONICAL_UA.md` | Canonical report structure |
| Rolling Contract | `docs/m4/ROLLING_CONTRACT.md` | Artifact schemas, provenance |
| Status Index | `docs/status/INDEX.md` | Status file navigation |
| M4 Status | `docs/status/Status_M4.md` | Current milestone state |
| M5_0 Status | `docs/status/Status_M5_0.md` | Infra evidence |

**Key rules:**
1. Evidence = `run_timestamp` + rolling artifacts (NOT code SHAs)
2. COVERAGE runDir without `run_summary` is invalid evidence
3. Version strings (`vX.Y.Z`) forbidden in Status files (use dates)
4. Do NOT reference `setting_timlid.md` (Codex-only)

## M4 vs M5_0 Boundary (2026-03-04)

**Critical distinction**: M4 rolling evidence ≠ M5_0 infra work.

| Scope | M4 (Execution Gate) | M5_0 (Infra Rollout) |
|-------|---------------------|----------------------|
| Purpose | Prove stable simulate-only profit | Expand chains, DEX coverage |
| Rolling | NORMAL only, primary chain | No rolling (COVERAGE/bring-up) |
| Primary Chain | `arbitrum_one` | Any (bring-up) |
| Artifacts | `_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json` | runDir bundles only |
| Evidence | Counted toward M4.1/M4.2 DoD | Not counted |

**Rolling Chain Discipline**:
- NORMAL+`--refresh-rolling` = `arbitrum_one` ONLY
- Multi-chain bring-up = COVERAGE mode, NO `--refresh-rolling`
- `MIXED_CHAIN_KEYS` warning = rolling contamination from non-primary chains

**M4.1 CLOSED (simulate-only)** - achieved via N≥100 REGISTRY_REAL runs with profit.

**M4.2/M4.3 NOT CLOSED** (require real execution):
- `profit_truth_available=false` (no real execution yet)
- `profit_is_diagnostic=true` (paper-only)
- Requires `roundtrip.profitable_count > 0` (market-dependent)

**Multi-chain runs must use**:
- `run_kind: COVERAGE` (not NORMAL)
- No `--refresh-rolling` flag
- Separate runDir analysis (not rolling metrics)

## Evidence Discipline (2026-03-04)

**COVERAGE evidence validity rule**: COVERAGE runDir is valid evidence ONLY if it contains `run_summary` (with `run_timestamp`). Without run_summary, the runDir cannot be referenced for metrics.

**run_summary generation**: All ONLINE PASS runs now generate run_summary regardless of `--refresh-rolling` flag (via M4 gate with `--artifact-mode full`).

**Algebra DEX safety**: `camelot_v3` removed from NORMAL intent configs until Algebra executable quoting is implemented. Keep in COVERAGE only for safe testing.

## Config Contract Canonical Keys (Fixes 2026-03-04)

**Canonical Keys** (MUST use these, not aliases):
- `run_kind` (not `run_kind_hint`) - determines rolling policy
- `discovery_runtime_max_pairs` (not `max_pairs`) - discovery contract
- `price_sanity_max_deviation_bps` (not `max_deviation_bps`) - sanity checks

**M4.2 Truth-Semantics** (required for intent configs):
```yaml
truth_mode_m42: true
execution_enabled: false
execution_block_reason: "EXECUTION_DISABLED_M4"
kill_switch_active: true
simulate_only: true
```

**validate_universe.py Updates**:
- Now supports `universe_source: discovery_runtime`
- Warns on non-canonical keys
- Requires explicit `run_kind` (not default to NORMAL)

**ci_m5_0_gate.py Guardrails**:
- FAIL if `--refresh-rolling` without explicit `run_kind`
- FAIL if `run_kind != NORMAL` with `--refresh-rolling`

## [!] M4 Close Plan

> **Problem**: M4 close depends on `roundtrip.profitable_count > 0`, which requires market arb opportunity.  
> **Current state (R18)**: `roundtrip.profitable_count=0`, best=-4.10 bps @ $25, latest=-13.44 bps @ $25, median=-18.74 bps.

**Economics frontier progress (2026-03-13):**
- **Best-ever gap**: 4.10 bps (arb_one), zksync frontier=0.0 bps (fresh scan)
- **Fee=100 lever**: If exists with liquidity, saves 8 bps → immediately crosses breakeven
- **Multi-chain frontier**: 5 chains ranked, zksync #1, arb_one #2, base #3

**Deterministic M4 Close Criteria (choose one):**
1. ✅ **Time-bound window**: N=100 consecutive runs with `agg_status=PASS` and `profit_is_diagnostic=true` is acceptable for simulate-only - **ACHIEVED 2026-02-21**
2. **Synthetic test**: Create fixture with profitable roundtrip to prove code path works (offline-only gate)
3. **Fee=100 discovery**: On-chain factory query for WBTC/USDC fee=100 pool → may immediately close M4.2

**Status**: Option 1 (time-bound window) completed. M4.1 simulate-only CLOSED. **M4.2 near closure** — gap_to_zero_min=3.55 bps (improved from 4.10). Base chain detected 2 profitable roundtrips (COVERAGE, not NORMAL).

## [WARN] PROFIT REALISM WARNING

**Paper profit PROVEN** under simulated cost model (`gas=$0.10`, `slippage=5bps`).
**Profit realism NOT PROVEN** — round-trip shows actual losses (`profitable_count=0`, best=-4.10 bps @ $25, latest=-9.03 bps @ $25).
**Near breakeven**: Best-ever frontier only 4.10 bps from zero; fee=100 lever would save 8 bps.
M4.2 requires `roundtrip.profitable_count > 0` AND `real_quote_count > 0` with real quoter-based economics (R28.2 semantics fix).

## M4.2 Economics Frontier (2026-03-15)

**Primary blocker**: `gap_to_zero_bps` (distance from breakeven in sweep best).

| Metric | R11 | R14 | R18 | R20 | R26 | R27.2 | R28.2 | **R28.6** | Delta |
|--------|-----|-----|-----|-----|-----|-------|---------|---------|-------|
| `sweep_best_net_pnl_bps` | -4.10 | -4.10 | -4.10 | -4.10 | -3.55 | -15.77 | -17.99 (median) | **-17.99** | stable |
| `gap_to_zero_bps (best)` | 4.10 | 4.10 | 4.10 | 4.10 | 3.55 | 15.77 | 3.55 (best-ever) | **3.55** | stable |
| `profitable_count (arb)` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | **0** | arb-only |
| `profitable_count (long_scan)` | — | — | — | — | — | 2 (SUSPECT) | 4 (base=2, linea=2) | **14** | +10 (parallel) |
| `frontier_pair` | WBTC/USDC | WBTC/USDC | WBTC/USDC | WETH/USDT | WETH/USDT | WETH/USDT | WETH/USDT | **WETH/USDT** | stable |
| `measured_fee_bps` | 10.0 | 10.0 | 10.0 | 10.0 | 10.0 | 10.0 | 10.0 | **10.0** | stable |
| `test_count` | 1635 | 1653 | 1661 | 1685 | 1738 | 1798 | 1817 | **1837** | +20 |
| `runs_in_window` | 161 | 170 | 179 | 184 | 200 | 200 | 200 | **200+** | stable |
| `total_net_usdc` | $1016 | $1065 | $1114 | $1142 | $1306 | $1310 | $1357 | **$1357+** | stable |

**Cost decomposition (arb WETH/USDT @ $25, R20 latest):**
- LP fee: 10.0 bps (2x500 tier) — **main controllable cost, fee=100 would save 8 bps**
- Slippage: 11.97 bps (volatile run, median=8.06)
- Gas: 3.16 bps (L2)
- Total: 25.13 bps cost (fee=40% of cost)

**R28.6 note**: RunDir collision fix (6→0 collisions in parallel). Long scan parallel (workers=2): 31 runs / 69 signals / $116.34 / 14 profitable RT / 544s wall / 0 collisions. Linea strongest non-arb (12 profitable RT). Scanner latency + evidence integrity now same priority blocker as arb market gap (per lead R28.6).
**R28.3 note**: Long scan improved: 9 runs/44 signals/$41.80 (was 8/23/$31.37). Sweep best=-12.81 bps (was -17.41). Scroll produced first non-zero signal. Base 3 profitable RT in long_scan (still thin: real_quote_count=1 per run). Agg: gap_median=17.95 bps, best-ever=3.55 bps unchanged.
**Best-ever frontier**: -3.55 bps gap (R26) — only needs ~4 bps improvement to breakeven.
**Fee=100 lever**: If fee=100 pool exists with liquidity, saves 8 bps → would cross breakeven.

**Evidence**: `long_scan_latest.json` (REFRESHED R28.6 parallel), `m4_stability_agg.json`, R28.6 session runDirs (chain-scoped).

**Pipeline status**: Full measured economics (gas/fee/slippage/total_cost_bps) canonical in: truth_report → run_summary → m4_stability_agg → _latest.json. Rolling includes: median_gap_to_zero_bps, median_net_pnl_bps, frontier_pair_latest, frontier_chain_latest. Per-chain frontier ranking in start.py summary.

## M4.2 Profit Truth Definition

> **FORMAL DEFINITION (binding):**
> When `truth_mode_m42=true` in config:
> - **Canonical profit** = Round-trip net_pnl_wei (leg1 + leg2 via QuoterV2, minus gas L2+L1)
> - **One-leg gross/net** = DIAGNOSTIC ONLY (not used in gating decisions)
> - **profit_realism_status** = mandatory field in truth_report (ROUNDTRIP_PROFITABLE | ROUNDTRIP_NOT_PROFITABLE | ONE_LEG_ONLY_DIAGNOSTIC)
> - **Roundtrip NOT_PROFITABLE is not a bug** - it means Truth Engine correctly detects no real arb opportunity

| Model | Description | Status |
|-------|-------------|--------|
| **One-leg spread** | `price_a / price_b` across DEX | DIAGNOSTIC ONLY |
| **Round-trip quoter** | `token_in -> token_out -> token_in` via QuoterV2 | [OK] Callback ready, leg2 re-quote wired |
| **Live gas** | `eth_getGasPrice` + WETH/USDC live price | [OK] In opportunity_engine + roundtrip |
| **Live slippage** | `(small_quote - target_quote) / target_quote` | [TODO] probe_slippage() ready, artifact integration pending |

**Reality Gates in Effect:**
| Gate | Source | Threshold | Status |
|------|--------|-----------|--------|
| `PRICE_SANITY_FAILED` | `strategy/quotes.py` via `core.validators.check_price_sanity` | `price_sanity_max_deviation_bps` | [OK] CONNECTED (quoter-path) |
| `SUSPECT_LIQUIDITY` | `strategy/quotes.py` | `ticks>15` or `gas>500k` | [OK] ACTIVE |
| `SUSPECT_SPREAD_HARD` | `engine/opportunity_engine.py` | `spread > SUSPECT_SPREAD_BPS_HARD` (500bps) | [OK] ACTIVE |
| `NOTIONAL_DRIFT` | `engine/opportunity_engine.py` | `|notional - target| / target > max_drift%` | [OK] ACTIVE |
| `MIXED_SOURCE` | `engine/opportunity_engine.py` | one leg quoter_v2, one leg slot0 | [OK] ACTIVE |
| `SLOT0_DIAGNOSTIC` | `engine/opportunity_engine.py` | both legs slot0 | [OK] ACTIVE |

**M4.2 Quote Source Policy:**
| Source | When Used | M4.2 Status |
|--------|-----------|-------------|
| `quoter_v2` | QuoterV2 call success | [OK] CANONICAL for profit |
| `slot0` | QuoterV2 fails/unavailable | DIAGNOSTIC ONLY (excluded from gated top-N) |
| `mixed` | One leg quoter, one leg slot0 | REJECTED (no mixed-source opportunities) |

> **M4.2 NOTE**: slot0 fallback quotes are collected for diagnostics but NOT used in opportunity gating.
> Opportunities require BOTH legs to have `quote_source=quoter_v2`.

## Core Truth (from Roadmap.md)

> **M4 execution gate є "core truth" для релізу.**

| DoD Level | Criterion | Evidence Required | Status |
|-----------|-----------|-------------------|--------|
| **M4.1 Simulate-only** | Code/schema/invariants | FIXTURE_OFFLINE or REAL with simulate_only=true | [OK] PASS |
| **M4 Online Profit (core truth)** | Paper profitability | `run_mode=REGISTRY_REAL`, N>=5 runs with `total_net_usdc > 0` | [OK] DIAGNOSTIC (one_leg_profit) |
| **Rolling Quality Gate** | Operational stability | `data_run_rate >= 0.30`, `agg_status != FAIL` | [OK] PASS |

**Clarification:**
> "Core Truth" (+PnL) != "Rolling Quality Gate". Core truth підтверджує що система генерує profit (paper, simulated cost).
> **IMPORTANT**: `one_leg_profit_is_diagnostic=true` means profit is simulated, NOT proven on-chain.
> Rolling quality gate перевіряє стабільність в операційному режимі.
> agg_status=FAIL означає проблеми з якістю даних, НЕ відсутність profit.

**RunMode Canonical:**
> `REGISTRY_REAL` is the canonical run_mode for online scanning.
> Legacy docs may use `REAL` as shorthand but artifacts MUST use `REGISTRY_REAL`.

**M4-profit DoD**: See `Roadmap.md` L52-62. Quick ref: N>=5 runs with `run_mode=REGISTRY_REAL`, `total_net_usdc>0`.

## Contracts & Reference (condensed)

**Version Discipline**: SHA-free provenance via `run_timestamp`. See `AGENTS.md §2`, `docs/DOCS_POLICY.md`.

**Workflow**: DEV (fast iteration, run_timestamp only) | RELEASE (public proof + rolling artifacts).

**Taxonomy**: `FAIL_*` → status=FAIL mandatory. `WARN_*` → status=PASS allowed. `NO_DATA` → signals_count==0 only.

**Status Contract**: NO_DATA = signals==0. signals>0,net>0 = PASS. signals>0,net≤0 = FAIL. signals<5 = quality_status=WARN.

**Run Kinds**: NORMAL (counted in KPIs) | COVERAGE (separate stats) | SMOKE/OFFLINE (excluded).

**Rolling KPIs**: data_run_rate≥0.50 (FAIL<0.30), fail_rate≤0.10 (FAIL>0.15), unique_pairs≥10 (FAIL<3), unique_routes≥4 (FAIL<2).

**Thresholds**: MIN_SIGNALS_FOR_PASS=3, MAE_WARN/FAIL=0.55/0.80, SIGN_RATE_MIN=0.60, AGG_FAIL_RATE=0.15, DIVERSITY_PAIRS_MIN/ROUTES_MIN=3/2.

**Docs Freeze**: DoD/contract changes only when code changes require it + rolling artifacts demonstrate new structure.

## Canonical Commands

```bash
# M4 gate (profit)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling
# Check rolling
Get-Content data/runs/_rolling/m4_stability_agg.json | Select-String "data_run_rate|no_data_rate"
```

## Rolling Artifacts

`data/runs/_rolling/`: `_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`

## Definition of Done

### M4.1: Simulate-Only -- [OK] PASS
- [x] Online scan generates signals
- [x] PnL calculated in strategy/artifacts.py pipeline (execution/simulator.py is SKELETON — expected for simulate-only)
- [x] Rolling artifacts persist
- [x] Evidence workflow works
- [x] agg_status = WARN_QUALITY (only DIVERSITY_*) accepted per Acceptable States table

### M4 Online Profit (core truth) -- [OK] DIAGNOSTIC (simulated)
- [x] N>=5 consecutive online runs with run_mode=REGISTRY_REAL (52 runs total, 24 data runs)
- [x] All data runs have total_net_usdc > 0 (pass_count=24, fail_count=0)
- [x] All runs use real pinned_block (not 429900000)
- [x] Paper profit confirmed under declared cost model
- [x] total_net_usdc (window): $416.18
- [ ] **NOTE**: `one_leg_profit_is_diagnostic=true` - on-chain profit NOT yet proven

**Rolling Quality Gate -- [OK] PASS:**
- [x] data_run_rate >= 0.30, agg_status != FAIL, unique_pairs >= 8, unique_routes >= 2, agg_reasons = []

### M4.2: Real Execution -- [NO] NOT PROVEN
- [ ] Kill switch disabled
- [ ] Real TX submitted
- [ ] On-chain profit recorded

## Known Blockers

1. **Python version**: Pipelines require 3.11 (3.14 not supported)
2. **DIVERSITY targets**: unique_routes=2 (<4 M5 target) — requires 3rd DEX. Deferred to M5.
3. **PROFIT REALISM**: Quoter-based PnL model required for M4.2. Do not proceed to execution until validated.

## Documentation

- [Policy & Thresholds](../m4/M4_POLICY.md)
- [Rolling Contract](../m4/ROLLING_CONTRACT.md)
- [Testing Guide](../TESTING.md)
