# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-05T13:05:29Z
run_id: data/runs/_rolling/soak_e158_3h_20260505_100524
mode: ONLINE 3h Base soak, dry-run/paper-signing only
artifact_mode: rolling
verdict: **E1.58 runtime verification REACHED**. The new submit-ready and roundtrip-bps wiring stayed compatible under a 3h soak. PROD produced non-zero paper/canonical simulation profit: `roundtrip_profitable_total=7`, `submit_ready_total=7`. This is not real on-chain profit because live submit paths remain intentionally unimplemented/unauthorized.
config: ARBY_COLD_IMMEDIATE_SIM=1; ARBY_COLD_IMMEDIATE_MIN_NET_BPS=0; ARBY_COLD_IMMEDIATE_TOP_N=5; ARBY_PAPER_SIGNING=1; ARBY_SIM_BACKEND_PROD=rpc_fork; ARBY_SIM_BACKEND_DISC=rpc_fork; ARBY_TENDERLY_DISABLE=1; command `scripts/start_nonstop_runtime.py --chain base --hours 3 --no-m4 --with-discovery --dashboard-port 8118 --m7-cold-pause 3 --m7-hot-pause 1 --m7-hot-ws-timeout 120 --m7-hot-blocks 300 --m7-hot-max-events 120`
code_identity:
  branch: split/code
  commit: ed55ce408e20eb894f4db90f29eb4636e9724f0d
  dirty: true
  desc: E1.58 additive dry-run/live-proof scaffolds; 4630 PASS / 6 skipped before soak.

## 1) Scope
Goal: verify that the E1.58 changes are compatible in runtime, do not degrade the funnel, and that the new CI submit-ready / roundtrip bps surfaces become live under a long enough soak.

Important boundary: this session validates simulated/paper canonical readiness. It does not authorize or perform real trading.

## 2) Commands Executed
py -3.11 scripts/check_repo_safety.py --allow-intent-edit: PASS, 0 warnings
py -3.11 scripts/check_rpc_endpoints.py --chain base --ws-timeout 15: PASS; Flashblocks endpoint warning 405
py -3.11 -m pytest tests/unit -q: 4630 passed / 6 skipped / 1 warning (pre-soak)
py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 3 --no-m4 --with-discovery --dashboard-port 8118 --m7-cold-pause 3 --m7-hot-pause 1 --m7-hot-ws-timeout 120 --m7-hot-blocks 300 --m7-hot-max-events 120: clean exit
py -3.11 scripts/check_repo_safety.py --allow-intent-edit: PASS, 0 warnings (post-soak)

## 3) Artifacts Used
data/runs/_rolling/m7_hot_rollup_latest.json
data/runs/_rolling/m7_hot_rollup_latest_discovery.json
data/runs/_rolling/soak_e158_3h_20260505_100524/supervisor.out.log
data/runs/_rolling/soak_e158_3h_20260505_100524/supervisor.err.log

Note: rolling `session_id=94894a30` was reused from the earlier 10-min control run, and `current_session_started_at=2026-05-05T09:46:07Z` predates the 3h supervisor start. CI/submit/roundtrip counters were zero before this 3h run, so those counters are fresh for the 3h validation. Feed totals include the small earlier control residue.

## 4) Key Results
Supervisor:
- started: 2026-05-05T10:05:24Z
- finished: 2026-05-05T13:05:29Z
- 5/5 child processes alive until shutdown
- 0 crash_restarts
- stderr size: 0 bytes

PROD HOT:
- events_seen_total: 1107
- fast_path_scored_total: 961
- fast_path_positive_total: 71
- cold_immediate_sim_input_total: 332
- cold_immediate_sim_attempted_total: 322
- cold_immediate_sim_passed_total / profitable: 69 / 69
- cold_immediate_roundtrip_attempted_total / profitable: 69 / 7
- cold_immediate_submit_ready_total: 7
- roundtrip_attempted_total / success / profitable: 71 / 8 / 7
- submit_ready_total: 7
- roundtrip_profit_bps best / median / worst: 982.8267 / 980.911 / -30.1319
- rate_metrics: attempt_rate=21.3831/h, profitable_event_rate=2.1082/h, scoring_blackhole_rate=0.0
- l1_fee_source_last: onchain; calldata_len=228; calldata_kind=swaprouter02_representative
- external_provider_blocker_total: 0
- session_ws_failed_429_windows: 41

DISCOVERY:
- events_seen_total: 1121
- fast_path_scored_total: 977
- fast_path_positive_total: 71
- cold_immediate_sim_input_total: 240
- cold_immediate_sim_attempted_total: 240
- cold_immediate_sim_passed_total / profitable: 110 / 110
- cold_immediate_roundtrip_attempted_total / profitable: 110 / 35
- cold_immediate_submit_ready_total: 35
- roundtrip_attempted_total / success / profitable: 114 / 38 / 35
- submit_ready_total: 35
- roundtrip_profit_bps best / median / worst: 1397.5115 / 326.4385 / -135.9316
- rate_metrics: attempt_rate=34.3491/h, profitable_event_rate=10.5458/h, scoring_blackhole_rate=0.0114
- l1_fee_source_last: onchain; calldata_len=228; calldata_kind=swaprouter02_representative
- external_provider_blocker_total: 0
- session_ws_failed_429_windows: 37

## 5) Contract Checks
- E1.58 submit-ready wiring: PASS (`cold_immediate_submit_ready_total` and top-level `submit_ready_total` both non-zero).
- E1.58 roundtrip bps buffer: PASS (`roundtrip_profit_bps_best/worst/median` populated).
- L1 fee onchain diagnostic: PASS on both lanes.
- rpc_fork canonical backend: PASS on both lanes.
- Tenderly/external provider blocker: PASS (`external_provider_blocker_total=0`).
- No crash regression: PASS.
- No scoring blackhole: PASS for PROD (`scoring_blackhole_rate=0.0`).

## 6) Blockers and Risks
Primary blocker to real production trading: live submit path remains intentionally disabled (`*_NOT_IMPLEMENTED` scaffolds). The system can produce paper/canonical simulated profitable opportunities, but has not yet submitted or settled a real transaction.

Operational risks still visible:
- dRPC free-tier pressure persists: 37-41 WS 429 windows and live HTTP 408 samples.
- Flashblocks preconf endpoint probe returned 405 in the preflight check, so pending-state paths need explicit endpoint/method validation.
- `pool_price_state.updates_total=0` in hot rollups; the HTTP proof lane proved the sink earlier, but this hot soak did not populate local price state.
- `session_id` reuse and stale `supervisor_end_utc` during the early part of the run can confuse reviewer deltas.
- `clean_child_exits_total` is null and supervisor process summary shows child `cycles_completed=0`; heartbeat windows are live, but child-cycle cadence remains a weak performance signal.
- Cold-immediate revert volume is high: PROD `cold_immediate_sim_revert_total=248`, mostly `REVERT:STF` / `REVERT:unknown:no_data` samples.

## 7) Next Steps
1. Fix rolling session hygiene: clear old `supervisor_end_utc` and create a new soak baseline at supervisor start.
2. Add reviewer baseline snapshot creation before every long soak.
3. Implement a Flashblocks HTTP pending lane for `eth_getLogs` with `fromBlock=toBlock=pending` and bounded target pool filters.
4. Validate `eth_simulateV1` against `https://mainnet-preconf.base.org` with one representative dry-run payload and feature-gate it.
5. Add provider throttle governance: per-method token buckets, backoff, and failover away from dRPC when 408/429 rates breach threshold.
6. Promote DISC winners to PROD with TTL and provenance while preserving manual governance caps.
7. Add revert-bucket dashboards for `REVERT:STF`, `REVERT:unknown:no_data`, HTTP 408, and pre-sim skip reasons.
8. Wire `pool_price_state` into the hot HTTP/pending path so local price state is non-zero without relying on paid WS.
9. Run a 1h preflight-enabled dry-run (`ARBY_EXECUTION_PREFLIGHT=1`, still no live submit) once the wallet/router context is configured.
10. Only after explicit authorization and a kill-switch rehearsal, run a 1-wei live canary; do not call any simulated profit "real profit" until on-chain inclusion and balance/PnL accounting are proven.

## 8) Session Completion
goal_status: REACHED
close_allowed: true
primary_result: E1.58 runtime compatibility and paper/canonical submit-ready proof reached in 3h soak
production_ready_status: BLOCKED_BY_LIVE_EXECUTION_AND_PROVIDER_LIMITS
blocker_status_before: IN_PROGRESS
blocker_status_after: RESOLVED_FOR_E1_58_RUNTIME_VERIFICATION__BLOCKED_FOR_REAL_EXECUTION
docs_reread_confirmed: true
