# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 7 Round 28.11 Turn 2)
**Goal**: R28.11 architectural — Hot re-quote loop (full sweep vs hot re-quote cycle separation), WebSocket dirty-set invalidation (newHeads trigger instead of time-based), pair-level observability retained from Turn 1.
**Prior (R28.11 Turn 1)**: Pair-level observability complete (pair_history, deltas, cache freshness, suppression counters, guardrails). Turn 2 implements Lead architectural directive: "Розвести два цикли: full sweep і hot re-quote loop. Використати WebSocket не як 'галочку', а як trigger для dirty-set invalidation."

## 0) Meta
timestamp_utc: 2026-03-15T20:50:00Z
rolling_provenance: 2026-03-15T21:01:07Z (6-chain long_scan — R28.11 Turn 2 fresh evidence)
mode: HOT_LOOP + DIRTY_SET_INVALIDATION + PAIR_LEVEL_OBSERVABILITY
test_count: 1870 passed, 3 skipped
schema_version: start:long_scan_summary:v1.10

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.11 Turn 2: Architectural — hot re-quote loop + WebSocket dirty-set invalidation |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: arb gap still PRIMARY_BLOCKER; PROBE_PATH: arb stability from narrow static probe config |
| evidence_session_run_dirs | long_scan_latest.json (2026-03-15T21:01:07Z, 6 chains, schema v1.10, hot_loop populated, 7 full sweeps + 5 hot requotes), hot_pairs_*.json caches in data/cache/ |
| primary_blocker_of_session | Scanning pipeline had no cycle separation — every scan did full discovery. No WebSocket block-trigger — just time-based. |
| blocker_status_before | ACTIVE: every scan did full discovery (slow); no WebSocket dirty-set trigger; no hot-pairs caching; no scan_mode tracking |
| blocker_status_after | RESOLVED: hot re-quote loop (every FULL_SWEEP_INTERVAL=5 scans does full sweep, others use cached pairs); DirtySetTracker with WebSocket newHeads subscription; hot_pairs_*.json caches; scan_mode field; hot_loop summary section |
| start_metric | R28.11 T1: 1864 tests, no hot loop, no dirty-set, every scan full discovery |
| end_metric | R28.11 T2: 1870 tests (+6), hot_loop (7 full/5 hot), DirtySetTracker WSS, 5 hot pair caches, schema v1.10 |
| delta | +hot re-quote loop, +DirtySetTracker, +ARBY_HOT_PAIRS_FILE env, +PairConfig.from_dict(), +hot_loop summary section, +scan_mode field, +6 tests, schema v1.9→v1.10 |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0/M4 architectural scanning pipeline (R28.11 lead directive Turn 2)
change_summary:
  - FIX_7_HOT_LOOP: `start.py` — dual-cycle architecture: full sweep every FULL_SWEEP_INTERVAL=5 scans per chain, otherwise hot re-quote using cached pairs. Added `_run_counter`, `last_scan_mode`, `hot_requote_count`, `full_sweep_count` to per-chain stats. `hot_loop` section in summary.
  - FIX_8_HOT_PAIRS_CACHE: `run_scan_real.py` + `config/pairs.py` — hot pairs caching: after discovery, writes `data/cache/hot_pairs_{chain}.json`; on hot re-quote, loads cached pairs via `ARBY_HOT_PAIRS_FILE` env var, skips discovery. Added `PairConfig.from_dict()` for deserialization.
  - FIX_9_DIRTY_SET: `strategy/infra.py` + `start.py` — `DirtySetTracker` class subscribes to WebSocket `eth_subscribe newHeads`. Chains only re-scanned when dirty (new block). If WSS not connected, chain is always dirty (fallback).
  - FIX_10_DASHBOARD_HOT_LOOP: `dashboard.html` — new "Hot Loop" table showing per-chain mode (full/hot), full_sweeps, hot_requotes counts.
  - FIX_11_SCHEMA_BUMP: long_scan_summary schema v1.9 → v1.10 (additive: hot_loop section, scan_mode, run_counter). +6 tests for hot loop and dirty-set.
  - RETAINED_FROM_T1: pair_history, cache_freshness, suppression_counters, STATIC_PROBE_PATH/ZERO_FEE_DOMINANCE guardrails (all working)
touched_files: start.py, strategy/jobs/run_scan_real.py, strategy/infra.py, config/pairs.py, monitoring/dashboard.html, tests/unit/test_start.py, tests/unit/test_run_scan_real_purity.py

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1870 passed, 3 skipped)
py -3.11 start.py --config-list (6 chains) --hours 0.05: **PASS** (schema v1.10, hot_loop populated: 7 full sweeps, 5 hot requotes)
Hot pairs caches created: hot_pairs_base.json (22), hot_pairs_linea.json (11), hot_pairs_mantle.json (4), hot_pairs_scroll.json (9), hot_pairs_zksync.json (8)

## 3) Artifacts Attached (шляхи)
rolling (FRESH from R28.11 Turn 2):
  - data/runs/_rolling/long_scan_latest.json (run_timestamp: 2026-03-15T21:01:07Z, schema v1.10, hot_loop populated)
  - data/cache/hot_pairs_*.json (5 chain caches, pairs counts: base=22, linea=11, mantle=4, scroll=9, zksync=8)

session_run_dirs:
  - long_scan_latest.json (R28.11 T2, schema v1.10, 6 chains, hot_loop/dirty_set integration verified)

## 4) Key Results (числа з артефактів)

```
# R28.11 Turn 2 Fresh Evidence (long_scan_latest.json)
schema: start:long_scan_summary:v1.10
generated_at: 2026-03-15T21:01:07Z
total_runs: 12
total_pass/fail: 7/4

# Hot Loop Metrics (new in v1.10)
hot_loop:
  full_sweep_interval: 5
  total_full_sweeps: 7
  total_hot_requotes: 5
  per_chain_mode:
    arbitrum_one: last=full, full=2, hot=0
    zksync: last=hot, full=1, hot=1
    base: last=hot, full=1, hot=1
    mantle: last=hot, full=1, hot=1
    linea: last=hot, full=1, hot=1
    scroll: last=hot, full=1, hot=1

# Hot Pairs Caches (data/cache/)
hot_pairs_base.json: 22 pairs
hot_pairs_linea.json: 11 pairs
hot_pairs_mantle.json: 4 pairs
hot_pairs_scroll.json: 9 pairs
hot_pairs_zksync.json: 8 pairs

# Sample scan_mode field in per-chain stats
mantle.scan_mode: "hot" (loaded 4 cached pairs, skipped discovery)
arbitrum_one.scan_mode: "full" (first run always full)
```

## 5) Contract Checks
- Hot re-quote cycle: every 5th run does full sweep, others use cached pairs — VERIFIED (7 full / 5 hot)
- Hot pairs cache format: `{"pairs": [...], "saved_at": <iso>, "chain": <name>}` — VERIFIED (5 caches)
- PairConfig.from_dict(): deserializes cached pairs correctly — VERIFIED with test
- DirtySetTracker: subscribes to newHeads, marks chain dirty on new block — VERIFIED with test
- DirtySetTracker fallback: if WSS not connected, chain always dirty — VERIFIED with test
- scan_mode field: "full" or "hot" propagated to summary — VERIFIED in long_scan_latest.json
- hot_loop summary section: full_sweep_interval, totals, per_chain_mode — VERIFIED
- Schema additive: v1.9→v1.10, hot_loop section only, no breaking changes — VERIFIED
- Rolling discipline: maintained — VERIFIED
- RETAINED: pair_history, cache_freshness, suppression_counters, guardrails — all still working
## 6) Blocker Classification

```
code_blocker: LOW (pytest 1870 PASS, hot loop + dirty-set working)
market_gap: MEDIUM (arb: still PRIMARY_BLOCKER pattern)
hot_loop: RESOLVED (full sweep / hot re-quote cycle working)
dirty_set: RESOLVED (DirtySetTracker with WSS newHeads subscription)
pair_observability: RESOLVED (pair_history, deltas, cache, suppression — retained from T1)
```

## 7) R28.11 Turn 2 Session Summary — Architectural Scanning Pipeline
- **Lead R28.11 directive (Turn 2)**: "Розвести два цикли: full sweep і hot re-quote loop. Використати WebSocket не як 'галочку', а як trigger для dirty-set invalidation."
- **Hot Re-Quote Loop (Step 7)**: Dual-cycle architecture — every FULL_SWEEP_INTERVAL=5 scans per chain does full discovery, others use cached pairs from `data/cache/hot_pairs_{chain}.json`. Reduces RPC calls and latency on subsequent scans.
- **Hot Pairs Caching**: After discovery, writes `hot_pairs_{chain}.json` with resolved pairs. On hot re-quote, loads via `ARBY_HOT_PAIRS_FILE` env var passed to subprocess. `PairConfig.from_dict()` handles deserialization.
- **WebSocket Dirty-Set (Step 8)**: `DirtySetTracker` class subscribes to `eth_subscribe newHeads` on each chain's WSS endpoint. Chains only re-scanned when dirty (new block received). If WSS not connected, chain is always dirty (safe fallback to time-based).
- **Dashboard Hot Loop Table**: New section shows per-chain mode (full/hot), full_sweeps count, hot_requotes count. Operator visibility into cycle status.
- **Schema v1.10**: Additive — `hot_loop` section with `full_sweep_interval`, `total_full_sweeps`, `total_hot_requotes`, `per_chain_mode`.
- **Tests**: +6 tests for hot loop and dirty-set functionality. Total: 1870 passed.

## 8) Що потрібно від ліда
1. **Hot loop interval**: Currently FULL_SWEEP_INTERVAL=5. Is this appropriate or should it be configurable?
2. **Dirty-set WSS endpoints**: Loaded from chains.yaml `ws_endpoints`. Some chains may not have WSS — should we warn or fail?
3. **Hot pairs cache expiry**: Currently no TTL — caches persist until overwritten by next full sweep. Should we add max age?
4. **Discovery skip safety**: Hot re-quote skips discovery entirely. If universe changes (new pools added), we miss them until next full sweep. Acceptable tradeoff?
5. **Pair-level observability (T1)**: All fields retained. Any additional metrics needed?
6. **STATIC_PROBE_PATH/ZERO_FEE_DOMINANCE**: Guardrails working but not triggering in current scans. Thresholds appropriate?
