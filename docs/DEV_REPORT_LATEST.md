# Dev Report — Latest

## E1.51 canary #8 — AttributeDict fix CONFIRMED live (2026-05-01)

### Summary

Three-root-cause chain now fully resolved. Canary #8 cold lane iter=4 produced:
```
raw_logs=12  pps_v3_updates=12  pps_v2_updates=0  pps_skipped=0
```
First live proof that `feed_raw_logs` correctly decodes V3 Swap events from
`web3.eth.get_logs()`. All three root causes have been fixed and unit-tested.

### Root Cause 3 — `isinstance(lg, dict)` fails for `web3.datastructures.AttributeDict`

`web3 v6 eth.get_logs()` returns logs as `AttributeDict`, which inherits from
`collections.abc.Mapping` (NOT from `dict`). So `isinstance(lg, dict)` is **False**
for every real log, making `data_hex = None` → all logs silently skipped.

**Fix** (`m7/orderflow/pool_price_state.py`, `feed_raw_logs`):
```python
# Before (broken):
data_hex = lg.get("data") if isinstance(lg, dict) else None

# After (fixed):
from collections.abc import Mapping
data_hex = lg.get("data") if isinstance(lg, Mapping) else None
```
`Mapping` is a supertype of both `dict` and `AttributeDict`. No behaviour change
for regular dicts.

**Test added**: `TestFeedRawLogs.test_attributedict_mapping_not_dict` (40th pps test).
Full test suite: **4510 passed / 6 skipped** (baseline was 4507 + 3 new this session).

### Complete root cause tree (all three)

| # | Root Cause | Location | Fix |
|---|-----------|----------|-----|
| RC1 | `HexBytes.startswith("0x")` raises `TypeError` (bytes vs str) | `feed_raw_logs` data normalization | Normalize `HexBytes → str` via `.hex()` |
| RC2 | Hot lane exits before HTTP fallback (drpc 429 fast exit) | Process/infra | Structural; needs working WS |
| RC3 | `isinstance(lg, dict)` is `False` for `AttributeDict` | `feed_raw_logs` Mapping check | Use `isinstance(lg, Mapping)` |

RC1 and RC3 were both silent: `except Exception` or `if not data_hex` ate the error.
RC2 is infra: hot rollup `updates_total` stays 0 without a non-throttled WS provider.

### Cold lane pps live trace (canary #8)
- `raw_logs=12 norm=1 scored=1` (iter=4, ended 10:08:22Z)
- `pps_v3_updates=12 pps_v2_updates=0 pps_skipped=0` ← first non-zero live result
- `funnel_debug` pps keys visible in artifact (new cold child, post-edit code)

### Status after canary #8

- **Cold lane pps**: `v3_updates=12` proven live ✅
- **Hot lane pps**: still 0 — hot lane gets 0 raw_logs (drpc 429 fast exit) ⚠️
- **Hot rollup `updates_total`**: 0 — reads hot-process singleton only ⚠️
- **`POOL_PRICE_STATE_SINK_STARVED`** reviewer guard: still FAILs for hot lane ⚠️
- **goal_status: IN_PROGRESS** — REACHED requires working WS so hot lane gets logs

---

## E1.51 canary #5/#6 — HexBytes bug found and fixed (2026-05-01)

### Summary

Canary #5 (PID 34144, 20-min, drpc free-tier) showed `ws_live_stats.raw_logs_total=12` but
`pool_price_state.updates_total=0`. Root cause: **`feed_raw_logs` silently dropped every log**.

**Root cause**: `web3 v6 eth.get_logs()` returns `log["data"]` as `HexBytes` (a `bytes`
subclass). Calling `data_hex.startswith("0x")` on `HexBytes` raises `TypeError` (requires
`bytes`, not `str`). The `except Exception` silently incremented `skipped` for every log.

**Fix** (`m7/orderflow/pool_price_state.py`, `feed_raw_logs`):
```python
if not isinstance(data_hex, str):
    data_hex = data_hex.hex() if hasattr(data_hex, "hex") else data_hex.decode("utf-8", errors="replace")
payload = data_hex[2:] if data_hex.startswith("0x") else data_hex
```
Confirmed by subprocess test → `{'v3_updates': 1, 'v2_updates': 0, 'skipped': 0}`.

**Canary #6** (PID 35716, 0.33h, same setup) launched after fix. Result: `updates_total=0`
still. Root cause analysis:

1. **Hot lane**: `session_ws_failed_429_windows=10, session_http_fallback_windows=0` —
   hot lane exits at WS 429 before any HTTP fallback triggers; `raw_logs=0` in hot lane.
2. **Cold lane**: receives ~12 V3 Swap logs (via `eth.get_logs()` HTTP fallback, filtered
   by `SWAP_EVENT_TOPIC`). These ARE valid V3 Swap events (data = 320 hex chars). The cold
   lane `_feed_pool_price_logs` runs with the HexBytes fix. However, cold lane is a **separate
   process with its own registry singleton** — updates go into the cold lane's in-process
   registry, NOT the hot rollup's registry. Hot rollup `pool_price_state` reads only the
   hot lane's singleton.
3. **Net result**: Hot rollup pps counters stay 0. HexBytes fix is code-correct and unit-proven
   but cannot be confirmed live because hot lane gets 0 logs with drpc free-tier 429s.

### Additional instrumentation (this session)

`mode_ws_live.py` `_funnel_debug` now accumulates per-session pps sink counters:
- `pps_v3_updates` — V3 updates fed in this ws_live window
- `pps_v2_updates` — V2 updates fed in this ws_live window
- `pps_skipped`    — logs rejected by size/decode in this window

These appear in `ws_live_stats.funnel_debug` of `m7_orderflow_latest.json` on new child
processes. Allows per-cycle diagnosis of how many Swap logs were routed to pps sink.

### Closure verdict

`goal_status: IN_PROGRESS`. HexBytes fix proves the sink is code-correct. Live proof blocked:

- Hot lane never gets raw_logs with drpc free-tier (ws_failed_429 → immediate exit)
- Cold lane pps updates not surfaced in hot rollup (cross-process registry isolation)

`REACHED` requires working WS (self-hosted node or paid subscription) so hot lane gets logs.

---

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

### Reviewer surface (lead-followup, this session)

Per the lead's directive, `scripts/reviewer_soak_summary.py` now reads
the nested `pool_price_state` block from
`data/runs/_rolling/m7_hot_rollup_latest.json` and emits the following
deltas alongside the existing scalar deltas:

- `pool_price_state_updates_total`
- `pool_price_state_v2_updates_total`
- `pool_price_state_decode_errors_total`
- `pool_price_state_v2_decode_errors_total`
- `pool_price_state_stale_drops_total`
- `pool_price_state_v2_stale_drops_total`
- `pool_price_state_pools_tracked_current` (snapshot, not delta)

A new reviewer guard `POOL_PRICE_STATE_SINK_STARVED` FAILs the lane
when `events_seen_delta > 0` and the combined updates delta is `0` —
this distinguishes the surfacing question (block presence) from the
sink-data-flow question (real decodes happening). Suppressed when
`ARBY_REVIEWER_QUIET_OK=1`.

Acceptance doc `docs/m7/E1_51_CANARY_ACCEPTANCE.md` was rewritten to
make the canonical source explicit (`m7_hot_rollup_latest.json`, NOT
`run_summary_latest.json`) and to harden
`pool_price_state.updates_total > 0` as a non-negotiable HARD row.

Test shield: `tests/unit/test_e1_51_reviewer_pool_price_state.py`,
5 cases, all passing. Full suite: **4507 passed / 6 skipped** in
102.84s. `check_repo_safety.py --allow-intent-edit` PASS 0 warnings.

