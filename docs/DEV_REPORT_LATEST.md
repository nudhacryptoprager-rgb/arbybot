# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_525_300b / m7a_525_300b_b / m7a_525_1000b
mode: ONLINE (evidence runs + unit tests)
artifact_mode: local evidence (data/tmp/m7a_525_*.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-04-02T23:00:00Z
  dirty: true
  desc: M7.A.5.25 — detection-time low-lag truth; PRICING_ANOMALY reject; hidden latency telemetry; 7 new tests; 18 assertion updates; ~50 fixture updates
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275
rolling_run_timestamp: 2026-03-27T21:30:14Z
note: rolling artifacts predate this session; not regenerated; session evidence is in data/tmp/m7a_525_*

## Session Completion
session_goal: M7.A.5.25 — correct broken detection-time low-lag accounting; add PRICING_ANOMALY reject for absurd net_bps; add hidden latency telemetry (registry_preload_ms, oracle_ms, admission_ms); honest correction of M7.A.5.24 "event arrival latency bottleneck" misdiagnosis
goal_status: REACHED (all 4 fixes implemented; 3 evidence runs confirm detection-time metrics now correct; PRICING_ANOMALY catches 4/100 events; hidden latency reveals registry_preload as dominant bottleneck; 3317 pass; all CI gates pass)
close_allowed: true
remaining_blockers: viable_count=0 (all positives are STALE_POSITIVE — detected at same block but stale by scoring completion); scoring pipeline latency (~1500-2000ms) exceeds block_time_ms (250ms); registry_preload (~372ms mean) is primary hidden latency source
evidence_session_run_dirs: [data/tmp/m7a_525_300b.json, data/tmp/m7a_525_300b_b.json, data/tmp/m7a_525_1000b.json]
primary_blocker_of_session: broken low-lag accounting (events_detected_low_lag=0 when 100% of events are genuinely same-block-detected) + pricing anomaly pollution (best_net=+154955 bps from thin-liquidity local pricing)
blocker_status_before: ACTIVE (broken accounting since M7.A.5.13; pricing anomaly since M7.A.5.20)
blocker_status_after: RESOLVED (detection-time lag fix: events_detected_low_lag=N/N in all runs; PRICING_ANOMALY catches 4/100 absurd results; hidden latency measured and documented)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.25 — detection-time low-lag truth + PRICING_ANOMALY + hidden latency telemetry
change_summary:
  - m7/orderflow/artifacts.py (MODIFIED): Added _detection_lag(r) helper (event_detected_at_block - event_block). _low_lag_all uses detection-time lag. positive_net_count_low_lag uses detection-time lag. stale_positive_count retains final lag.
  - m7/orderflow/mode_ws_live.py (MODIFIED): Added _det_lag(r) helper. same_block_count, next_block_count, stale_count, low_lag subset, stale subset all use detection-time lag instead of same_state_class.
  - m7/shared/constants.py (MODIFIED): Added REJECT_PRICING_ANOMALY. ALL_REJECT_REASONS 20→21.
  - m7/orderflow/scoring_parallel.py (MODIFIED): PRICING_ANOMALY gate (abs(net_bps) > 10000) in success path and mid-pipeline abort. Hidden latency: admission_ms, oracle_ms, registry_preload_ms in stage_latency.
  - tests/unit/test_orderflow_m7a524.py (MODIFIED): 7 new tests (TestPricingAnomalyReject: 4, TestDetectionTimeLag: 3).
  - 12 test files: 18 assertions updated (ALL_REJECT_REASONS == 20 → == 21).
  - 5 test files: ~50 fixtures updated with event_block/event_detected_at_block fields.
touched_files:
  - m7/orderflow/artifacts.py (MODIFIED: detection-time lag)
  - m7/orderflow/mode_ws_live.py (MODIFIED: detection-time lag)
  - m7/shared/constants.py (MODIFIED: +1 reject reason)
  - m7/orderflow/scoring_parallel.py (MODIFIED: PRICING_ANOMALY + telemetry)
  - tests/unit/test_orderflow_m7a524.py (MODIFIED: +7 tests)
  - tests/unit/test_orderflow_m7a520.py (MODIFIED: assertion update)
  - tests/unit/test_orderflow_m7a521.py (MODIFIED: assertion update)
  - tests/unit/test_orderflow_m7a522.py (MODIFIED: assertion update)
  - tests/unit/test_orderflow_m7a523.py (MODIFIED: assertion + fixtures)
  - tests/unit/test_orderflow_m7a511_512.py (MODIFIED: 4 assertion updates)
  - tests/unit/test_orderflow_base.py (MODIFIED: assertion + comment)
  - tests/unit/test_orderflow_m7a516_517.py (MODIFIED: assertions + fixtures)
  - tests/unit/test_orderflow_m7a513_515.py (MODIFIED: assertions + fixtures)
  - tests/unit/test_orderflow_m7a59_510.py (MODIFIED: assertion + fixtures)
  - tests/unit/test_orderflow_m7a518_519.py (MODIFIED: assertion + fixtures)
  - tests/unit/test_orderflow_m7a55_56.py (MODIFIED: assertion update)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.25 section + M7.A.5.24 correction)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3317 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest + docs_consistency + status_m4_check + m5_0_offline + m4_smoke + m4_profit: ALL REQUIRED GATES PASSED)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --ws-timeout 360 --max-events 30 --output data/tmp/m7a_525_300b.json: PASS
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --ws-timeout 360 --max-events 30 --output data/tmp/m7a_525_300b_b.json: PASS
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 1000 --ws-timeout 600 --max-events 100 --output data/tmp/m7a_525_1000b.json: PASS

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_525_300b.json (300-block ws-live, 21 events, events_detected_low_lag=21, best_net=+14.05 bps)
  - data/tmp/m7a_525_300b_b.json (300-block ws-live, 30 events, events_detected_low_lag=30, best_net=+66.62 bps)
  - data/tmp/m7a_525_1000b.json (1000-block ws-live, 100 events, events_detected_low_lag=100, PRICING_ANOMALY=4, best_net=+66.62 bps)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json (run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275)
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results — M7.A.5.25

### CORRECTION: M7.A.5.24 "Event Arrival Latency Bottleneck" Was Wrong

M7.A.5.24 concluded: "events arrive already stale (mean_block_lag=209-460). This is a WebSocket event-fetching limitation."

**This was incorrect.** Raw artifact fields prove `event_detected_at_block == event_block` for 100% of events in ALL M7.A.5.24 runs. Events ARE detected at same block. The `events_detected_low_lag=0` metric was an artifact of broken accounting — `_lag(r)` used `block_lag` (= quote_finished_block - event_block, which includes 26-965 blocks of scoring time) instead of detection-time lag (= event_detected_at_block - event_block, which is always 0 for ws-live).

### Detection-Time Low-Lag Accounting: Fixed

| Metric | M7.A.5.24 (BROKEN) | M7.A.5.25 (FIXED) | Explanation |
|--------|---------------------|--------------------|-------------|
| events_detected_low_lag | 0 | 21/30/100 (100%) | Now uses detection-time lag |
| same_block_count | 0 | 21/30/100 (100%) | Now uses detection-time lag |
| positive_net_count_low_lag | 0 | 2/4/19 | Positives from same-block-detected events |
| stale_positive_count | unchanged | 2/4/19 | Same positives, stale at scoring completion |
| events_scored_low_lag | 0 | 21/30/100 | Scored events from detection-low-lag set |
| LOW_LAG_NONE_THIS_WINDOW | always active | no longer fires | Correct: events ARE low-lag at detection |

### PRICING_ANOMALY Reject: Active

| Run | PRICING_ANOMALY_count | Caught Events | abs(net_bps) | Pairs |
|-----|----------------------|---------------|-------------|-------|
| 300b | 0 | — | — | — |
| 300b_b | 0 | — | — | — |
| 1000b | 4 | SOL/USDC, SOL/0x03236ce8, SOL/#BTB, SOL/#BB | 10168-10198 | All SOL-paired, size_valid=false |

Threshold: `abs(net_bps) > 10000`. These are thin-liquidity local pricing artifacts. Previously counted as GAS_EXCEEDS_GROSS or STALE_POSITIVE, polluting signal metrics.

### Hidden Latency Telemetry: Registry Preload Is Dominant Bottleneck

Per-event latency breakdown (100-event sample from 1000b):

| Stage | Mean (ms) | Max (ms) | Notes |
|-------|-----------|----------|-------|
| admission_ms | 0 | 0 | In-memory check, instant |
| oracle_ms | 101 | 141 | Chainlink eth_call per event |
| registry_preload_ms | 372 | 1235 | **Primary hidden latency** |
| local_pricing_ms | 0 | 0 | In-memory V3/V2 math, instant |
| total pipeline_ms | 1500-2000 | 3000 | Sum of all stages |

**Finding**: Registry preload + oracle together account for ~470ms of pre-scoring latency. Block time on Arbitrum is 250ms. Even with zero-cost economics/gas calculation, the pipeline exceeds 1 block just from registry + oracle. To score within a single block, both need caching or amortization.

### Evidence Summary: 3 Runs

| Metric | 300b | 300b_b | 1000b |
|--------|------|--------|-------|
| events_count | 21 | 30 | 100 |
| events_detected_low_lag | 21 (100%) | 30 (100%) | 100 (100%) |
| events_scored_low_lag | 21 (100%) | 30 (100%) | 100 (100%) |
| positive_net_count_any | 2 | 4 | 19 |
| positive_net_count_low_lag | 2 | 4 | 19 |
| stale_positive_count | 2 | 4 | 19 |
| best_net_bps | +14.05 | +66.62 | +66.62 |
| PRICING_ANOMALY | 0 | 0 | 4 |
| GAS_EXCEEDS_GROSS | 19 | 26 | 77 |
| STALE_POSITIVE | 2 | 4 | 19 |
| viable_count | 0 | 0 | 0 |
| mean_registry_preload_ms | — | — | 372 |
| mean_oracle_ms | — | — | 101 |

## 5) Strategic Reading

1. **M7.A.5.24 misdiagnosis corrected**: "Event arrival latency bottleneck" was wrong. Events are 100% same-block-detected. The real bottleneck is **scoring pipeline latency** (registry_preload + oracle + RPC calls during scoring push events from fresh to stale).
2. **Detection-time accounting now correct**: `events_detected_low_lag` accurately reflects detection truth. All downstream metrics (low-lag debug rows, watchlist, pipeline stages, reject decomposition) now analyze the correct set of events.
3. **PRICING_ANOMALY eliminates noise**: 4/100 events in the 1000b run would have inflated positive counts with absurd +10000 bps values. They are now correctly rejected and excluded from signal metrics.
4. **Registry preload is the actionable bottleneck**: At 372ms mean (1235ms max), it consumes 1.5 blocks of scoring time before economics even begin. Caching across events within a session or prewarming popular pairs (already partially done in M7.A.5.24) should reduce this.
5. **Discovery is solved**: `registry_direct=100%` across all runs. Factory-driven pool discovery works. No further discovery investigation needed.
6. **viable_count remains 0**: All positives are STALE_POSITIVE — detected fresh, scored stale. Path to first viable event requires scoring within block_time_ms (250ms).

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 66 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (all m7/ modules ≤ 1100 lines)
test file size constraint: OK (all M7 test files ≤ 600 lines)

## 5.2) Blockers / Risks
- PRIMARY (changed): Scoring pipeline latency (~1500-2000ms) exceeds block_time_ms (250ms); registry_preload (~372ms) is the largest single contributor; to get first viable event, need pipeline under 250ms
- SECONDARY: All positives are STALE_POSITIVE — genuine edge detected but not capturable at current scoring speed
- RESOLVED: "Event arrival latency bottleneck" (M7.A.5.24) was WRONG — events are 100% same-block-detected; broken accounting fixed
- RESOLVED: Pricing anomaly pollution — PRICING_ANOMALY reject catches absurd net_bps from thin-liquidity pairs
- UNCHANGED: M4 baseline still negative; SUBGRAPH_API_KEY_REQUIRED persists; viable_count=0
- NEXT: (a) Cache registry_preload across events (session-level pair cache already exists but preload still makes RPC calls), (b) Cache oracle results for known tokens (Chainlink price unlikely to change within a session), (c) Measure total sub-block feasibility after optimization
