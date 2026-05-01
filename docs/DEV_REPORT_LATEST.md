# Dev Report — Latest

## E1.51 program closure attempt (live canary #4)

**Goal**: replace RPC-per-pool `eth_call slot0` reads with event-derived
local market state from Swap/Sync logs (slice 1-8 program).

**Outcome**: code+tests+docs LANDED for all 8 slices; slice-3c rollup
surfacing now wired across all three rollup writers; live canary #4
confirms the `pool_price_state` block lands in
`data/runs/_rolling/m7_hot_rollup_latest.json`. Counters are zero
because drpc free-tier WS still rate-limits `eth_subscribe` before any
swap log can be delivered. Per
`docs/m7/E1_51_CANARY_ACCEPTANCE.md` verdict mapping this matches the
"`ws_429_delta>0` but everything else green" branch — slices 1-6 are
effective, bottleneck is upstream of recv-loop body.

### Verification

- `py -3.11 -m pytest tests/unit -q` → **4502 passed / 6 skipped / 1
  warning** in 106.93s.
- Live canary #4 (2026-05-01T10:01:12Z, 0.1h, supervisor PID 19088,
  clean exit): rollup carries `clean_child_exits_total=1`,
  `periodic_heartbeats_total=2`, well-formed `pool_price_state` block
  with all-zero counters.

### Slice-3c writer fan-out (this session)

Initial slice-3c only wrote `pool_price_state` from `_update_hot_rollup`
(windowed counter path). Canary #3 surfaced `pool_price_state: None`
because the WS recv loop never delivered events to that path during a
short canary on free-tier drpc. Fix: replicate the registry-counter
snapshot in **all three** rollup writers in
`m7/orderflow/hot_runtime_artifacts.py`:

1. `_update_hot_rollup` (windowed counter increment).
2. `heartbeat_hot_rollup_cycle` (mid-cycle periodic flush).
3. `flush_rollup_shutdown` / `_flush_rollup_at_path` (clean child exit).

All three read the same `pool_price_state.get_registry().counters()`
snapshot via defensive `try/except` so they never raise into the hot
path. Confirmed by canary #4 rollup output.

### Closure verdict (per AGENTS.md §0)

`goal_status: IN_PROGRESS`. `REACHED` requires either:

- slice-7 self-host op-geth+op-node (Hetzner AX52 plan in
  `docs/m7/SELF_HOST_BASE_NODE.md`), OR
- a premium Alchemy WS subscription,

followed by a re-canary that produces
`pool_price_state.updates_total > 0`,
`sim_attempted_delta > 0`, and `clean_child_exits_delta >= 1`.
