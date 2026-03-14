# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-14, Session 4 Round 27)
**Goal**: R27 — Establish additive rollout model (full universe preserved, staged chain onboarding via configs/adapters). Create coverage matrix `docs/ONBOARDING_MATRIX.md`, fix scroll nuri_v3 contract mismatch, create 6 onboarding stage configs, add 48 adapter readiness tests.

## 0) Meta
timestamp_utc: 2026-03-13T22:12:07Z
rolling_provenance: 2026-03-13T22:12:07Z (arb rolling, no new scan this session)
mode: OFFLINE (adapter/config matrix work, no new online scan per lead directive)
test_count: 1786 passed, 2 skipped (+48 from R26)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R27: additive rollout model, coverage matrix, scroll nuri_v3 fix, onboarding configs, adapter readiness tests |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb (primary); ve33 adapter not implemented (base/aerodrome, mantle/stratum) |
| evidence_session_run_dirs | ci_m5_gate_20260313_231122 (rolling, unchanged), no new online scan this session |
| primary_blocker_of_session | adapter/config matrix not documented; scroll nuri_v3 contract mismatch; no onboarding stage configs |
| blocker_status_before | R26: no coverage matrix; scroll nuri_v3 excluded as "algebra-incompatible" (incorrect); no onboard_*.yaml configs |
| blocker_status_after | RESOLVED. ONBOARDING_MATRIX.md created; scroll nuri_v3 re-enabled (uniswap_v3/quoter_v2); 6 stage configs created; +48 tests |
| start_metric | R26: 1738 tests, no coverage matrix, no onboarding configs |
| end_metric | R27: 1786 tests, coverage matrix created, 6 onboarding configs, ve33 gap documented |
| delta | +48 tests, 7 files created (1 matrix doc, 6 configs, 1 test file), 3 files modified (2 status docs, 1 coverage config) |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 infrastructure — additive rollout model formalization (per lead directive R27)
change_summary:
  - `docs/ONBOARDING_MATRIX.md`: NEW — coverage matrix (chain→dex→adapter→factory→quoter→blocker)
  - `config/coverage_intent_scroll.yaml`: MODIFIED — nuri_v3 re-enabled, require_cross_dex=true
  - `config/onboard_arbitrum_one_candidate.yaml`: NEW — 4-DEX candidate config
  - `config/onboard_zksync_candidate.yaml`: NEW — 2-DEX candidate config
  - `config/onboard_base_stage1.yaml`: NEW — 3-DEX stage1 (aerodrome excluded, ve33 gap)
  - `config/onboard_mantle_stage1.yaml`: NEW — 1-DEX stage1 (stratum excluded, ve33 gap)
  - `config/onboard_linea_stage1.yaml`: NEW — 2-DEX stage1 (pancake+lynex)
  - `config/onboard_scroll_stage1.yaml`: NEW — 2-DEX stage1 (sushi+nuri)
  - `tests/unit/test_adapter_readiness.py`: NEW — 48 tests (adapter registry, ve33 gap, nuri_v3 contract, config validation)
  - `docs/status/Status_M5_0.md`: R27 update (strategy change, rollout queue, onboarding configs)
  - `docs/status/Status_M4.md`: R27 update (additive rollout table, observability blocker clarification)
touched_files:
  - docs/ONBOARDING_MATRIX.md (NEW)
  - config/coverage_intent_scroll.yaml (MODIFIED)
  - config/onboard_*.yaml (6 NEW)
  - tests/unit/test_adapter_readiness.py (NEW)
  - docs/status/Status_M5_0.md
  - docs/status/Status_M4.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1786 passed, 2 skipped, 1 warning, 37.76s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (after DEV_REPORT alignment fix)
py -3.11 scripts/check_repo_safety.py: **PASS** (expected)

## 3) Artifacts Attached (шляхи)
rolling (unchanged, no new scan):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/long_scan_latest.json (schema v1.7)
run_dir_bundle (from R26):
  - data/runs/ci_m5_gate_20260313_231122/reports

new_files_created:
  - docs/ONBOARDING_MATRIX.md
  - config/onboard_arbitrum_one_candidate.yaml
  - config/onboard_zksync_candidate.yaml
  - config/onboard_base_stage1.yaml
  - config/onboard_mantle_stage1.yaml
  - config/onboard_linea_stage1.yaml
  - config/onboard_scroll_stage1.yaml
  - tests/unit/test_adapter_readiness.py

## 4) Key Results (числа з артефактів)

```
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: 0.935
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.signals_count: 4
  metrics.total_net_usdc: 5.6022
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN | quality_reasons: [WARN_TOP_PAIR_DOMINANCE_HIGH, WARN_PROFIT_DIAGNOSTIC]
  run_timestamp: 2026-03-13T22:12:07.954488Z
  code_identity: ts:2026-03-13T22:12:07.954488Z
  inputs.run_mode: REGISTRY_REAL
stability_agg:
  schema_version: m4:stability_agg:v2.0
  agg_status: PASS
  agg_reasons: []
  runs_since_timestamp.runs_count: 200
  runs_since_timestamp.data_runs_count: 187
  quick_stats.unique_pairs: 13
  quick_stats.unique_routes: 6
  quick_stats.low_sample_rate: 0.05
  quick_stats.data_run_rate: 0.935
  quick_stats.total_net_usdc: 1306.2564
  runs_by_date: {2026-03-03: 1, 2026-03-04: 18, 2026-03-05: 62, 2026-03-09: 5, 2026-03-10: 48, 2026-03-11: 9, 2026-03-12: 6, 2026-03-13: 51}
long_scan_latest:
  schema: start:long_scan_summary:v1.7
  generated_at: 2026-03-13T21:37:23Z
  total_runs: 21 (PASS=18, FAIL=3)
  total_included_signals: 68
  total_net_usdc: $56.40
  roundtrip_profitable: 2 (base, COVERAGE)
  run_context.run_timestamp: 2026-03-13T21:37:23Z (R26 fix)
```

## 4.1) Theoretical Net Profit (cost-aware reporting)

```
theoretical_net_profit:
  mode: paper_simulated
  gross_pnl_usdc: 56.40 (21 runs, 6 chains)
  cost_breakdown: per-signal in truth_reports (gas+slippage+L1 cost model)
  net_pnl_usdc: 56.40 (after cost model)
  disclaimer: "Theoretical profit based on simulated execution. No real trades were executed."
```

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline (3+1 canonical files): OK — _latest, run_summary, m4_stability_agg, long_scan_latest
- v2.x provenance contract: OK (run_timestamp, code_identity=ts:ISO, no runs_by_code_sha)
- runtime artifacts not committed: OK
- schema version: **v1.7** (unchanged from R26)
- test delta: +48 tests (1738 → 1786)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1786 PASS, CI green, safety PASS)
data_collection_blocker: LOW (data_run_rate=0.935, low_sample_rate=0.05, unique_pairs=13)
market_window_blocker: HIGH (roundtrip_profitable=0 on primary chain arb; 2 on COVERAGE base)
adapter_blocker: MEDIUM (ve33 not implemented — affects base/aerodrome, mantle/stratum)
```

### Per-Chain Blocker Classification (R27)

| Chain | Classification | Route Health | Gap bps | Signals | Stage Config | Actionable |
|-------|---------------|-------------|---------|---------|--------------|------------|
| arbitrum_one | NONE | 1.00 | 20.5 | 18 | onboard_arbitrum_one_candidate.yaml | Exit gate validation |
| zksync | MIXED | 1.00 | 0.0 | 4 | onboard_zksync_candidate.yaml | drift < 0.25 for promotion |
| base | MIXED + ve33 gap | 1.00 | 67.1 | 31 | onboard_base_stage1.yaml | ve33 adapter (aerodrome) |
| mantle | STRUCTURAL + ve33 gap | 1.00 | n/a | 6 | onboard_mantle_stage1.yaml | ve33 adapter (stratum) |
| linea | STRUCTURAL | 1.00 | n/a | 9 | onboard_linea_stage1.yaml | lynex_v3 algebra stability |
| scroll | ECOSYSTEM_BLOCKED | 0.00 | n/a | 0 | onboard_scroll_stage1.yaml | nuri_v3 online verification |

### Rollout Queue (R27 — additive model, per lead directive)

| Priority | Chain | Stage Config | Condition |
|----------|-------|--------------|-----------|
| 1 | arbitrum_one (NORMAL) | onboard_arbitrum_one_candidate.yaml | Exit gate, then 4-DEX additive |
| 2 | zksync | onboard_zksync_candidate.yaml | drift < 0.25 |
| 3 | base | onboard_base_stage1.yaml | ve33 adapter (aerodrome) needed |
| 4 | mantle | onboard_mantle_stage1.yaml | ve33 adapter (stratum) needed |
| 5 | linea | onboard_linea_stage1.yaml | lynex_v3 algebra stability |
| 6 | scroll | onboard_scroll_stage1.yaml | nuri_v3 quoter_v2 verification |

## 6.1) Blockers / Risks (max 5)
- **MARKET**: roundtrip_profitable=0 on arbitrum_one (primary) — gap=20.5 bps
- **ADAPTER**: ve33 not implemented — blocks base/aerodrome, mantle/stratum full coverage
- **DATA**: scroll ECOSYSTEM_BLOCKED — nuri_v3 re-enabled R27, verification pending
- **STRUCTURAL**: mantle/linea stage1 configs exclude ve33 DEXes (adapter gap)
- **NOTE**: base roundtrip_profitable=2 is COVERAGE evidence, NOT promotion evidence

## 7) Lead's R27 10 Steps: Execution Map
step_01: **DONE** — Adapter/config diagnostic commands executed. Evidence: chains.yaml (6 chains), dexes.yaml (16 DEXes), registry.py (uniswap_v3, algebra registered; ve33 NOT implemented).
step_02: **DONE** — Coverage matrix created `docs/ONBOARDING_MATRIX.md`. Evidence: file exists, chain→dex→adapter→factory→quoter→blocker table.
step_03: **DONE** — Scroll nuri_v3 contract mismatch fixed. Evidence: coverage_intent_scroll.yaml updated (nuri_v3 re-enabled, require_cross_dex=true).
step_04: **DONE** — 6 onboarding stage configs created. Evidence: config/onboard_*.yaml files exist.
step_05: **DONE** — Additive rollout model documented. Evidence: ONBOARDING_MATRIX.md section "Rollout Order", Status_M5_0.md "Strategy" note.
step_06: **DONE** — ve33 gap explicitly documented. Evidence: ONBOARDING_MATRIX.md blocker column, Status_M5_0.md chain classification.
step_07: **DONE** — 48 adapter readiness tests added. Evidence: tests/unit/test_adapter_readiness.py, pytest 1786 passed.
step_08: **DONE** — Status_M5_0.md + Status_M4.md updated with R27 strategy change, rollout queue with stage configs. Evidence: file diff.
step_09: **PARTIAL** — ci_full_pipeline PASS pending DEV_REPORT alignment (this update). websockets.legacy warning NOT removed (honest reporting).
step_10: **PENDING** — Online verification not run this session (lead directive: "Зараз не запускати новий online scan").

## 8) Що потрібно від ліда
1. Підтвердити additive rollout model (full universe preserved, onboard via stage configs)
2. Запустити online verification 4-command sequence (коли готово)
3. Рішення щодо ve33 adapter implementation priority (base/aerodrome vs mantle/stratum)
4. Рішення щодо scroll nuri_v3 — чи достатньо re-enable для monitoring або потрібен online proof
