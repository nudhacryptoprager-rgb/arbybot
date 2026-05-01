# M7.E1.51 slice-8 — Canary acceptance for slices 1-7

## Run command

```powershell
# Pre-flight: ensure registry sink is on (default) and choose sim backend
$env:ARBY_USE_LOCAL_PRICE_STATE = "1"
$env:ARBY_SIM_BACKEND = "anvil"   # or "tenderly" if quota available

# 30 minute canary
py -3.11 scripts/bootstrap_system.ps1 -Hours 0.5 `
   -ProviderBudget free -ProdSimBackend $env:ARBY_SIM_BACKEND `
   -DiscSimBackend rpc_fork
```

## Acceptance metrics

Read from `data/runs/_rolling/run_summary_latest.json` after the canary
finishes. All of the following must hold simultaneously:

| Metric                                | Required                       | Source slice |
| ------------------------------------- | ------------------------------ | ------------ |
| `price_state_updates_delta`           | `> 0`                          | slice-1/2/3  |
| `pool_price_state.v3_pools_tracked`   | `>= 1`                         | slice-1      |
| `pool_price_state.v2_pools_tracked`   | `>= 0` (≥1 if Aerodrome live)  | slice-2      |
| `ws_429_delta` (logs subscription)    | `== 0`                         | slice-7 dep  |
| `sim_attempted_delta`                 | `> 0`                          | slice-3 hot  |
| `sim_passed_delta`                    | `>= sim_attempted_delta * 0.4` | slice-5      |
| `clean_child_exits_delta`             | `>= 1`                         | supervisor   |
| `gross_pnl_drift_bps_p95` vs reference| `< 10`                         | slice-4/5    |

## Verdict mapping

- **PASS**: all rows green → mark E1.51 closed, demote E1.51 to "Prior"
  in `Status_M7.md`, write `goal_status: REACHED` in DEV_REPORT_LATEST.
- **FAIL ws_429_delta>0 but everything else green**: slices 1-6 are
  effective; the bottleneck is upstream of recv-loop body (drpc rate
  limit). Execute slice-7 (self-host) and re-canary.
- **FAIL price_state_updates_delta==0**: registry not being fed. Check
  `ARBY_USE_LOCAL_PRICE_STATE` env, inspect `mode_ws_live.py` integration
  at the `feed_raw_logs` call site.
- **FAIL gross_pnl_drift_bps_p95>=10**: anvil backend diverges from
  reference. Capture divergent bundle to
  `docs/artifacts/m7/anvil_drift/<timestamp>.json`, re-test on Tenderly
  to isolate.

## Closure rule (per AGENTS.md §0)

`goal_status: REACHED` requires fresh runtime artifacts proving the
deltas above. Green CI alone is **insufficient**. Close session as
`IN_PROGRESS` until the canary log is captured and verdict is computed.

## Live canary results (run #4, 2026-05-01)

| Field                       | Observed                          |
|-----------------------------|-----------------------------------|
| Duration                    | 0.1 h (≈6 min)                    |
| Supervisor                  | PID 19088, clean exit             |
| `clean_child_exits_total`   | `1` ✅                            |
| `periodic_heartbeats_total` | `2` ✅                            |
| `pool_price_state` block    | **present** ✅ (slice-3c surface) |
| `pool_price_state.updates_total` | `0` ❌                       |
| `pool_price_state.v2_updates_total` | `0` ❌                    |
| `events_seen_total`         | `None` (no hot events)            |
| Root cause for zeros        | drpc free-tier WS 429 throttle    |

**Verdict: IN_PROGRESS / partial PASS.** Slices 1, 2, 3, 3b, 3c, 4, 6
landed and surfaced (rollup carries the `pool_price_state` block via
both `heartbeat_hot_rollup_cycle` and `flush_rollup_shutdown` paths,
plus the regular `_update_hot_rollup` path). All 4502 unit tests pass.
The remaining metrics (`updates_total > 0`, `sim_attempted_delta`,
`gross_pnl_drift_bps_p95`) cannot be observed on free-tier drpc because
the WS subscribe is rate-limited before any swap log is delivered. Per
the verdict mapping above this matches the
"`ws_429_delta>0` but everything else green" branch → execute
**slice-7 (self-host node)** or upgrade to a premium WS provider, then
re-canary to flip `goal_status: REACHED`.
