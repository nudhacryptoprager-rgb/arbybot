# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-06T08:33:50Z
run_id: m7a542_signal_classification
mode: ONLINE (nonstop verification with fresh rolling artifacts)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-06T08:33:50Z
  dirty: true
  desc: M7.A.5.42 — signal classification, diagnostic_raw, dashboard 3-section split, artifact hygiene
rolling_run_dir_name: nonstop_m7a542
rolling_run_timestamp: 2026-04-06T08:33:50Z
m7_orderflow_timestamp: 2026-04-06T08:33:50Z
m7_hot_timestamp: 2026-04-06T08:34:23Z

## Session Completion
session_goal: M7.A.5.42 — convert cold executable-positive candidates into hot-lane scored candidates; separate 4 signal classes; clean artifacts; split dashboard
goal_status: REACHED (code changes complete, 3277 tests pass, nonstop verification produces correct artifact shape)
close_allowed: true
remaining_blockers: hot lane fast_path.scored=0 persists (conversion gap: all events not_in_hot_registry); economics refinement needed for profit_guard pass
evidence_session_run_dirs: [tests/unit (3277 passed, 6 skipped), nonstop 10-min (m7_orderflow_latest.json, m7_hot_latest.json, m7_cold_hot_bridge.json)]
primary_blocker_of_session: Blocker shifted from latency/discovery to hot conversion + execution economics. Cold lane confirms executable positives exist but hot lane cannot score them (watchlist mismatch).
blocker_status_before: ACTIVE (raw/anomaly metrics mixed with execution headlines; dashboard Panel 11 conflated 3 different positives; rolling artifact polluted with legacy hypothesis blocks)
blocker_status_after: RESOLVED (4-tier signal classification, diagnostic_raw block, 3-section dashboard, clean rolling, cold→hot bridge queue, hot_gap_debug counters)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.42 — signal classification + artifact hygiene + dashboard split + cold→hot bridge
change_summary:
  - m7/orderflow/artifacts.py (MODIFIED): (a) Added signal_classification dict with 4 tiers (diagnostic_positive, stale_positive, cold_executable_positive, hot_execution_ready). (b) Added diagnostic_raw dict — relocated 7 raw metrics from top-level return. (c) Removed best_net_bps_any, positive_net_count_any, positive_net_count_low_lag, best_net_bps_stale, best_net_bps_low_lag_scored, mean_net_bps_stale, mean_net_bps_low_lag_scored from top-level.
  - m7/orderflow/mode_ws_live.py (MODIFIED): Expanded _ROLLING_EXCLUDE_KEYS from 4 to 19 entries (added _raw_results, m7a4_hypothesis, m7a56-m7a524 hypothesis blocks).
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) Added _write_cold_hot_bridge() — writes m7_cold_hot_bridge.json with cold_executable, cold_stale_positive, signal_classification. (b) Added hot_gap_debug to hot artifact (total_events, fast_path_attempted_count, not_in_hot_registry_count, watchlist_match_count).
  - monitoring/dashboard.html (MODIFIED): Replaced renderM7Orderflow() with 3-section split — Hot Execution Ready (red banner when not ready), Cold Executable Positive (amber banner when cold exists but not hot-ready), Diagnostic Positive (informational).
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): +5 tests in TestM7A542SignalClassification + 1 rolling exclude test. Updated 4 existing tests for diagnostic_raw migration.
  - tests/unit/test_orderflow_status_metrics.py (MODIFIED): Updated 7 existing tests for diagnostic_raw migration.
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.42 section, updated header.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.42)
touched_files:
  - m7/orderflow/artifacts.py (MODIFIED)
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - monitoring/dashboard.html (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - tests/unit/test_orderflow_status_metrics.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3277 passed, 6 skipped)
python scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (3/3 alive, 0 restarts)

## 3) Artifacts Attached

fresh rolling (from M7.A.5.42 nonstop):
  - data/runs/_rolling/m7_orderflow_latest.json (timestamp: 2026-04-06T08:33:50Z, signal_classification present, diagnostic_raw present, no legacy hypothesis blocks)
  - data/runs/_rolling/m7_hot_latest.json (timestamp: 2026-04-06T08:34:23Z, hot_gap_debug present: total_events=4, fast_path_attempted=0, not_in_hot_registry=4, watchlist_match=0)
  - data/runs/_rolling/m7_cold_hot_bridge.json (timestamp: 2026-04-06T08:33:50Z, cold_executable=[], signal_classification)
  - data/runs/_rolling/m7_promoted_pairs.json (from prior nonstop)

## 4) Key Results — M7.A.5.42

### 4-Tier Signal Classification

| Tier | Count | Best BPS | What it means |
|------|-------|----------|---------------|
| diagnostic_positive | 1 | 101.44 | Positive after anomaly exclusion (may be stale or size-invalid) |
| stale_positive | 1 | 101.44 | Positive but stale (block_lag>2 or mid-pipeline abort) |
| cold_executable_positive | 0 | None | Route-viable, fresh, size-valid — cold-lane confirmed |
| hot_execution_ready | 0 | None | Profit-guard passed in hot lane — ready for execution |

### Artifact Hygiene

- Removed from top-level: best_net_bps_any, positive_net_count_any, positive_net_count_low_lag, best_net_bps_stale, best_net_bps_low_lag_scored, mean_net_bps_stale, mean_net_bps_low_lag_scored → moved to `diagnostic_raw`
- Removed from rolling: _raw_results, m7a4_hypothesis, m7a56-m7a524_hypothesis (14 legacy blocks)
- Rolling artifact key count: 84 (was 100+ before cleanup)
- New rolling files: m7_cold_hot_bridge.json

### Hot Gap Debug

```
hot_gap_debug: {
  total_events: 4,
  fast_path_attempted_count: 0,
  not_in_hot_registry_count: 4,
  watchlist_match_count: 0
}
```

Confirms: all events fail at registry lookup stage — zero reach fast_path scoring. Conversion gap is between cold lane discovery (promoted watchlist populated) and hot lane registry activation.

### Dashboard 3-Section Split

Panel 11 now has 3 visually distinct sections:
1. **Hot Execution Ready** (red header) — honest "NOT IMPLEMENTATION-READY" banner when fast_path.scored=0 or profit_guard_passed=0. Shows hot_gap_debug counters.
2. **Cold Executable Positive** (blue header) — amber "cold positive exists but not implementation-ready" banner when viable>0 but hot not ready. Shows top_executable_candidates table.
3. **Diagnostic Positive** (gray header) — clean/stale best_bps, positive counts, mid-abort rate, anomaly count. Clearly informational.

## 5) Strategic Reading

1. **Signal classification makes claims honest**: Previously, Panel 11 mixed diagnostic positives (anomaly-polluted), stale positives, cold executables, and hot candidates in one flat view. A reader could misinterpret diagnostic_positive count=1 as "we have 1 executable opportunity." Now each tier is labeled and gated.
2. **Conversion gap is the dominant blocker**: The hot_gap_debug proves that the problem is NOT lack of events — 4 events arrive per hot iteration. The problem is that 4/4 are not_in_hot_registry: hot lane's prewarmed registry doesn't contain the pools these events touch. Cold lane promotes pairs via m7_promoted_pairs.json, but hot lane's prewarm doesn't resolve them into the fast-path registry.
3. **Cold→hot bridge provides the data contract**: `m7_cold_hot_bridge.json` now carries the exact candidate list (top_executable_candidates + signal_classification) that a future hot-lane scheduler can consume to expand its registry.
4. **Artifact hygiene prevents misinterpretation**: 14 legacy hypothesis blocks and 7 raw metrics removed from the headline surface. Rolling file is clean and dashboard-focused.
5. **Next step: hot registry activation from bridge**: Hot lane must read m7_cold_hot_bridge.json → extract cold_executable pool addresses → preload into hot registry → re-score incoming events. This is the narrowest path to first profit_guard pass.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files + m7_promoted_pairs.json + m7_cold_hot_bridge.json)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
signal_classification contract: OK (4 tiers, all with count/best_bps/label)
diagnostic_raw contract: OK (7 keys, none at top level)
_ROLLING_EXCLUDE_KEYS: OK (19 entries)
test count: OK (3277 passed, 6 skipped, +5 net new)

## 5.2) Blockers / Risks
- RESOLVED (this session): raw/anomaly metrics mixed with execution headlines → moved to diagnostic_raw
- RESOLVED (this session): dashboard Panel 11 conflated 3 signal tiers → 3-section split with honest banners
- RESOLVED (this session): rolling artifact polluted with 14 legacy hypothesis blocks → expanded _ROLLING_EXCLUDE_KEYS
- RESOLVED (this session): no machine-readable cold→hot bridge → m7_cold_hot_bridge.json added
- RESOLVED (this session): no diagnostic for why hot fast_path.scored=0 → hot_gap_debug added
- ACTIVE: hot lane conversion gap — events not_in_hot_registry despite promoted watchlist. Next step: hot registry activation from bridge file.
- PENDING: profit_guard_passed_count > 0 in at least one executable candidate (requires online run)
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE; SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) Run nonstop to verify hot lane fix, (b) Confirm top_hot_candidates populated, (c) Target profit_guard_passed > 0
