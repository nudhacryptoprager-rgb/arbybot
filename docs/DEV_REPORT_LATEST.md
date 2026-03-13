# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-13, Session 4 Round 26)
**Goal**: R26 AUDIT — Add `run_context.run_timestamp` to long_scan provenance, enrich `frontier_ranking` with triage fields (status, route_health, blocker_classification, blocker_reason), define rollout queue, freeze arbitrum_one as sole NORMAL chain. 21-run 6-chain verification scan.

## 0) Meta
timestamp_utc: 2026-03-13T21:34:36Z
rolling_provenance: 2026-03-13T21:37:23Z (6-chain, 21 runs)
mode: ONLINE
test_count: 1738 passed, 2 skipped (+5 from R25)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R26: add run_context provenance to long_scan, enrich frontier_ranking with triage fields, define rollout queue |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb (primary); scroll ECOSYSTEM_BLOCKED |
| evidence_session_run_dirs | ci_m5_gate_20260313_221453 (M5+M4 online), 21 runs across 6 chains (long scan), last=ci_m5_gate_20260313_223350 |
| primary_blocker_of_session | long_scan_latest.json lacked `run_context.run_timestamp`; frontier_ranking lacked triage fields for promotion decisions |
| blocker_status_before | R25: no run_context in long_scan (provenance gap); frontier_ranking had gap_to_zero but no status/route_health/blocker fields |
| blocker_status_after | RESOLVED. run_context.run_timestamp added; frontier_ranking enriched with 5 triage fields; schema v1.7 |
| start_metric | R25: 1733 tests, v1.6 schema, no run_context, no triage fields |
| end_metric | R26: 1738 tests, v1.7 schema, run_context present, 5 triage fields in frontier_ranking |
| delta | +5 tests, 2 files modified, schema v1.6→v1.7, run_context added, frontier triage fields added |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 infrastructure hardening — provenance + triage (per lead audit R26)
change_summary:
  - `start.py build_summary()`: added `run_context` block (run_timestamp, code_identity ts:<ISO>, code_sha=null, evidence_sha=null)
  - `start.py _compute_frontier_ranking()`: added 5 triage fields: status, route_health, chain_quality_level, blocker_classification, blocker_reason
  - `start.py`: schema bump v1.6 → v1.7
  - `tests/unit/test_start.py`: +5 tests (TestRunContextProvenance: 2, TestFrontierTriageFields: 3), 2 schema version assertions updated
  - `docs/status/Status_M5_0.md`: R26 update with fresh evidence
  - `docs/status/Status_M4.md`: R26 update, rollout queue defined, economics snapshot refreshed
touched_files:
  - start.py
  - tests/unit/test_start.py
  - docs/status/Status_M5_0.md
  - docs/status/Status_M4.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1738 passed, 2 skipped, 1 warning, 30.18s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (ALL REQUIRED GATES PASSED, 30.8s)
py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: **PASS** (5 cycles, runDir ci_m5_gate_20260313_221453)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --run-dir data/runs/ci_m5_gate_20260313_221453: **PASS**
py -3.11 start.py (6-chain long scan): **21 runs** (18 PASS, 3 AF scroll), 68 signals, $56.40 net

## 3) Artifacts Attached (шляхи)
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/long_scan_latest.json (schema v1.7, run_context present)
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_20260313_221453/reports
  - data/runs/ci_m5_gate_20260313_223350/reports

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
  run_timestamp: 2026-03-13T21:34:36.973024Z
  code_identity: ts:2026-03-13T21:34:36.973024Z
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
- schema version: **v1.7** (bumped from v1.6)
- test delta: +5 tests (1733 → 1738)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1738 PASS, CI green, safety PASS, 0 warnings)
data_collection_blocker: LOW (data_run_rate=0.935, low_sample_rate=0.05, unique_pairs=13)
market_window_blocker: HIGH (roundtrip_profitable=0 on primary chain arb; 2 on COVERAGE base)
```

### Per-Chain Blocker Classification (R26)

| Chain | Classification | Route Health | Gap bps | Signals | Actionable |
|-------|---------------|-------------|---------|---------|------------|
| zksync | MIXED | 1.00 | 0.0 | 4 | drift_rejection_rate_median < 0.25 for promotion |
| arbitrum_one | NONE | 1.00 | 20.5 | 18 | Fee=100 pool discovery |
| base | MIXED | 1.00 | 67.1 | 31 | quality/mixed-source cleanup; rt_profitable=2 detected |
| mantle | STRUCTURAL | 1.00 | n/a | 6 | Wait for 2nd DEX |
| linea | STRUCTURAL | 1.00 | n/a | 9 | Wait for 2nd DEX |
| scroll | ECOSYSTEM_BLOCKED | 0.00 | n/a | 0 | Do not invest engineering time |

### Rollout Queue (per lead directive R26)

| Priority | Chain | Condition |
|----------|-------|-----------|
| 1 | arbitrum_one (NORMAL) | Must pass exit gate before others promoted |
| 2 | zksync | drift < 0.25 |
| 3 | base | quality cleanup, gap reduction |
| 4 | mantle/linea | COVERAGE only (no cross-DEX) |
| 5 | scroll | monitoring_only (ECOSYSTEM_BLOCKED) |

## 6.1) Blockers / Risks (max 5)
- **MARKET**: roundtrip_profitable=0 on arbitrum_one (primary) — gap=20.5 bps
- **MARKET**: sweep_gap_to_zero_min=3.55 bps (rolling best, improved from 4.10)
- **DATA**: scroll ECOSYSTEM_BLOCKED — 0 signals, single DEX
- **STRUCTURAL**: mantle/linea lack cross-DEX surface (single DEX each)
- **NOTE**: base detected 2 profitable roundtrips (COVERAGE chain, not NORMAL)

## 7) Lead's Previous 10 Steps: Execution Map (R26 Audit)
step_01: **DONE** — test count corrected (1733→1738 after +5 new tests). Evidence: pytest 1738 passed.
step_02: **DONE** — run_context.run_timestamp added to build_summary() in start.py. Evidence: long_scan_latest.json has run_context block.
step_03: **DONE** — frontier_ranking enriched: status, route_health, chain_quality_level, blocker_classification, blocker_reason. Evidence: long_scan_latest.json frontier_ranking entries.
step_04: **DONE** — arbitrum_one frozen as sole NORMAL chain. Evidence: rollout queue in Status_M4.md, Status_M5_0.md.
step_05: **DONE** — rollout queue defined: arb→zksync→base. mantle/linea=COVERAGE, scroll=monitoring_only. Evidence: Status_M4.md Rollout Queue table.
step_06: **DONE** — schema bumped v1.6→v1.7 with R26 comment. Evidence: start.py line, test assertions.
step_07: **DONE** — 5 unit tests added (TestRunContextProvenance: 2, TestFrontierTriageFields: 3). Evidence: pytest 1738 passed.
step_08: **DONE** — ci_full_pipeline PASS + check_repo_safety PASS (0 warnings). Evidence: terminal output.
step_09: **DONE** — M5 online gate PASS (5 cycles, ci_m5_gate_20260313_221453) + M4 online gate PASS. Evidence: rolling artifacts updated.
step_10: **DONE** — 6-chain long scan: 21 runs, 18 PASS, 3 AF scroll, 68 signals, $56.40 net. Evidence: long_scan_latest.json (v1.7).

## 8) Що потрібно від ліда
1. Підтвердити rollout queue (arb→zksync→base) як офіційний порядок promotion
2. Визначити exit gate для arbitrum_one (N consecutive runs + criteria)
3. Рішення щодо base roundtrip_profitable=2 — чи варто підняти base у черзі пріоритетів
