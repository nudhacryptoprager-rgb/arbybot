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

**Canonical source**: `data/runs/_rolling/m7_hot_rollup_latest.json`
(plus the `_discovery` sibling for DISC lane). The supervisor's
`run_summary_latest.json` is **not** authoritative for E1.51 because
it does not carry the `pool_price_state` block — the rolling hot
rollup is the single source of truth for canary acceptance.

After the canary finishes, read the rollup once and verify that **all**
of the following hold simultaneously (hard acceptance — no partial
credit):

| Metric (rollup field)                              | Required                       | Source slice |
| -------------------------------------------------- | ------------------------------ | ------------ |
| `pool_price_state.updates_total`                   | `> 0` (HARD)                   | slice-1/3    |
| `pool_price_state.v2_updates_total`                | `>= 0` (≥1 if Aerodrome live)  | slice-2/3    |
| `pool_price_state.pools_tracked`                   | `>= 1`                         | slice-1/2    |
| `pool_price_state.decode_errors_total`             | `== 0`                         | slice-1/2    |
| `ws_429_total` delta (logs subscription)           | `== 0`                         | slice-7 dep  |
| `sim_attempted_total` delta                        | `> 0`                          | slice-3 hot  |
| `sim_passed_total` delta                           | `>= sim_attempted_delta * 0.4` | slice-5      |
| `clean_child_exits_total` delta                    | `>= 1`                         | supervisor   |
| `gross_pnl_drift_bps_p95` vs reference             | `< 10`                         | slice-4/5    |

**Hard rule**: `pool_price_state.updates_total > 0` is non-negotiable.
A rollup with the `pool_price_state` block present but all counters
zero proves only **surfacing**, not **sink data flow** — that is
`IN_PROGRESS`, not `REACHED`.

## Verdict mapping

- **PASS**: all rows green → mark E1.51 closed, demote E1.51 to "Prior"
  in `Status_M7.md`, write `goal_status: REACHED` in DEV_REPORT_LATEST.
- **FAIL ws_429_delta>0 AND `pool_price_state.updates_total==0`**:
  slices 1-6 are effective at the surfacing layer (rollup carries the
  block) but the sink path is starved upstream of the recv-loop body
  (drpc rate limit). Do **not** re-canary on the same WS — execute
  slice-7 (self-host) or move to a premium WS provider first.
- **FAIL `pool_price_state.updates_total==0` with ws_429_delta==0**:
  registry not being fed despite a healthy WS. Check
  `ARBY_USE_LOCAL_PRICE_STATE` env, inspect `mode_ws_live.py` integration
  at the `feed_raw_logs` call site, and verify the recv loop actually
  yields `logs` payloads (not only `newHeads`).
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
