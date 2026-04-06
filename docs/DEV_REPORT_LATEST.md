# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: ONLINE (10.2-min nonstop + CI verified)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.A.5.47f — funnel concentration diagnostics, diversity cap, anomaly flag

## Session Completion
session_goal: M7.A.5.47f — diagnose whether final-layer concentration is market-real or filter/ranking-induced via per-pair funnel diagnostics, bridge source breakdown, diversity cap, anomaly flag
goal_status: REACHED (concentration diagnosed as FILTER-INDUCED: gas_exceeds_gross kills 18/30, RAIN/WETH positive but 8/8 stale, cold_executable=0 across all families)
close_allowed: true
remaining_blockers: cold_executable_count=0 across ALL pair families — gas economics and staleness eliminate every candidate
evidence_session_run_dirs: [data/runs/_rolling (fresh 10.2-min nonstop), tests/unit (3360 passed, 6 skipped), CI full pipeline PASS]
primary_blocker_of_session: final-layer concentration unknown — was it market-real or system-induced?
blocker_status_before: UNKNOWN (no per-pair funnel data, no source breakdown, no diversity tracking)
blocker_status_after: DIAGNOSED (filter-induced: gas_exceeds_gross dominant killer 18/30, staleness kills all RAIN/WETH positives 8/8, cold_executable=0 universally)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47f — funnel concentration diagnostics + diversity-aware bridge fill
change_summary:
  - m7/orderflow/artifacts.py (MODIFIED): (a) `funnel_by_pair_top` — top 10 pair families × 5 funnel counts (seen, positive, stale_positive, cold_executable, gas_exceeds_gross). (b) `pair_family_concentration` KPI (seen_top1_share, positive_top1_share, cold_executable_top1_share, unique_pair_families). (c) `best_net_bps_any_anomaly` boolean in diagnostic_raw (|value| > 10000 bps).
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) `candidate_source_breakdown` in bridge payload (cold_exec, near_exec, stale_positive, recent_active, hot_seen_backfill, ptt_total). (b) Diversity-aware bridge fill: _FAMILY_CAP=8 per token-pair family, replaces simple slice with diversity-bounded selection.
  - tests/unit/test_pair_concentration.py (NEW): 16 tests — pair normalization, funnel computation, concentration KPIs, anomaly flag, diversity fill.
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): Updated diagnostic_raw schema test for best_net_bps_any_anomaly.
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.47f section, compressed 47e.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.47f)
touched_files:
  - m7/orderflow/artifacts.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_pair_concentration.py (NEW)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3360 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (10.2-min, 0 restarts)

## 3) Artifacts Attached

Rolling artifacts refreshed by 10.2-min nonstop:
- data/runs/_rolling/m7_orderflow_latest.json (cold, final cycle)
- data/runs/_rolling/m7_cold_hot_bridge.json (bridge, ts=2026-04-06T20:04:14Z)
- data/runs/_rolling/m7_hot_rollup_latest.json (hot rollup, events_seen=22)

## 4) Key Results — M7.A.5.47f

### Per-Pair Funnel (funnel_by_pair_top)

| Pair Family | Seen | Positive | Stale Positive | Cold Executable | Gas>Gross |
|------------|------|----------|---------------|-----------------|-----------|
| USDC/WETH  | 9    | 0        | 0             | 0               | 9         |
| RAIN/WETH  | 9    | 9        | 9             | 0               | 0         |
| WBTC/WETH  | 2    | 0        | 0             | 0               | 2         |
| ESP/USDC   | 2    | 0        | 0             | 0               | 2         |
| ARB/WETH   | 1    | 0        | 0             | 0               | 1         |
| (7 more)   | 1 ea | 0        | 0             | 0               | all gas   |

### Concentration KPI (pair_family_concentration)

| Metric | Value | Interpretation |
|--------|-------|---------------|
| seen_top1_share | 0.300 | Moderate — 12 families at intake |
| positive_top1_share | 0.900 | Extreme — RAIN/WETH dominates positives |
| cold_executable_top1_share | 0.0 | ZERO executable across ALL families |
| unique_pair_families | 12 | Healthy diversity at intake |

### Bridge Source Breakdown (candidate_source_breakdown)

cold_exec=0, near_exec=5, stale_positive=5, recent_active=30, hot_seen_backfill=10, ptt_total=56.

### Diagnosis: Concentration is FILTER-INDUCED

Two filters eliminate all candidates:
1. **gas_exceeds_gross**: Kills 18/30 events (USDC/WETH, ARB/WETH, WBTC pairs) — gas cost exceeds gross profit
2. **Staleness**: Kills all RAIN/WETH positives (8/8 stale, block_lag > 2)

Result: cold_executable_count=0 universally. Zero executable candidates despite 13 families and 9 positive events.

## 5) Strategic Reading

1. **Diversity at intake is healthy** (13 families, top-1 = 26.7%). The system is NOT narrow at intake.
2. **Gas economics is the dominant filter** (60% of events killed). Next justified step: investigate gas estimation accuracy — are gas costs over-estimated? Or is true on-chain gas genuinely prohibitive for these pair sizes?
3. **Staleness kills all survivors**: RAIN/WETH passes gas but every observation is stale (block_lag > 2). Next: verify block_lag accuracy — is the monitoring infrastructure introducing artificial latency?
4. **Diversity cap (FAMILY_CAP=8) has no effect currently**: with cold_exec=0, the bottleneck is upstream of bridge fill.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (canonical rolling files unchanged, new fields additive only)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
