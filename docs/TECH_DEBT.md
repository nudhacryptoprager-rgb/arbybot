# Technical Debt Tracker

> Policy: track non-blocking technical debt that still matters after the current public-infrastructure DEX-DEX audit.

## Active Items

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
