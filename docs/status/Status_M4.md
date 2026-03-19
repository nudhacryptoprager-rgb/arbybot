# Status: M4 (DEX-DEX Atomic Execution)

**Status**: **M4.1 SIMULATE-ONLY CLOSED** (N≥100 REGISTRY_REAL runs with profit, agg_status=PASS)  
**Updated**: 2026-03-19 (R28.25 — Lead audit: filter-layer RCA corrected. Config aligned all chains 150 USD / 5 bps. Suppression reform. roundtrip_truth_status elevated to compute_status(). 0 profitable RT. Pending verification scan.)  
**Policy**: DIVERSITY_PAIRS_TARGET=4 (adjusted for min_spread_bps=10 filter)  
**Infra Evidence**: see [Status_M5_0.md](Status_M5_0.md) for multicall/failover/WS proof  
**Profit Truth**: `profit_is_diagnostic=true`, `profit_truth_source=ONE_LEG_DIAGNOSTIC`. **R28.25**: roundtrip_truth_status now separate field in compute_status() — "PROFITABLE"/"NOT_PROFITABLE"/"NO_DATA". profit_status (one-leg) preserved but no longer masks roundtrip truth. All chains PRIMARY_BLOCKER or CANDIDATE. 0 profitable RT. Filter funnel material blocker alongside market efficiency.  
**Primary blocker**: Filter funnel (73% quote loss) + market efficiency (phantom spreads) — roundtrips evaluate negative even with reduced suppression. Anchor stale since 2026-02-17.

## [!] M4.1 Simulate-Only DoD **MET** (historical)

**M4.1 DoD ACHIEVED** (per Roadmap.md L130-145, achieved pre-R28.17):
- ✅ N = 100 REGISTRY_REAL runs with `net_usdc > 0`
- ✅ `agg_status = PASS` sustained
- ✅ `profit_is_diagnostic = true` (accepted for simulate-only)
- ✅ `total_net_usdc = $1142.02` (cumulative paper profit, historical)

**Current State (R28.21)**:
- Rolling: runs_in_window=200+, unique_pairs=13
- **No chain is positive control** — R28.17+ truth audit reset all chains to non-profitable
- All chains cache-backed (rpc=0), registry from warm_pool_cache
- Policy: `intent.txt` = business intent (per Roadmap.md:680); pool-level quarantine/runtime_disabled handles filtering

**M4.2 (roundtrip) Remains**:
- Requires market arb opportunity (`roundtrip.profitable_count > 0`)
- Non-deterministic, depends on market conditions
- Currently blocked: all chains have best_net_pnl_bps < 0

---

> [!] **ROLLING STABILITY (2026-03-19 R28.25)**: R28.25 code changes: roundtrip_truth_status elevated to compute_status(), filter funnel propagated to start.py, suppression reformed (probation mode). Config aligned all chains. 1961 tests PASS. No fresh scan yet — pending verification.
> R28.24: Deep pipeline analysis. Phantom spread root cause. Filter funnel artifact. 37-run scan, gap=15.38bps.
> R28.23: Lead config audit. 8 configs regenerated. +FusionX V3 mantle. 240-run bundle. arb gap=10.62bps.
> R28.22-cont-2: Per-chain NO_USD_PRICE fixes (+14 tokens), zombie quarantine fix, 97.7-min bundle (406 runs). base 0→54 signals.
> R28.21: Cache freshness observability, all chains cache-backed (rpc=0), 0 profitable RT. Removed stale positive-control claims.
> R28.20: Lead post-verification directive (10 issues, 10 fix steps). warm_pool_cache+start.py tooling fixes. reject_histogram+reject_samples in truth artifacts. actionable_signals_count. mantle/scroll configs. Fresh 54-run online verification: 0 profitable RT confirmed.
> R28.19: best_net_pnl_bps sane filter fix (base 8e16 contamination blocked). +8 regression tests. Reject visibility in truth_report roundtrip_summary.
> R28.18: Code fixes for scroll price-truth blocker + promotion contract enforcement + fresh 10-min online evidence.
> R28.17: Truth-quality discipline. SUSPECT_ACCOUNTING state added. Accumulation guard rejects insane PnL. 3-tier signal classification. All chains reset to non-profitable.
> R28.15: Live execution infrastructure implemented (simulator.py, dex_dex_executor.py, providers.py) but dormant in production. Scanner wiring done. +38 tests.
> R28.11 Turn 2: Hot re-quote loop + WebSocket dirty-set invalidation — dual-cycle architecture.
> Earlier rounds: see Status_M5_0.md for full history.

**Economics Snapshot (2026-03-19, R28.23 — from 240-run long_scan, 60.5 min):**
| Metric | Value | Source |
|--------|-------|--------|
| `arb best_net_pnl_bps` | -21.19 bps | long_scan R28.23 (primary chain, ECONOMICS) |
| `arb sweep_best` | -10.62 bps @ $25 | long_scan R28.23 (gap_to_zero=10.62 bps — CLOSEST) |
| `linea best_net_pnl_bps` | -62.96 bps | long_scan R28.23 (ECONOMICS, 100% pass, cdx=4) |
| `zksync best_net_pnl_bps` | -130.31 bps | long_scan R28.23 (ECONOMICS, cdx=1) |
| `base best_net_pnl_bps` | 0.0 bps | long_scan R28.23 (QUOTE_PATH, VE33=29) |
| `mantle best_net_pnl_bps` | n/a | long_scan R28.23 (**NEW: 35 sig, 39 rq, FusionX works**) |
| `scroll best_net_pnl_bps` | n/a | long_scan R28.23 (DIAGNOSTIC, 0 rq, dead pools) |
| `total_profitable_roundtrips` | 0 | long_scan R28.23 (all chains) |
| `benchmark_chain` | None | long_scan R28.23 (no chain qualifies) |

**Rollout Queue (R28.23 — 240-run bundle, all chains blocked):**
| Priority | Chain | Status | Evidence |
|----------|-------|--------|----------|
| 1 | arbitrum_one | PRIMARY_BLOCKER | sig=1163, rq=172, cdx=8, prt=0, best=-21.19bps, gap=10.62bps |
| 2 | linea | PRIMARY_BLOCKER | sig=160, rq=160, cdx=4, prt=0, best=-62.96bps, 100% pass |
| 3 | zksync | PRIMARY_BLOCKER | sig=40, rq=80, cdx=1, prt=0, best=-130.31bps |
| 4 | base | PRIMARY_BLOCKER | sig=50, rq=52, cdx=0, prt=0, VE33_QUOTE_FAILED=29 |
| 5 | mantle | PRIMARY_BLOCKER | sig=35, rq=39, cdx=1, prt=0 (**NEW: FusionX V3 → SIGNAL_PRODUCING**) |
| 6 | scroll | CANDIDATE | sig=80, rq=0, cdx=2, prt=0, LIQUIDITY_ZERO=20, accepted_fail |

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
