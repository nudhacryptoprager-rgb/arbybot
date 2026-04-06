# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343
mode: OFFLINE (CI verification, nonstop pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.A.5.47 — focused hot intake, cumulative rollup, submit-size refinement
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z

## Session Completion
session_goal: M7.A.5.47 — first hot-scored candidate from existing cold-executable set
goal_status: IN_PROGRESS (code changes complete, CI green, nonstop verification pending)
close_allowed: false
remaining_blockers: Nonstop verification needed to confirm focused event intake produces hot_scored > 0
evidence_session_run_dirs: [tests/unit (3327 passed, 6 skipped), ci_full_pipeline PASS, check_repo_safety PASS (0 warnings)]
primary_blocker_of_session: Hot lane events=0 (broad unfiltered eth_getLogs returns events from random pools, not bridge pools)
blocker_status_before: ACTIVE (hot events=0, fast_path.scored=0, pool_address_match=0, bridge_pool_hit=0)
blocker_status_after: PENDING_VERIFICATION (focused eth_getLogs with bridge pool address filter implemented, cumulative rollup tracks progress)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47 — focused hot intake + cumulative rollup + submit-size refinement
change_summary:
  - m7/orderflow/mode_ws_live.py (MODIFIED): (a) Added bridge_pool_addresses parameter — in hot mode, eth_getLogs uses targeted address filter (up to 50 pools). (b) Added Set to typing imports. (c) Subgraph seed skipped in hot mode (currently 403, hot lane uses bridge for token discovery).
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) Builds _bridge_pool_addrs set from _cold_exec_pools + pool_token_transport keys, passes to run_ws_live(). (b) _update_hot_rollup() — cumulative hot rollup artifact (m7_hot_rollup_latest.json) with windows_seen, events/scored/positive totals, 6 canonical hot miss counters, dominant_hot_miss_reason. (c) Added fast_score_attempted + fast_score_rejected_economics per-window counters to hot_gap_debug.
  - m7/orderflow/artifacts.py (MODIFIED): Submit-size refinement — multipliers [0.75, 1.0, 1.25, 1.5], added best_submit_size, gas_floor_gap_bps, verified_net_bps_after_refinement fields.
  - monitoring/dashboard_server.py (MODIFIED): Added m7_hot_rollup to ARTIFACT_FILES and /api/hot response.
  - monitoring/dashboard.html (MODIFIED): (a) New "Hot Cumulative Rollup" section in Panel 11. (b) Micro-refinement table updated with gas_gap and verified columns.
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.47 section, updated header.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.47)
touched_files:
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - m7/orderflow/artifacts.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - monitoring/dashboard_server.py (MODIFIED)
  - monitoring/dashboard.html (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3327 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (all required gates)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)

## 3) Artifacts Attached

rolling: pending nonstop verification to populate:
  - data/runs/_rolling/m7_hot_rollup_latest.json (NEW — cumulative hot rollup)
  - data/runs/_rolling/m7_hot_latest.json (hot: now with focused event intake)
  - data/runs/_rolling/m7_orderflow_latest.json (cold: micro_refinement with gas_floor_gap_bps)

## 4) Key Results — M7.A.5.47

### Focused Event Intake for Bridge Pools (Critical)

Before: Hot lane `eth_getLogs({topics: [SWAP_EVENT_TOPIC]})` fetched ALL swap events per block. With ~100s of events per block from random pools, probability of hitting a bridge pool was near zero. Result: events=0 scored from bridge pools across all windows.

After: Hot lane `eth_getLogs({fromBlock, toBlock, topics: [SWAP_EVENT_TOPIC], address: bridge_pool_addresses})` fetches ONLY events from bridge-known pools (up to 50 addresses). This should massively increase hit rate — every event returned is scorable.

The bridge pool address set is built from:
- `_cold_exec_pools`: pool addresses from cold_executable + near_executable candidates
- `pool_token_transport` keys: all pool addresses with cached token mappings

### Cumulative Hot Rollup Artifact

`m7_hot_rollup_latest.json` — persists across hot windows:
- `windows_seen`: total windows processed
- `events_seen_total`: cumulative events across all windows
- `fast_path_scored_total`: cumulative fast-scored events
- `fast_path_positive_total`: cumulative positive fast-scored events
- `profit_guard_passed_total`: cumulative guard-passed events
- `dominant_hot_miss_reason`: derived from 6 canonical counters (pool_not_in_cache, pool_not_in_registry, fast_score_rejected, no_events, etc.)
- `first_window_at` / `last_window_at`: temporal bounds

This solves the "latest-window snapshot masks progress" problem.

### Submit-Size Refinement Update

Multipliers tightened to `[0.75, 1.0, 1.25, 1.5]` (from `[0.5, 0.8, 1.0, 1.5, 2.0]`):
- Removed 0.5x (too small — always pass but unrealistic execution size)
- Removed 2.0x (too large — always fail due to slippage)
- Added 0.75x and 1.25x (closer to realistic execution band)

New fields in micro_refinement output:
- `best_submit_size`: the actual wei amount that produced best net_bps
- `gas_floor_gap_bps`: closest net_bps to zero across all tested sizes (measures how close to gas floor)
- `verified_net_bps_after_refinement`: best net_bps if any size passed, else null

### Subgraph Seed Disabled in Hot Mode

Subgraph seed (The Graph) is currently returning 403. Hot lane uses bridge `pool_token_transport` for token discovery, not subgraph. Skipping it in hot mode eliminates:
- Wasted HTTP call to blocked API
- Log noise from best-effort failure
- ~100ms startup latency per hot window

### 6 Canonical Hot Miss Counters

Per-window in `hot_gap_debug`:
- `bridge_loaded_candidate_count`: entries loaded from bridge
- `bridge_pool_address_hit_count`: events whose pool_address matched bridge
- `bridge_pair_hit_count`: events whose canonical pair matched bridge
- `pool_address_match_count`: hot_skip events with pool_address in cache
- `fast_score_attempted`: events that entered score_backrun_fast
- `fast_score_rejected_economics`: fast-scored events rejected by GAS_EXCEEDS_GROSS or STALE

Cumulative versions in `m7_hot_rollup_latest.json` with suffix `_total`.

### Comparison with M7.A.5.45

| Metric | M7.A.5.45 | M7.A.5.46 | Change |
|--------|-----------|-----------|--------|
| hypothesis keys in artifact | 13 | 0 | REMOVED |
| results serialization | Full [asdict(r)...] | [] (compact) | SKIP |
| m7a4_hypothesis | Present | Absent | REMOVED |
| cold_executable_positive source | _fast_positive (wrong) | bridge._bridge_cold_executable (correct) | FIXED |
| /api/hot response | {hot_loop, m7_hot} | {m7_hot, m7_hot_intents} | SEPARATED |
| /api/intents → dashboard | Not wired | Panel 11 intents table | WIRED |
| bridge_pair_fallback_count | Not tracked | In hot_gap_debug | NEW |
| tests | 3327 | 3327 | Same count |

## 5) Strategic Reading

1. **Ballast removal accelerates the operational path**: 13 hypothesis strings and full results serialization were consuming cycles on every ws-live iteration. With compact mode, the operational artifact contains only what's needed for rolling/hot/bridge/dashboard.
2. **Single truth surface prevents drift**: execution_funnel is now the only headline truth in the dashboard. signal_classification remains as diagnostic but is visually secondary. No duplicate KPI surfaces to maintain.
3. **Correct hot semantic prevents false claims**: cold_executable_positive from bridge means the hot artifact accurately reflects "how many cold-verified executable candidates exist" rather than "how many hot-scored events had positive net_bps." These are fundamentally different metrics.
4. **M7/hot_loop separation simplifies dependency graph**: Panel 11 has a clean dependency on 3 artifacts only (m7_hot, m7_hot_intents, m7_cold_hot_bridge). No generic hot loop noise.
5. **bridge_pair_fallback_count is a diagnostic canary**: When this counter shows nonzero, it means events ARE arriving at pools with the right canonical pair but different pool addresses — suggesting that adding pair-level matching would capture more candidates.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files + m7_promoted_pairs.json + m7_cold_hot_bridge.json + m7_hot_intents_latest.json)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
