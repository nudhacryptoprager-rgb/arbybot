# Technical Debt Tracker

> Policy: track non-blocking technical debt that still matters after the current public-infrastructure DEX-DEX audit.

## Active Items

### TD-004: RPC-Per-Pool `slot0`/`liquidity` Reads — Replace with Event-Derived State

**Added**: 2026-05-01 (E1.51 slice-1)
**Priority**: HIGH (drives RPC budget exhaustion under drpc/Alchemy free tiers)
**Category**: Hot lane cost model

`m7/orderflow/resolve.py::extract_pool_state_for_sim` calls `core.multicall.MulticallBatcher.batch_full_pool_data` (per-pool `slot0` + `liquidity` RPC reads) for every shortlisted pool on every scored event. Under free-tier provider budgets this is the dominant RPC-CU consumer in the hot lane; it competes with `eth_subscribe newHeads` for the same drpc CU/min budget and contributes to the 429 storms tracked in TD-003.

The full V3 `Swap` event payload **already contains** `sqrtPriceX96`, `liquidity`, `tick` (the same 3 values returned by `slot0`+`liquidity`), but `m7/orderflow/events.py::normalize_swap_log` validates the 320-hex layout and then explicitly drops the last 3 fields with the comment `# sqrtPriceX96, liquidity, tick available but not needed for event normalization`. Replacing the RPC read with an event-derived registry should cut `multicall_full_pool_data_calls_total / scored_event` by ≥50% on a healthy WS feed.

**Slice plan (E1.51, executed slice-by-slice with checkpoint gates):**
- **slice-1 ✅ DONE** (2026-05-01): `m7/orderflow/pool_price_state.py` — `V3PoolState` dataclass + `decode_v3_swap_log_state` + thread-safe chain-scoped `PoolPriceStateRegistry` with latest-write-wins by `(block_number, log_index)` + module-level singleton. Test shield `tests/unit/test_pool_price_state.py` 19 PASS. NO public API change to `OrderflowEvent`. NO hot-lane wiring yet.
- **slice-2 ✅ DONE** (2026-05-01): V2/ve33 `Sync(uint112,uint112)` decoder + `V2PoolState` dataclass + parallel `_v2_state` substore in registry + schema bump to `m7.e1.51.slice2.pool_price_state.v2`; +13 unit tests (32 total in `test_pool_price_state.py`).
- **slice-3 ✅ DONE** (2026-05-01): `m7/orderflow/pool_price_state.feed_raw_logs(chain, logs)` passive sink + wiring in `m7/orderflow/mode_ws_live.py` recv loop (gated by `ARBY_USE_LOCAL_PRICE_STATE`, default on); +5 unit tests (37 total). `extract_pool_state_for_sim` registry-first lookup is deferred to slice-3b for safety.
- **slice-4 ✅ DONE** (2026-05-01): `scripts/replay_v3_state_drift.py` offline harness + `tests/unit/test_replay_v3_state_drift.py` (5 tests). Acceptance gates: `drift_pools_pct < 1%` AND `max_sqrt_price_drift_bps < 5`.
- **slice-5 ✅ DONE** (2026-05-01, doc-only): `docs/m7/SIM_BACKEND_ANVIL.md` — operational runbook. Anvil router was already wired in `m7/orderflow/simulation.py` (no code duplication needed).
- **slice-6 ✅ DONE** (2026-05-01): `m7/orderflow/flashblocks_ingest.py` (`consume_flashblock` + `FlashblockSubscriber` stub) + 5 unit tests. Real WS subscriber lands in slice-6b when provider chosen.
- **slice-7 ✅ DONE** (2026-05-01, doc-only): `docs/m7/SELF_HOST_BASE_NODE.md` — Hetzner AX52 ~$60/mo plan, op-geth + op-node, snapshot bootstrap, monitoring matrix, break-even calc.
- **slice-8 ✅ DOC DONE** (2026-05-01): `docs/m7/E1_51_CANARY_ACCEPTANCE.md` — canary command + 8-row acceptance metric table + verdict mapping. Real 30m canary run is an ops step (not synchronously verifiable in CI).

**Acceptance for full TD-004 closure**: full slice-3 wire-up confirmed by 30m canary showing `multicall_full_pool_data_calls_per_scored_event` drops by ≥50% AND no regression in `sim_passed_rate`.

---

### TD-003: In-Process Hot Registry / Tier-Map Refresh Bridge

**Added**: 2026-04-30 (E1.49 speed-audit)
**Updated**: 2026-04-30 (E1.50 surgical patches landed and live-tested)
**Priority**: LOW (was MEDIUM)
**Category**: Hot lane cadence

E1.49 landed mid-cycle + iteration-boundary heartbeat (`heartbeat_hot_rollup_cycle`) and reviewer
`HOT_CADENCE_TOO_SLOW` guard so reviewer staleness windows are now decoupled from `ws_timeout`.

E1.50 landed the deferred "in-process bridge" surgical patches:

- `m7/orderflow/mode_ws_live.py` — module-level `_LAST_WORKING_WS` cache + `_remember_last_working_ws`
  / `_peek_last_working_ws` helpers, used at WS resolution time and stamped on subscribe success
  (gated by `ARBY_WS_REUSE_LAST_WORKING`, default `1`; refuses `public_fallback` to honor strict
  provider policy).
- `m7/orderflow/mode_ws_live.py` — mid-recv-loop bridge re-read every `ARBY_HOT_BRIDGE_REFRESH_S`
  (default 45s) that warms `_pool_token_cache` so newly resolved pools become scoreable inside the
  same WS subscription. Pure additive; registry mutation stays at iteration boundary.
- `m7/orderflow/loop_runner.py` — zero-liq refresh throttled to every Nth hot iteration
  (`ARBY_HOT_ZLR_EVERY_N_ITERS`, default 3) to cut drpc HTTP load by ~66%.
- Unit shield: `tests/unit/test_e1_50_ws_reuse.py` (5 cases).

**Live test (2026-04-30T20:49:39Z→21:19:41Z, 30 min)**: cycles_completed=0; the recv-loop body
(where all 3 patches plus the E1.49 mid-cycle heartbeat live) was never reached because drpc 429
storms blocked `eth_subscribe newHeads` upstream. Hypothesis "in-process bridge unblocks the
canary" — REFUTED for the dominant 429-on-subscribe failure mode.

**Why this is now LOW**: the surgical bridge is implemented and unit-shielded. It REMAINS VALUABLE
as soon as any WS provider permits a sustained recv-loop (it removes per-iteration redundant cost
and absorbs new resolutions in-iteration). It is no longer "deferred work that might unblock
production"; the production blocker is upstream provider throttling, not in-process registry
sharing.

The deeper full refactor (cross-process registry sharing with lock primitives, WS multiplexer
opening 2 parallel subscriptions and reading from whichever survives) is its own iteration. Track
separately if/when needed. For now, operators should pair the E1.49+E1.50 stack with a healthier
WS provider (premium Alchemy slot or dedicated drpc plan) to deliver `clean_child_exits_delta>=2`
per 30 min soak.

---

### TD-002: Large File Concentration

**Added**: 2026-03-14  
**Priority**: MEDIUM  
**Category**: Architecture

The repo is now functionally much healthier than it was before the R39 extraction wave, but several files still carry too much orchestration surface:

| File | Current Shape | Why It Still Matters |
|------|---------------|----------------------|
| `strategy/jobs/run_scan_real.py` | primary online orchestration shell | runtime glue still dense |
| `strategy/quotes.py` | large quote pipeline surface | mixed adapter/fallback/policy logic |
| `scripts/ci_m5_0_gate.py` | large gate script | validation/reporting surface still broad |
| `scripts/check_repo_safety.py` | large repo policy checker | many independent checks in one file |

Current reading:

- this is real maintainability debt,
- but it is no longer the main blocker for strategy truth,
- large-file cleanup should follow milestone needs, not become a refactor project by itself.

---

### TD-001: `websockets.legacy` Deprecation Warning

**Added**: 2026-02-23  
**Priority**: LOW  
**Category**: Dependencies

The warning remains non-blocking. It should be cleaned up eventually, but it is not currently affecting milestone truth, CI, or rolling evidence quality.

---

## Resolved / Reclassified

### TD-003: Event-Driven Freshness As Primary Leverage

**Added**: 2026-03-24  
**Reclassified**: 2026-03-27  
**Result**: resolved as a strategic no-go for the current public-infrastructure thesis

What changed:

- the repo now contains enough fresh live evidence to evaluate the claim directly,
- WS/polling freshness improvements did not yield material spread improvement on the current public-infrastructure simple DEX-DEX path,
- `DirtySetTracker`, `PairHotQueue`, and hot-loop scaffolding remain useful infrastructure, but event-driven freshness is no longer a high-priority profit unlock for the current thesis.

This means:

- the code should not be ripped out,
- but it should also not be treated as the current highest-value optimization target.

---

## Current Debt Reading

The main open debt in this repo is no longer "hidden infra weakness". The remaining debt is mostly:

1. code concentration in several large orchestration files,
2. documentation drift if status/docs are not kept aligned with rolling evidence,
3. dormant execution capability that is implemented architecturally but not promoted operationally.
