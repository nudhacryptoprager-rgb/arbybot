# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: data/runs/ci_m5_gate_arbitrum_one_20260402_110313_968343
mode: ONLINE (M7.E1.8.1 provenance completion + zero-state uniformity. 3-min Base nonstop April 10 10:49-10:52Z. M4/M5 rolling unchanged — M7-only session with --no-m4)
artifact_mode: rolling
config: config/onboard_base_profit.yaml (base, narrow contour)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.E1.8.1 - run_context.chain in rollup/intents, heartbeat 9-key signal_counts, invariant tests

## Session Completion
session_goal: M7.E1.8.1 - complete chain provenance (run_context.chain in rollup + intents), uniform zero-state (heartbeat 9-key signal_counts), invariant tests
goal_status: REACHED (all 3 code fixes verified in fresh 3-min nonstop: rollup run_context.chain=base, intents run_context.chain=base + run_timestamp, heartbeat signal_counts=9-key zero dict. 3797 passed.)
close_allowed: true
remaining_blockers: (1) No non-empty windows — signal_counts all 0, market timing. (2) Flashblocks WS DNS unreachable. (3) Submit sim = 0. (4) Cold artifact lacks signal_counts (asymmetric honesty).
evidence_session_run_dirs: [data/runs/_rolling/ (m7_hot_rollup_latest.json run_context.chain=base, m7_hot_intents_latest.json run_context.chain=base run_context.run_timestamp=2026-04-10T10:52:39Z, m7_hot_latest.json signal_counts=9-key)]
primary_blocker_of_session: chain_provenance_incomplete — RESOLVED (run_context.chain was None in rollup and intents; heartbeat signal_counts was {} instead of 9-key zero dict)
blocker_status_before: ACTIVE — reviewer confirmed run_context.chain=None in rollup/intents artifacts
blocker_status_after: RESOLVED — all 3 hot artifacts have consistent chain=base and run_context.chain=base
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.E1.8.1 = reviewer fix steps 2 (rollup run_context.chain), 3 (intents run_context.run_timestamp), 4 (heartbeat 9-key signal_counts), 5 (invariant tests)
change_summary:
  - scripts/m7a_orderflow_loop.py: (1) Added "chain": chain to _update_hot_rollup run_context dict. (2) Added full run_context block to _write_hot_intents payload (chain + run_timestamp). (3) Heartbeat from-scratch signal_counts changed from {} to 9-key zero dict.
  - tests/unit/test_e1_base_chain_aware.py: 8 new tests in section 30 (chain invariants: rollup/intents run_context on disk, heartbeat 9-key). Updated heartbeat from-scratch test for 9-key assertion. Total: 123 E1 tests.
touched_files:
  - scripts/m7a_orderflow_loop.py
  - tests/unit/test_e1_base_chain_aware.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3797 passed, 6 skipped)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.05 --chain base --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (10:49-10:52Z, 3/3 alive, 0 restarts)

## 3) Artifacts Attached

M7 hot artifacts (FRESH — provenance complete):
- m7_hot_latest.json: chain=base, run_context.chain=base, signal_counts=9-key (all 0), error_counts={heartbeat_on_error:0}
- m7_hot_rollup_latest.json: chain=base, run_context.chain=base, run_context.run_timestamp=2026-04-10T10:52:39Z
- m7_hot_intents_latest.json: chain=base, run_context.chain=base, run_context.run_timestamp=2026-04-10T10:52:39Z

M4/M5 rolling (unchanged — M7-only session):
- _latest.json: run_status=PASS, agg_status=PASS, data_run_rate=1.0
- run_summary_latest.json: status=PASS, signals_count=31, total_net_usdc=40.0986

## 4) Key Results - M7.E1.8.1

### Reviewer Issues Addressed

| Issue | Description | Status |
|-------|-------------|--------|
| #2 | Session contract inconsistency (Status OPEN vs DEV_REPORT REACHED) | FIXED (both now aligned for E1.8.1) |
| #3 | run_context.chain=None in rollup | FIXED (now "base") |
| #4 | run_context.chain=None, run_timestamp=None in intents | FIXED (both populated) |
| #5 | Heartbeat signal_counts={} while docs claim 9-key | FIXED (now 9-key zero dict) |

### Artifact Evidence

| Artifact | Field | Before E1.8.1 | After E1.8.1 |
|----------|-------|---------------|--------------|
| m7_hot_rollup | `run_context.chain` | **None** | **base** |
| m7_hot_intents | `run_context.chain` | **None** | **base** |
| m7_hot_intents | `run_context.run_timestamp` | **None** | **2026-04-10T10:52:39Z** |
| heartbeat from-scratch | `signal_counts` | **{}** | **{9 keys, all 0}** |

### CI Evidence

| Command | Result |
|---------|--------|
| pytest | 3797 passed, 6 skipped |
| nonstop 3-min | 3/3 alive, 0 restarts |

latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: 1.0
  low_sample_rate: 0.0
run_summary_latest:
  status: PASS
  metrics.signals_count: 31
  metrics.total_net_usdc: 40.0986
  run_timestamp: 2026-04-02T09:03:41Z
  code_identity: ts:2026-04-02T09:03:41.464858Z
  inputs.run_mode: REGISTRY_REAL

## 5) Strategic Reading

1. **Chain provenance now complete across all hot artifacts**: rollup, intents, and hot artifact all have consistent `chain` + `run_context.chain` + `run_context.run_timestamp`. Reviewer can audit any artifact knowing exactly which chain and when.
2. **Zero-state contract truly uniform**: Heartbeat from-scratch now emits 9-key `signal_counts` dict (was `{}`). All paths — normal, heartbeat-on-error, from-scratch — produce the same 9-key structure.
3. **Session contract aligned**: Status_M7.md and DEV_REPORT_LATEST.md now agree on session state. Previous mismatch (OPEN vs REACHED) resolved.
4. **Operational truthfulness is real improvement, not throughput proof**: E1.8/E1.8.1 improved observability and contract consistency. Fresh profitable-case detection still requires non-empty hot windows during peak hours.
5. **Cold artifact asymmetry remains**: `m7_orderflow_latest.json` still has `signal_counts=None`. This is a known lower-priority gap (reviewer fix step 6).

## 5.1) Contract Checks
status/reasons consistency: OK (REACHED — provenance complete with fresh evidence)
rolling discipline: OK (canonical M7 artifacts only)
runtime artifacts not committed: OK (data/runs/** not in git)
docs_reread_confirmed: true

## 6) Blocker Classification

code_blocker: NONE (provenance complete, 3797 tests PASS)
data_collection_blocker: HIGH (empty windows — signal_counts all 0)
market_window_blocker: HIGH (Base swap events absent in off-peak windows)

## 6.1) Blockers / Risks
- No non-empty windows — signal_counts/gate_trace not exercised in runtime
- Flashblocks WS DNS unreachable
- Submit sim = 0 (scaffold only)
- Cold artifact lacks signal_counts (asymmetric honesty)

## 8) What I need from Lead now
question_1: Confirm E1.8.1 closure (provenance fully consistent). E1.9 = peak-hours evidence collection + Tenderly?
request_1: Schedule 10-30min peak-hours Base nonstop (14:00-22:00 UTC) for non-empty window evidence before submit-stage simulation.
