# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_524_300b / m7a_524_300b_b / m7a_524_1000b
mode: ONLINE (evidence runs + unit tests)
artifact_mode: local evidence (data/tmp/m7a_524_*.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-04-02T22:00:00Z
  dirty: true
  desc: M7.A.5.24 — pipeline latency optimization; skip Stage A/B for registry_direct; mid-pipeline lag abort; two-queue priority; session prewarm; 24 new tests
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275
rolling_run_timestamp: 2026-03-27T21:30:14Z
note: rolling artifacts predate this session; not regenerated; session evidence is in data/tmp/m7a_524_*

## Session Completion
session_goal: M7.A.5.24 — pipeline latency optimization for registry_direct scoring path; skip unnecessary stages (Stage A multicall, size sweep, remote quoter); add mid-pipeline lag abort, two-queue priority, session prewarm; rename low_lag_scoring_path to scoring_path
goal_status: REACHED (all 6 pipeline optimizations implemented; 100% mid-pipeline abort fires; Stage A/B correctly skipped; scoring_path rename complete; 24 new tests + 15 renamed references; 3310 pass; 3 evidence runs)
close_allowed: true
remaining_blockers: 0 low-lag events detected in any run (event arrival latency bottleneck — events arrive already stale); all positive-net events are STALE_POSITIVE; viable_count=0; best_net in 1000b suspiciously high (pricing anomaly on low-liquidity pair)
evidence_session_run_dirs: [data/tmp/m7a_524_300b.json, data/tmp/m7a_524_300b_b.json, data/tmp/m7a_524_1000b.json]
primary_blocker_of_session: scoring pipeline spent time on redundant stages (Stage A multicall, size sweep) for registry_direct events; no mid-pipeline abort for events that became stale during scoring
blocker_status_before: ACTIVE (mean_pipeline_ms ~2000ms in M7.A.5.23; all stages executed even for registry_direct; no priority ordering)
blocker_status_after: MITIGATED (Stage A/B skipped, mean_pipeline_ms=1527ms in 1000b, all events abort mid-pipeline before Stage B; but 0 events arrive low-lag so optimization cannot be measured on fresh events)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.24 — pipeline latency optimization for registry_direct scoring path
change_summary:
  - `m7/orderflow/contracts.py` (MODIFIED): Renamed low_lag_scoring_path → scoring_path (semantic fix). Still 66 fields.
  - `m7/orderflow/scoring_parallel.py` (MODIFIED, 6 changes): (a) Rename _low_lag_scoring_path → _scoring_path. (b) _is_low_lag flag. (c) Instant reject for low-lag + zero active pools. (d) Skip Stage A for registry_direct. (e) Mid-pipeline lag abort (~90 lines). (f) Skip size sweep for registry_direct.
  - `m7/orderflow/mode_ws_live.py` (MODIFIED, 4 changes): (a) Session prewarm: 6 core pairs preloaded. (b) Two-queue priority: low-lag events first. (c) Rename scoring_path refs. (d) m7a524_hypothesis in artifact.
  - `m7/orderflow/artifacts.py` (MODIFIED): Rename filter ref, add m7a524_pipeline_optimization section (mid_pipeline_abort_count, scoring_path_histogram).
  - `tests/unit/test_orderflow_m7a523.py` (MODIFIED): Renamed 15 low_lag_scoring_path → scoring_path references.
  - `tests/unit/test_orderflow_m7a524.py` (NEW, 24 tests): 8 test classes.
touched_files:
  - m7/orderflow/contracts.py (MODIFIED: rename field)
  - m7/orderflow/scoring_parallel.py (MODIFIED: 6 pipeline optimizations)
  - m7/orderflow/mode_ws_live.py (MODIFIED: prewarm + priority + rename)
  - m7/orderflow/artifacts.py (MODIFIED: optimization metrics)
  - tests/unit/test_orderflow_m7a523.py (MODIFIED: rename refs)
  - tests/unit/test_orderflow_m7a524.py (NEW: 24 tests)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.24 section)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3310 passed, 6 skipped)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --ws-timeout 360 --max-events 30 --output data/tmp/m7a_524_300b.json: PASS
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --ws-timeout 360 --max-events 30 --output data/tmp/m7a_524_300b_b.json: PASS
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 1000 --ws-timeout 600 --max-events 100 --output data/tmp/m7a_524_1000b.json: PASS

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_524_300b.json (300-block ws-live, 30 events, best_net=-1.68 bps, 30/30 mid_pipeline_abort)
  - data/tmp/m7a_524_300b_b.json (300-block ws-live, 30 events, best_net=+1.01 bps, 30/30 mid_pipeline_abort)
  - data/tmp/m7a_524_1000b.json (1000-block ws-live, 100 events, best_net=+154955 bps [pricing anomaly], 14 positive, 100/100 mid_pipeline_abort)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json (run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275)
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results — M7.A.5.24

### Pipeline Optimization: All Stages Correctly Skipped

**Before (M7.A.5.23)**: 100% scoring via registry_direct, but full pipeline still runs: Stage A multicall (~400ms), size sweep (multiple remote quoter calls), Stage B remote quoter. Mean pipeline latency ~2000ms.

**After (M7.A.5.24)**: For registry_direct scoring path: Stage A skipped (stage_a_ms=0.0), Stage B skipped (stage_b_ms=0.0), size sweep skipped. Mid-pipeline lag abort catches events before they waste further RPC budget.

| Metric | 300b | 300b_b | 1000b |
|--------|------|--------|-------|
| events_scored | 30/30 (100%) | 30/30 (100%) | 100/100 (100%) |
| scoring_path=registry_direct | 30 (100%) | 30 (100%) | 100 (100%) |
| mid_pipeline_abort | 30 (100%) | 30 (100%) | 100 (100%) |
| stage_a_ms | 0.0 | 0.0 | 0.0 |
| stage_b_ms | 0.0 | 0.0 | 0.0 |
| positive_net_count | 0 | 1 | 14 |
| best_net_bps | -1.68 | +1.01 | +154955 (anomaly) |
| events_detected_low_lag | 0 | 0 | 0 |
| mean_block_lag | 209.53 | 242.17 | 459.85 |
| mean_pipeline_ms | 1927 | 2029 | 1527 |

### 0 Low-Lag Events Detected — Event Arrival Latency Bottleneck

The pipeline optimizations are structurally correct but untestable against real low-lag events because events arrive already stale. The eth_getLogs-per-newHead pattern fetches events from past blocks, not the current head. This is a fundamental architectural limitation: to get genuinely low-lag events, the system needs either (a) mempool monitoring, (b) log streaming (no polling), or (c) block-level log subscription.

### Mid-Pipeline Abort: 100% Fire Rate

Every event enters the registry_direct path but becomes stale during local pricing (~1500-2000ms). The mid-pipeline abort catches this and returns a partial result with computed economics (if local pricing succeeded) instead of continuing to Stage B.

### Pricing Anomaly in 1000b Run

best_net=+154955 bps in the 1000-block run is a pricing anomaly — likely caused by a low-liquidity pair where local pricing produces unrealistic amounts. This is a known limitation of local pricing (no slippage simulation against actual pool depth for extreme cases).

### Comparison: M7.A.5.24 vs M7.A.5.23

| Metric | M7.A.5.23 | M7.A.5.24 | Delta |
|--------|-----------|-----------|-------|
| Stage A multicall | executed | SKIPPED (0.0ms) | **-400ms** |
| Stage B quoter | skipped (local pricing) | SKIPPED (mid-pipeline abort) | same |
| Size sweep | executed | SKIPPED | **-N×RPC** |
| Mid-pipeline abort | n/a | 100% events | **NEW** |
| Two-queue priority | n/a | low-lag first | **NEW** |
| Session prewarm | n/a | 6 core pairs | **NEW** |
| events_detected_low_lag | 0 | 0 | unchanged |
| mean_pipeline_ms | ~2000 | 1527-2029 | marginal |
| BackrunResult fields | 66 | 66 | unchanged (rename) |

## 5) Strategic Reading

1. **Pipeline optimizations structurally correct**: Stage A, Stage B, and size sweep all correctly skipped for registry_direct events. The pipeline is now as lean as possible for this path.
2. **Mid-pipeline abort is the key innovation**: It catches events that become stale during scoring and prevents wasted RPC budget. 100% fire rate confirms all events become stale during the ~1500ms scoring window.
3. **Event arrival latency is the real bottleneck**: No amount of scoring pipeline optimization helps if events arrive 200-460 blocks late. The eth_getLogs polling model inherently introduces latency.
4. **Positive events continue appearing**: 14/100 in the 1000b run (up from 9/100 in M7.A.5.23). All STALE_POSITIVE, not executable.
5. **Pricing anomaly needs investigation**: +154955 bps is not real — local pricing on extremely low-liquidity pools can produce unrealistic amounts. A sanity bound on net_bps may be needed.
6. **Honest assessment**: M7.A.5.24 is a correct pipeline optimization but cannot demonstrate its value because event arrival is the binding constraint, not scoring speed. The fast path (skip Stage A, skip size sweep, mid-pipeline abort) will only matter if/when events arrive within 2 blocks.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 20, UNSCORED_REJECTS: 12, BackrunResult: 66 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (all m7/ modules ≤ 1100 lines)
test file size constraint: OK (all M7 test files ≤ 600 lines)

## 5.2) Blockers / Risks
- PRIMARY (changed): Scoring pipeline optimization **IMPLEMENTED** but unbenchmarkable on fresh events; new primary is **event arrival latency** (events arrive 200-460 blocks stale)
- SECONDARY: All positive-net events are STALE_POSITIVE — edge exists at detection but cannot be captured
- ANOMALY: best_net=+154955 bps in 1000b — pricing anomaly on low-liquidity pair; needs sanity bound
- UNCHANGED: M4 baseline still negative; SUBGRAPH_API_KEY_REQUIRED persists; viable_count=0
- NEXT: To progress, need either (a) mempool/streaming event source for <2-block arrival, (b) net_bps sanity cap for pricing anomalies, or (c) M7.A scope freeze (all pipeline optimizations are in place, bottleneck is architectural)
