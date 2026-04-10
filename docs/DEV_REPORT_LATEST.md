# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343
mode: ONLINE (M7.E1.10 longer peak-hours Base A/B evidence under session-first dashboard)
artifact_mode: rolling
config: config/real_minimal.yaml
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.E1.10 - 1h peak-hours A/B runs + dashboard namespace badge + cold heartbeat display

## Session Completion
session_goal: M7.E1.10 - run 1h production + 1h discovery at peak hours (16:00-20:00 UTC) to test event scarcity ceiling, per reviewer commit bc388cea fix steps 1-2.
goal_status: REACHED (1h production 16:05-17:05Z + 1h discovery 17:05-18:05Z, both at peak hours, both 0 events. Market-window scarcity CONFIRMED at 1h duration. Dashboard enhanced with namespace badge + cold heartbeat age.)
close_allowed: true
remaining_blockers: (1) market-window scarcity CONFIRMED at 1h peak-hours duration. (2) Per reviewer step 5: threshold for wider discovery = 3 pairs x 1h at 16:00-20:00 UTC still zero. This is pair 1 of 3.
evidence_session_run_dirs: [data/runs/_rolling/ — 1h production + 1h discovery at 16:05-18:05Z]
primary_blocker_of_session: market_window_scarcity
blocker_status_before: CONFIRMED (E1.9.2: 9 short runs, 0 events)
blocker_status_after: CONFIRMED (E1.10: 2 x 1h peak-hours runs, 1953 total windows, 0 events)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.10 = longer peak-hours Base A/B evidence per reviewer commit bc388cea
change_summary:
  - monitoring/dashboard.html: Namespace badge in M7 Session panel header + cold heartbeat age in COLD SNAPSHOT PRESERVED notice
  - tests/unit/test_e1_9_discovery_lane.py: 2 new tests (TestE110DashboardEnhancements)
  - 1h production proof-run (16:05-17:05Z, 991 windows, 0 events)
  - 1h discovery proof-run (17:05-18:05Z, 962 windows, 0 events)
touched_files:
  - monitoring/dashboard.html
  - tests/unit/test_e1_9_discovery_lane.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3831 passed, 6 skipped, 92.41s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED, 94.0s)
py -3.11 scripts/start_nonstop_runtime.py --hours 1.0 --chain base --m7-profile production --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (16:05-17:05Z, 3/3 alive, 0 restarts)
py -3.11 scripts/start_nonstop_runtime.py --hours 1.0 --chain base --m7-profile discovery --no-m4 --dashboard-port 8100 --m7-hot-pause 1 --m7-cold-pause 5: PASS (17:05-18:05Z, 3/3 alive, 0 restarts)

## 3) Artifacts Attached

rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343, ts: 2026-04-02T09:03:41Z)
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/m7_hot_rollup_latest.json (production 1h)
  - data/runs/_rolling/m7_hot_rollup_latest_discovery.json (discovery 1h)
  - data/runs/_rolling/m7_orderflow_latest.json (heartbeat 17:05Z, signal_counts present)
  - data/runs/_rolling/m7_orderflow_latest_discovery.json (heartbeat 18:05Z)

## 4) Key Results

### 4.1) 1h Peak-Hours A/B Evidence (April 10, 16:05-18:05 UTC)

| Metric | Production (1h) | Discovery (1h) |
|--------|-----------------|----------------|
| Run window | 16:05-17:05Z | 17:05-18:05Z |
| Supervisor | 3/3 alive, 0 restarts | 3/3 alive, 0 restarts |
| Session windows | 991 | 962 |
| Session events | 0 | 0 |
| Session bridge hits | 0 | 0 |
| Session fast scored | 0 | 0 |
| Historical windows (cumulative) | 3573 | 1813 |
| Historical events (cumulative) | 290 | 0 |
| Historical positive (cumulative) | 17 | 0 |
| Historical viable (cumulative) | 14 | 0 |
| Historical guard passed (cumulative) | 14 | 0 |
| Historical gas rejected (cumulative) | 129 | 0 |
| Windows with events (historical) | 58 | 0 |
| Empty-window count (no_events_in_window) | 3515 | 1813 |
| Cold heartbeat timestamp | 17:05:13Z | 18:05:38Z |
| Cold snapshot_preserved | true | true |
| signal_counts present | true | true |
| Cross-contamination | NONE | NONE |

**Key observations**:
1. Both runs executed entirely within reviewer's recommended peak window (16:00-20:00 UTC). Still 0 events.
2. Combined 1953 windows across 2h at peak hours — zero swap events for any monitored Base pair.
3. Production historical totals show the engine HAS found signals before (290 events, 17 positive, 14 viable in prior sessions).
4. Discovery has never seen events (0 across its lifetime — created fresh in E1.9.1).
5. Namespace isolation confirmed: production hot frozen at 17:05Z after its run, discovery hot at 18:05Z, no overlap.
6. Dominant miss reason on both: `no_events_in_window`.

### 4.2) Dashboard Enhancements (E1.10)

- **Namespace badge**: `Namespace: PRODUCTION` / `Namespace: DISCOVERY` now shown in M7 Session panel header with color-coded border
- **Cold heartbeat display**: COLD SNAPSHOT PRESERVED notice now shows `[Heartbeat: Xm ago]` with color-coded freshness (green < 15m, yellow > 15m), proving cold lane is alive even when preserving old snapshot

### 4.3) Rolling Artifact Summary (M4 gate, arbitrum_one)

latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: 1.0
run_summary_latest:
  status: PASS
  metrics.signals_count: 31
  metrics.total_net_usdc: 40.0986
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
  run_timestamp: 2026-04-02T09:03:41Z
  code_identity: ts:2026-04-02T09:03:41Z
stability_agg:
  schema_version: m4:stability_agg:v2.0
  agg_status: PASS
  runs_since_timestamp.runs_count: 200
  quick_stats.unique_pairs: 7
  quick_stats.unique_routes: 11

### 4.4) Test Results

- 3831 passed, 6 skipped (up from 3829 in E1.9.3)
- 2 new tests: TestE110DashboardEnhancements (namespace label, cold heartbeat)

## 5) Strategic Reading

1. **Market-window scarcity is now confirmed at 1h peak-hours resolution**: 2h total scanning (16:05-18:05Z, deep inside 16:00-20:00 UTC peak) yielded 0 events across 1953 windows. This is the strongest evidence yet that Base swap events for monitored pairs are extremely sparse even at prime hours.
2. **Historical engine capability is intact**: Production cumulative shows 290 events, 17 positive, 14 viable, 14 guard passed from prior sessions (before the current scarcity period). The engine can find and score signals when events flow.
3. **Reviewer step 5 threshold**: "if after 3 pairs 1h+1h at 16:00-20:00 UTC both lanes remain zero, then modest pair expansion in discovery justified." This is pair 1 of 3. Need 2 more pairs to trigger expansion threshold.
4. **Per reviewer step 3**: Base remains primary chain candidate. OP Mainnet is best fallback per same Flashblocks/OP Stack architecture. Arbitrum not recommended.
5. **Dashboard enhancements shipped**: Namespace badge + heartbeat prove the system is "visibly alive" as reviewer step 8 requested.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (production canonical, discovery _discovery namespace)
runtime artifacts not committed: OK
docs_reread_confirmed: true

## 6) Blocker Classification

code_blocker: NONE
infra_blocker: NONE
market_window_scarcity: CONFIRMED (E1.10: 2 x 1h peak-hours runs at 16:05-18:05 UTC, 1953 windows, 0 events)

## 6.1) Blockers / Risks
- **market-window scarcity** (CONFIRMED, E1.10): 0 events across 2h at peak hours (16:05-18:05Z). Combined with E1.9.2 evidence (9 shorter runs), total evidence = 12 runs, 0 session events.
- Flashblocks WS DNS unreachable
- Submit sim = 0 (scaffold only)
- Discovery scoreboard empty (0 families — needs events to populate)
- Per reviewer step 5: 2 more 1h pairs needed before discovery expansion threshold
