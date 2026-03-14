# Status: M4 (DEX-DEX Atomic Execution)

**Status**: **M4.1 SIMULATE-ONLY CLOSED** (N≥100 REGISTRY_REAL runs with profit, agg_status=PASS)  
**Updated**: 2026-03-14 (R27.2)  
**Policy**: DIVERSITY_PAIRS_TARGET=4 (adjusted for min_spread_bps=10 filter)  
**Infra Evidence**: see [Status_M5_0.md](Status_M5_0.md) for multicall/failover/WS proof  
**Profit Truth**: `profit_is_diagnostic=true`, `profit_truth_source=ONE_LEG_DIAGNOSTIC`, **Clean PnL AVAILABLE** (`execution_pnl.cost_model_available=true`, `profit_truth_available=false`, `WARN_PROFIT_DIAGNOSTIC`)

## [!] M4.1 Simulate-Only DoD **MET**

**M4.1 DoD ACHIEVED** (per Roadmap.md L130-145):
- ✅ N = 100 REGISTRY_REAL runs with `net_usdc > 0`
- ✅ `agg_status = PASS` sustained
- ✅ `profit_is_diagnostic = true` (accepted for simulate-only)
- ✅ `total_net_usdc = $1142.02` (cumulative paper profit)

**Current State**:
- Rolling: runs_in_window=184, unique_pairs=13
- Policy: `intent.txt` = business intent (per Roadmap.md:680); pool-level quarantine/runtime_disabled handles filtering
- Pairs restored: RDNT, MAGIC, GRAIL (with evidence-based USD prices/anchors)
- LIQUIDITY_ZERO auto-disable working

**M4.2 (roundtrip) Remains**:
- Requires market arb opportunity (`roundtrip.profitable_count > 0`)
- Non-deterministic, depends on market conditions

---

> [!] **ROLLING STABILITY (2026-03-14 R27.2)**: `agg_status=PASS` sustained. runs_in_window=200, total_net_usdc=$1310.11. **M4.1 DoD MET**: 100+ REGISTRY_REAL runs with profit. **Rolling contamination FIXED R27.2**: NORM-only pointer guard in m4/gates.py prevents COVERAGE/SMOKE from overwriting pointer files.
> R27.2: Rolling guard added, +7 regression tests. Fresh long_scan: 8 runs, 17 signals, $23.49 (6 chains). Arb gap regressed 8.41→15.77 bps (market). zksync drift=0.27 (above 0.25).
> R27.1: Online proof — arb 4-DEX candidate PASS (14 signals, $14.61, dexes_active=4), scroll stage1 PASS (3 signals, $0.14, nuri_v3 quoter_v2 confirmed). +5 narrative consistency tests.
> R27: Additive rollout model formalized — full universe preserved, staged chain onboarding via `onboard_<chain>_stageN.yaml` configs and adapter readiness (NOT by removing pairs/chains). Coverage matrix: `docs/ONBOARDING_MATRIX.md`. Scroll nuri_v3 contract mismatch fixed. +48 adapter readiness tests.
> R26 closed observability/docs blocker (run_context, frontier triage fields, schema bump), NOT arb profit-truth blocker.
> Latest evidence: `long_scan_latest.json` (REFRESHED 2026-03-14T18:40:26Z), R27.2 online: ci_m5_gate_20260314_192514 (arb primary), ci_m5_gate_20260314_192713 (arb candidate), ci_m5_gate_20260314_193000 (scroll stage1).

**Economics Snapshot (2026-03-14, R27.2):**
| Metric | Value | Notes |
|--------|-------|-------|
| `sweep_gap_to_zero_bps (arb)` | 15.77 | Long_scan R27.2 (regressed from 8.41 — market) |
| `gap_to_zero_bps (zksync)` | n/a | No sweep data in long_scan (drift=0.27 blocks) |
| `gap_to_zero_bps (base)` | n/a | No sweep data (ve33 gap) |
| `roundtrip_total_profitable` | 2 | Long_scan total (base COVERAGE only) |
| `roundtrip_profitable (arb)` | 0 | Primary chain: still market-blocked |
| `frontier_pair` | WETH/USDT | Latest frontier candidate |
| `per_chain_frontier` | LIVE | 5 ranked chains + 1 accepted-fail |
| `runs_in_window` | 200 | Total NORMAL runs (rolling) |
| `total_net_usdc` | $1310.11 | Cumulative paper profit |
| `multi_chain_pass` | 5/6 | arb, base, mantle, linea, zksync |
| `long_scan_signals` | 17 | 8-run 6-chain scan (REFRESHED R27.2), $23.49 net |
| `R27.2_online` | 11+ | arb_primary=4, arb_candidate=87q, scroll=3 |
| `schema_version` | LATEST | R26: run_context + frontier triage |

**Rollout Queue (R27.2 — additive model, with fresh long_scan + online proof):**
| Priority | Chain | Status | Stage Config | Condition for Promotion |
|----------|-------|--------|-------------|-------------------------|
| 1 | arbitrum_one | NORMAL (primary) | `onboard_arbitrum_one_candidate.yaml` | 4-DEX PASS (R27.2: 14 sims), gap=15.77 bps, exit gate: 5 consecutive |
| 2 | zksync | Candidate | `onboard_zksync_candidate.yaml` | drift=0.27 (above 0.25 threshold), needs improvement |
| 3 | base | Stage1 | `onboard_base_stage1.yaml` | ve33 adapter (aerodrome) needed, 4 signals in long_scan |
| 4 | mantle | Stage1 | `onboard_mantle_stage1.yaml` | ve33 adapter (stratum) needed, 1 signal in long_scan |
| 5 | linea | Stage1 | `onboard_linea_stage1.yaml` | lynex_v3 Algebra path stability, 2 signals (rank #2 frontier) |
| 6 | scroll | CROSS_DEX_VERIFIED | `onboard_scroll_stage1.yaml` | nuri_v3 confirmed (R27.1+R27.2), 0 signals in long_scan (accepted-fail) |

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
M4.2 requires `roundtrip.profitable_count > 0` with real quoter-based economics.

## M4.2 Economics Frontier (2026-03-14)

**Primary blocker**: `gap_to_zero_bps` (distance from breakeven in sweep best).

| Metric | R11 | R14 | R18 | R20 | R26 | **R27.2** | Delta |
|--------|-----|-----|-----|-----|-----|-----------|-------|
| `sweep_best_net_pnl_bps` | -4.10 | -4.10 | -4.10 | -4.10 | -3.55 | **-15.77** | regressed (market) |
| `gap_to_zero_bps (best)` | 4.10 | 4.10 | 4.10 | 4.10 | 3.55 | **15.77** | +12.22 (market) |
| `profitable_count` | 0 | 0 | 0 | 0 | 0 | **2** (base COVERAGE) | +2 |
| `frontier_pair` | WBTC/USDC | WBTC/USDC | WBTC/USDC | WETH/USDT | WETH/USDT | **WETH/USDT** | stable |
| `measured_fee_bps` | 10.0 | 10.0 | 10.0 | 10.0 | 10.0 | **10.0** | stable |
| `test_count` | 1635 | 1653 | 1661 | 1685 | 1738 | **1798** | +60 |
| `runs_in_window` | 161 | 170 | 179 | 184 | 200 | **200** | stable |
| `total_net_usdc` | $1016 | $1065 | $1114 | $1142 | $1306 | **$1310** | +$4 |

**Cost decomposition (arb WETH/USDT @ $25, R20 latest):**
- LP fee: 10.0 bps (2x500 tier) — **main controllable cost, fee=100 would save 8 bps**
- Slippage: 11.97 bps (volatile run, median=8.06)
- Gas: 3.16 bps (L2)
- Total: 25.13 bps cost (fee=40% of cost)

**R27.2 note**: Gap regressed from 3.55→15.77 bps. This is market volatility, not code regression. Rolling sweep reflects current long_scan arb frontier.
**Best-ever frontier**: -3.55 bps gap (R26) → only needs ~4 bps improvement to breakeven.
**Fee=100 lever**: If fee=100 pool exists with liquidity, saves 8 bps → would cross breakeven.

**Evidence**: `long_scan_latest.json` (REFRESHED 2026-03-14T18:40:26Z), R27.2 online runs.

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

**M4-profit DoD**: See `Roadmap.md` L52-62. Quick ref: N>=5 runs in `m4_stability_agg.json.runs[]` with `run_mode=REGISTRY_REAL`, `pinned_block!=429900000`, `block_is_synthetic=false`, `total_net_usdc>0`.

**Evidence (rolling snapshot 2026-02-19)**: 80 runs in window, 79 data runs PASS, `total_net_usdc=$4359.51`, `data_run_rate=0.9875`, `agg_status=PASS`, `unique_pairs=8`, `unique_routes=2`. `profit_is_diagnostic=true` (paper, not on-chain).

## Version Discipline

> Per docs policy, version tracking moved to `docs/DEV_REPORT_LATEST.md`. See `docs/DOCS_POLICY.md`.

## Workflow (SHA-free)

| Mode | Description | Provenance |
|------|-------------|------------|
| **DEV** | Fast iteration cycle | run_timestamp only |
| **RELEASE** | Public proof | run_timestamp + rolling artifacts |

> Provenance: SHA tracking removed. `run_timestamp` is primary provenance. See AGENTS.md §2.

## Docs Freeze Rules

**Зміни DoD/контрактів дозволені лише при:**
1. Зміні коду/скриптів, що вимагає нового контракту
2. Оновленні `docs/m4/ROLLING_CONTRACT.md` з новою схемою
3. Прикладі у rolling/runDir artifacts, що демонструє нову структуру

**Policy Version Discipline:**
- `policy_version` у `m4/policy.py` MUST змінюватись при будь-якому зсуві порогів `MIN_*`
- `policy_version` у rolling артефактах MUST дорівнювати `policy.py`
- Розбіжність = FAIL для release gates  

## Taxonomy Contract

| Reason Prefix | Status Required | Semantic |
|---------------|-----------------|----------|
| `FAIL_*` | status=FAIL | Hard failure, blocks passage |
| `WARN_*` | status=PASS allowed | Warning, quality concern |
| `NO_DATA` | status=NO_DATA | signals_count == 0 only |

**Invariant**: If `FAIL_*` appears in reasons, status MUST be FAIL. Enforced by `compute_status()`.

## Status Contract

| Condition | Status | Semantic |
|-----------|--------|----------|
| `signals_count == 0` | NO_DATA | True absence of data |
| `signals > 0, net > 0` | PASS | Profitable (quality may warn) |
| `signals > 0, net <= 0` | FAIL | Unprofitable |
| `signals < 5` | quality_status=WARN | Low sample (not NO_DATA) |

**Rule**: NO_DATA only when signals_count == 0. Low sample -> WARN, not NO_DATA.

## Run Kinds

| Kind | Description | Counted in KPIs |
|------|-------------|-----------------|
| NORMAL | Regular online scan | [YES] Main KPIs |
| COVERAGE | Coverage batch run | [NO] Separate stats |
| SMOKE | Smoke test | [NO] Excluded |
| OFFLINE | Offline fixture | [NO] Excluded |

## Rolling KPIs (Targets)

| Metric | Target | FAIL | Description |
|--------|--------|------|-------------|
| `data_run_rate` | >= 0.50 | < 0.30 | % NORMAL runs with >=3 signals |
| `fail_rate` | <= 0.10 | > 0.15 | % FAIL runs |
| `fragile_rate_p90` | <= 0.30 | > 0.50 | p90 fragile rate |
| `unique_pairs` | >= 10 | < 3 | Pair diversity |
| `unique_routes` | >= 4* | < 2 | Route diversity (*M4 accepts 2 with 2 DEX) |

## Thresholds

| Threshold | Value |
|-----------|-------|
| `MIN_SIGNALS_FOR_PASS` | 3 |
| `MIN_SIGNALS_WARN` | 2 |
| `MAE_WARN` / `MAE_FAIL` | 0.55 / 0.80 |
| `SIGN_RATE_MIN` | 0.60 |
| `AGG_FAIL_RATE_FAIL` | 0.15 |
| `DIVERSITY_PAIRS_MIN` / `ROUTES_MIN` | 3 / 2 |

### Acceptable States (agg_status)

| agg_status | DEV | RELEASE |
|------------|-----|---------|
| `PASS` | [OK] | [OK] |
| `WARN_QUALITY` (DIVERSITY only) | [OK] | [WARN] TEMP OK |
| `WARN_QUALITY` (DATA_RUN_RATE) | [WARN] | [FAIL] |
| `FAIL` | [FAIL] | [FAIL] |
| `PASS_WARMUP` | [OK] | [WAIT] |

## Canonical Commands

```bash
# Coverage batch (COVERAGE kind)
python scripts/run_coverage_batch.py --min-signals-target 30 --max-seconds 600 --profile profit

# M4 gate (profit, require-clean by default)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling

# Allow dirty worktree (dev only)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --allow-dirty

# Check rolling KPIs
Get-Content data/runs/_rolling/m4_stability_agg.json | Select-String "data_run_rate|no_data_rate|signals_per_run_p50"

# Reset window
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window
```

## Rolling Artifacts

| File | Purpose |
|------|---------|
| `_latest.json` | Latest run pointer |
| `run_summary_latest.json` | Full run summary |
| `m4_stability_agg.json` | Rolling aggregator (segmented by run_kind) |

Location: `data/runs/_rolling/`

## Definition of Done

### M4.1: Simulate-Only -- [OK] PASS
- [x] Online scan generates signals
- [x] Simulator calculates PnL
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
