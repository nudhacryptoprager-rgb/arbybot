# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-08T08:18:55
canonical_rolling_timestamp: 2026-07-08T08:18:55
rolling_run_dir: data/runs/ci_m5_gate_arbitrum_one_20260708_101645_712808
goal_status: IN_PROGRESS
primary_blocker_of_session: M8_BATCH2_TIMEOUT_BUDGET_UNDER_RPC_DEGRADATION
blocker_type: CODE_OR_INFRASTRUCTURE
runtime_validation: FAILED_BEFORE_M9
session_id: 2026-07-27T06:46:35Z
docs_reread_confirmed: true
code_revision: a15478c (pre-retry3 patch in progress)

## Session Completion
session_goal: fresh M8→M9 bundle after batch-1 timeout + getLogs circuit breaker fix
goal_status: IN_PROGRESS
primary_blocker_of_session: M8_BATCH2_TIMEOUT_BUDGET_UNDER_RPC_DEGRADATION
close_allowed: false
remaining_blockers: batch-1 timeout budget fix; getLogs 400 circuit breaker; retry3 bundle
docs_reread_confirmed: true

## Online runtime (retry2 bundle)

### Command
```powershell
py -3.11 start.py -m8_m9 --streaming --sniper-batch-minutes 15 --no-dashboard --new-session --force-rerun-steps --pipeline-log data/tmp/m8_m9_p0_fixed_retry2.log
```

### Result
- session_id: `2026-07-27T06:46:35Z` (valid runtime namespace)
- batch_1: `m8_sniper_acceptance_batch_1: hard_timeout_1323s` (~22 min)
- stall_seconds: 0.7 (active progress — timeout budget defect, not stall)
- getlogs_400_count: 625 (RPC degradation; failover under-split)
- M8.1/M8.2/M8.3/M9: NOT RUN
- P0 M9 economics (capacity trace, transport QSR): NOT RUN

### Retry3 result (session `2026-07-27T07:37:15Z`)
- batch_1 sniper: **PASS** (`timeout_s=2343`, exit=0, ~22 min)
- batch_1 M8.1/M8.2/M8.3 + upstream gate: **PASS**
- batch_2 sniper: **FAIL** `hard_timeout_1443s` (stall_seconds=2.4 — active progress)
- batch_2+ timeout too tight under RPC degradation (89×400, 75 provider switches)
- M9 / P0 economics: NOT RUN

### Prior failures
- `2026-07-26T13:04:06Z` + force-rerun: `SNIPER_FINGERPRINT_MISMATCH` (fixed by session guard `8cfa09c`)
- `2026-07-26T20:13:13Z`: batch_1 PASS; batch_2 `hard_timeout_7200s` + orphan sniper

## Patch-set in progress (batch-1 timeout + getLogs circuit breaker)

### Target files
- `core/pipeline_streaming.py`
- `start.py`
- `m8/runtime/smoke_run.py`
- `monitoring/sniper_funnel.py`
- `tests/unit/test_streaming_integration.py`
- `tests/unit/test_m8_sniper_rpc_lane.py`

### Fixes
1. Batch-index-aware sniper step timeout: batch 1 = self-test budget + scan + grace; batch 2+ = scan + grace
2. Configurable budgets via `ARBY_SNIPER_SELF_TEST_BUDGET_S`, `ARBY_SNIPER_STARTUP_GRACE_S`, `ARBY_SNIPER_BATCH_TIMEOUT_FACTOR`
3. Per-provider getLogs 400 circuit breaker (`ARBY_SNIPER_GETLOGS_400_CIRCUIT`) forces provider switch
4. Bounded getLogs 400 batch budget (`ARBY_SNIPER_GETLOGS_400_BUDGET`)
5. Sniper artifact fields: `getlogs_400_count_by_provider`, `range_shrinks`, `provider_switches`, `rpc_retry_exhausted`

### Verification (retry3 patch)
```powershell
py -3.11 -m pytest tests/unit/test_streaming_integration.py tests/unit/test_m8_sniper_rpc_lane.py -q
# 36 passed

py -3.11 scripts/check_repo_safety.py
# PASS

py -3.11 scripts/check_quality_ratchet.py --pip-audit
# PASS

py -3.11 scripts/ci_full_pipeline.py --mode ci
# ALL REQUIRED GATES PASSED
```

### Retry3 in progress
```powershell
py -3.11 start.py -m8_m9 --streaming --sniper-batch-minutes 15 --no-dashboard --new-session --force-rerun-steps --pipeline-log data/tmp/m8_m9_p0_fixed_retry3.log
```
- session_id: `2026-07-27T07:37:15Z`
- batch_1 timeout_s: 2343 (self-test + scan budget fix confirmed)
- circuit breaker: active (`sniper_rpc_failover` with `getlogs_400_circuit` in log)

Status files (`Status_M8*.md`, `Status_M9.md`) not updated — no valid same-session M9 evidence.
