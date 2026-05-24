# DEV REPORT LATEST — M9 Smoke25: 3/3 Consecutive ALL-PASS — M8→M9 Bridge Unlock (5/5 runtime_gates PASS)

**mode**: M9_SMOKE25_15MIN_SOAK_ALL_PASS_BRIDGE_UNLOCK
**session_date**: 2026-05-23
**schema_family**: m9_graph_arb
**schema_revision**: m9.1
**run_label**: smoke25 (15-min real-RPC soak, publicnode.com, prequote-min-bps=-9999 bypass, dynamic_sizes)
**execution_enabled**: false
**kill_switch_active**: true

---

## Smoke25 Summary

**goal**: 3rd consecutive all_pass 15-min proof-run on publicnode.com to satisfy M8→M9 bridge unlock policy (3/3 gate).

**result**: ALL 5 runtime_gates PASS. qsr=0.9779 ✅, mc_rate=1.0 ✅, data_completeness=1.0 ✅, unverified=0 ✅, quote_revert_rate=0.0 ✅. Zero http errors (429/408/5xx). **3/3 consecutive all_pass runs achieved. M8→M9 bridge unlock condition MET.**

### Run stats
- elapsed=900.2s (full 15 min ✅, duration_fulfilled=True)
- sweeps=450, cycles_found=4483, cycles_quoteable=4384, positive_gross=0 (flat market)
- sizes_usd=[100, 250, 500] ✅ (from config `scan_params`)
- dynamic_size_selected_count=1329 (selection_rate=0.2965, ~30%)
- run_timestamp: 2026-05-23T19:21:47Z

### runtime_gates — ALL PASS (3rd consecutive — BRIDGE UNLOCK)
| gate | value | threshold | pass |
|---|---|---|---|
| multicall_success_rate | 1.0 | 0.90 | ✅ |
| data_completeness | 1.0 | 0.98 | ✅ |
| unverified_active_routes | 0 | 0 | ✅ |
| qsr | 0.9779 | 0.80 | ✅ |
| quote_revert_rate | 0.0 | <0.05 | ✅ |
| **all_pass** | **true** | | ✅ **3/3** |

### Infra telemetry (zero errors)
- `http_429_count=0`
- `http_408_count=0`
- `http_5xx_count=0`
- `actual_http_calls=7626`
- `rpc_provider=publicnode`

### QSR trend (all 3 consecutive runs)
- smoke23 (1/3): qsr=0.9742 ✅
- smoke24 (2/3): qsr=0.9766 ✅
- smoke25 (3/3): qsr=0.9779 ✅ (improving)

---

## Session Completion

session_goal: Run smoke25 as 3rd consecutive all_pass proof-run for M8→M9 bridge unlock.
goal_status: REACHED — bridge unlock condition MET (3/3)
close_allowed: true
remaining_blockers: None for bridge unlock. Next: M8/M8.1 integration review.
evidence_session_run_dirs: data/runs/_rolling/m9_graph_latest.json (run_ts: 2026-05-23T19:21:47Z)
blocker_status_before: smoke25 PENDING (2/3 done)
blocker_status_after: smoke25 PASS (all_pass=True, 3/3 done)
docs_reread_confirmed: true

## Consecutive All-Pass Record
- smoke23 (2026-05-23T17:59:55Z): all_pass=True, qsr=0.9742, mc_rate=1.0 ✅
- smoke24 (2026-05-23T19:04:00Z): all_pass=True, qsr=0.9766, mc_rate=1.0 ✅
- smoke25 (2026-05-23T19:21:47Z): all_pass=True, qsr=0.9779, mc_rate=1.0 ✅ ← BRIDGE UNLOCK

## Code Changes This Session
- `m9/graph_arb/pool_state_cache.py`: added `TypeError` to except clause in `load()` to handle stale cache entries with `block_number=None`

## Previous Report Reference
smoke24: 2nd all_pass run, qsr=0.9766, mc_rate=1.0, all_pass=true (2/3 consecutive)

