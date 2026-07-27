# DEV REPORT

## 0) Meta
timestamp_utc: 2026-07-08T08:18:55
canonical_rolling_timestamp: 2026-07-08T08:18:55
rolling_run_dir: data/runs/ci_m5_gate_arbitrum_one_20260708_101645_712808
session_patch_timestamp_utc: 2026-07-26T20:13:13Z
goal_status: IN_PROGRESS
primary_blocker_of_session: M8_SNIPER_BATCH_2_HARD_TIMEOUT
blocker_type: CODE_OR_INFRASTRUCTURE
runtime_validation: FAILED_BEFORE_M9
valid_partial_evidence: batch_1 upstream gate PASS, session 2026-07-26T20:13:13Z
docs_reread_confirmed: true
run_id: m8-sniper-batch-timeout-guard-2026-07-26
mode: sniper bounded timeout / orphan cleanup patch-set
config: config/exotic_base_anchor.yaml
code_revision: 8cfa09c6288ce0d5b78a6b8d632703b32cde1aea

## Session Completion
session_goal: fresh M8→M9 bundle after streaming session guard
goal_status: IN_PROGRESS
primary_blocker_of_session: M8_SNIPER_BATCH_2_HARD_TIMEOUT
close_allowed: false
remaining_blockers: sniper bounded timeout + orphan cleanup; full bundle retry
docs_reread_confirmed: true

## Online runtime (retry bundle)

### Command
```powershell
py -3.11 start.py -m8_m9 --streaming --sniper-batch-minutes 15 --no-dashboard --new-session --force-rerun-steps --pipeline-log data/tmp/m8_m9_p0_fixed_retry.log
```

### Result
- session_id: `2026-07-26T20:13:13Z` (valid runtime namespace)
- batch_1: PASS through M8.1/M8.2/M8.3 + upstream truth gate
- batch_2: `m8_sniper_acceptance_batch_2: hard_timeout_7200s`
- orphan sniper process remained after timeout (manually stopped)
- M9 shadow / capacity / lane acceptance / post_depth: NOT RUN

### Prior failures
- `2026-07-26T13:04:06Z` + force-rerun: `SNIPER_FINGERPRINT_MISMATCH` (fixed by session guard `8cfa09c`)

## Patch-set in progress (sniper timeout guard)

### Target files
- `application/stage_runner.py`
- `core/pipeline_streaming.py`
- `m8/runtime/smoke_run.py`
- `monitoring/sniper_funnel.py`
- `start.py`
- `tests/unit/test_application_control_plane.py`
- `tests/unit/test_m8_sniper_rpc_lane.py`
- `tests/unit/test_streaming_integration.py`

### Fixes
1. Per-RPC HTTP timeout on sniper providers
2. Bounded `400_range` split depth + factory poll timeout
3. Progress watchdog (`SNIPER_STALLED`) with funnel progress fields
4. In-process batch wall-clock buffer (`duration * 1.45`)
5. Sniper pipeline step timeout ~22m for 15m batch (not 7200s)
6. Process-tree kill on hard timeout / stale heartbeat
7. SLO + fail marker enrichment with progress/provider/block_range
8. Hermetic streaming integration test (`tmp_path` streaming root)

### Verification (sniper timeout guard patch)
```powershell
py -3.11 -m pytest tests/unit/test_streaming_integration.py tests/unit/test_m8_sniper_rpc_lane.py tests/unit/test_application_control_plane.py -q
# 50 passed

py -3.11 scripts/check_repo_safety.py
# PASS

py -3.11 scripts/check_quality_ratchet.py --pip-audit
# PASS

py -3.11 scripts/ci_full_pipeline.py --mode ci
# ALL REQUIRED GATES PASSED; collected 7402 items; 7363 passed, 39 skipped
```

### Retry command (after patch lands)
```powershell
py -3.11 start.py -m8_m9 --streaming --sniper-batch-minutes 15 --no-dashboard --new-session --force-rerun-steps --pipeline-log data/tmp/m8_m9_p0_fixed_retry2.log
```

Status files (`Status_M8*.md`, `Status_M9.md`) not updated — no valid same-session M9 evidence.
