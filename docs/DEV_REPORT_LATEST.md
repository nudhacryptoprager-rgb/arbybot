# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39j**: Per-leg quote-source propagation, WS subscription validation fix, base rq=0→1 improvement. 2370 tests.

## SESSION GOAL (R39j: leg-source propagation + WS fix + base improvement)
**Goal**: (1) Propagate per-leg quote-source aggregation through truth_report/RCA artifacts, (2) Fix WS subscription validation (eth_subscribe error detection), (3) Add contract tests for rq=0 blocker classification, quoter_v2 skip mechanism, WS validation, (4) Verify base quote-path improvement with fresh 10-min 6-chain scan.
**Prior (R39i++)**: 2344 tests, frontier truth fix (degenerate sweep guard + slippage quality gate), falsy coalescing fix.
**Lead directive (R39j)**: "Patch is useful prep layer, not blocker closure. Need measurable KPI shift: base rq>0, MIXED_SOURCE reduction on scroll/mantle, or chains_ws_connected>0."

## 0) Meta
timestamp_utc: 2026-03-24T16:57:59Z
run_dir_name: ci_m5_gate_arbitrum_one_20260324_175718_614983
long_scan_summary: long_scan_latest.json
mode: R39j_LEG_SOURCE_PROPAGATION
test_count: 2370 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.15
code_identity:
  primary: ts:2026-03-24T16:57:59Z
  dirty: true (R39j code changes uncommitted)
  desc: leg_source_aggregation_ws_validation_base_improvement

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39j: leg-source propagation + WS fix + base improvement |
| goal_status | **IN_PROGRESS** |
| close_allowed | false (base rq=1 is improvement but not stable; WS still 0; scroll/mantle MIXED_SOURCE unchanged) |
| remaining_blockers | profitable_rt=0 (economics); scroll/mantle MIXED_SOURCE; WS=0 (public endpoints); base rq=1 (needs stability) |
| fresh_evidence_run | 10-min 6-chain scan (ts:2026-03-24T16:57:59Z), 36 runs, 670s wall |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260324_175718_614983 |
| primary_blocker_of_session | Per-leg source visibility gap: no aggregation in truth_report/RCA artifacts |
| blocker_status_before | ACTIVE: base rq=0 QUOTE_PATH_BLOCKED; scroll/mantle MIXED_SOURCE; WS silent fail |
| blocker_status_after | **PARTIAL**: base rq=0→1 (QUOTE_PATH_BLOCKED→OE_ECONOMICS); WS error detection added; leg_source_summary in artifacts |
| start_metric | 2344 tests, base rq=0, no leg_source in truth_report, WS silent fail |
| end_metric | 2370 tests, base rq=1, leg_source_summary propagated, WS subscription validated |
| delta | +26 tests, 4 code changes (roundtrip + artifacts + run_scan_real + infra), base KPI shift |
| docs_reread_confirmed | true |

## 0.3) Fresh 10-Min Scan Evidence (R39j — 6-chain scan)

```
Wall time:      ~670s (10-min 6-chain scan)
Total runs:     36
Signals total:  302
Net USDC total: $435.97
Profitable RTs: 0 (evaluated: 67)
Sweep best:     -27.36 bps (EXECUTABLE_BEST_NEG, USDC/DAI on arb)
```

### Per-Chain Frontier Ranking (fresh R39j scan)
| Chain | Rank | RQ | Blocker | Best bps | Signals | Key Insight |
|-------|-----:|---:|---------|------:|--------:|-------------|
| arb | 1 | 35 | OE_ECONOMICS | **-27.36** | 239 | Best=USDC/DAI; slippage dominant |
| scroll | 2 | 10 | MIXED_SOURCE | -94.81 | 20 | MIXED_SOURCE still primary blocker |
| mantle | 3 | 4 | MIXED_SOURCE | -307.66 | 0 sig / 7 RT w/o signal | Semantic split persists |
| base | 4 | **1** | **OE_ECONOMICS** | — | 6 | **rq=0→1, QUOTE_PATH_BLOCKED→OE_ECONOMICS** |
| zksync | 5 | 6 | OE_ECONOMICS | — | 24 | Clean but thin; no RT this scan |
| linea | 6 | 5 | OE_ECONOMICS | — | 20 | Economics, not coverage |

### base rq=0→1 Improvement (R39j KPI shift)
Previous session: base had rq=0, blocker QUOTE_PATH_BLOCKED. This session: **rq=1**, blocker reclassified to OE_ECONOMICS. This means at least one quoter_v2 quote succeeded on base. Not yet stable (1 quote across 36 runs), but the quote path is no longer fully blocked.

### Signal Funnel (v1.15 — fresh R39j)
```json
{
  "intent_pairs_total": 42,
  "pairs_after_excludes_total": 41,
  "cross_dex_pairs_total": 40,
  "spread_signals_total": 302,
  "rt_evaluated_total": 67,
  "sweep_reprieve_rt_total": 0,
  "rt_without_signal_total": 7
}
```

### WS Status
`chains_ws_connected: 0` — all 6 chains use public BlastAPI WSS endpoints which do not support `eth_subscribe newHeads`. Subscription validation fix added (infra.py) detects errors instead of silently spinning. Requires premium WS endpoints for actual connectivity.

## 1) Scope
goal (Roadmap): M5_0/M4 -- R39j: per-leg source propagation + WS fix + base improvement
change_summary:
  - **engine/roundtrip.py** — R39j: Added `aggregate_leg_sources()` function: aggregates leg1/leg2 source counts from RoundTripResult list. Returns dict with leg1/leg2 Counter dicts, both_quoter_v2, both_slot0, mixed_source, total.
  - **strategy/artifacts.py** — R39j: Added `leg_source_summary` field to `_build_roundtrip_summary()` — propagates per-leg source aggregation into truth_report.
  - **strategy/jobs/run_scan_real.py** — R39j: Added import + call to `aggregate_leg_sources()` in roundtrip stats dict.
  - **strategy/infra.py** — R39j: Fixed `_ws_loop()` to validate eth_subscribe subscription response — parses JSON, checks for `"error"` key, logs warning and resets instead of silently spinning.
  - **tests/unit/test_roundtrip_canonical_gating.py** — +7 tests: TestLegSourceSummaryInTruthReport (2), TestAggregateLegSources (3), TestBlockerEvidenceRqZeroNotEconomics (2).
  - **tests/unit/test_quote_source_contracts.py** — +4 tests: TestQuoterV2SkipMechanism (threshold, TTL, cycle, base-specific documentation).
  - **tests/unit/test_r38_changes.py** — +3 tests: TestWsSubscriptionValidation (error detection, no-url, bad-url).
  - Prior R39i++ changes: degenerate sweep guard, slippage quality gate, falsy coalescing fix, frontier truth fix.

## 2) Root Cause Analysis

### Layered Blocker Diagnosis (R39j update)
Full audit across chains/dex/config/engine/strategy/discovery. Blockers are layered:
1. **base quote-path** (PARTIALLY RESOLVED): rq=0→1, QUOTE_PATH_BLOCKED→OE_ECONOMICS. 1 executable quote in 36 runs — needs stability.
2. **mixed-source truth loss** on scroll (MIXED_SOURCE rank #2) and mantle (MIXED_SOURCE rank #3) — one executable + one diagnostic leg.
3. **HTTP-only freshness**: WS endpoints configured for all 6 chains but public BlastAPI doesn't support eth_subscribe. chains_ws_connected=0. Subscription error detection now active (infra.py fix).
4. **post-signal economics/slippage** on all healthy chains (arb best -27.36 bps, slippage-dominated).

### Per-Chain Fresh RCA (R39j 10-min scan)
| Chain | Rank | RQ | Blocker | Best bps | Signals | Key Insight |
|-------|-----:|---:|---------|------:|--------:|-------------|
| arb | 1 | 35 | OE_ECONOMICS | -27.36 | 239 | best USDC/DAI; slippage=10.29+gas=17.27 bps |
| scroll | 2 | 10 | MIXED_SOURCE | -94.81 | 20 | slip=186 bps dominates |
| mantle | 3 | 4 | MIXED_SOURCE | -307.66 | 0 sig | 7 RT w/o signal = semantic split |
| base | 4 | **1** | **OE_ECONOMICS** | — | 6 | **rq=0→1 improvement** |
| zksync | 5 | 6 | OE_ECONOMICS | — | 24 | clean but no RT this scan |
| linea | 6 | 5 | OE_ECONOMICS | — | 20 | economics, not coverage |

### Mantle Semantic Split (persists)
rt_without_signal=7 in fresh scan. 0 signals passed 500bps threshold, but RT from OE opportunities via quote path. Not a bug — pipeline architecture feature. `sweep_reprieve_rt` field in signal_funnel exposes this.

### Per-Leg Quote Source Propagation (R39j — new)
`aggregate_leg_sources()` now aggregates leg1/leg2 source from RoundTripResult into `leg_source_summary` dict. Flows into truth_report via `_build_roundtrip_summary()` in artifacts.py. This gives operators visibility into MIXED_SOURCE vs both_quoter_v2 vs both_slot0 distribution per-chain.

### WS Subscription Validation (R39j — new)
`_ws_loop()` in infra.py now validates the `eth_subscribe` response. If server returns `{"error": ...}`, the loop logs a warning and continues to reconnect backoff. Previously, the error JSON was silently ignored and the loop would spin indefinitely waiting for block notifications that never arrive. Root cause: all 6 chains use public BlastAPI WSS endpoints (`wss://*.public.blastapi.io`) which don't support `eth_subscribe newHeads`.

## 3) Universe Contour (42 pairs, unchanged from R39h calibration)

| Chain | Pairs | Cross-Dex | Note |
|-------|------:|----------:|------|
| arbitrum_one | 11 | 11 | Primary chain, best economics |
| base | 9 | 9 | rq=1 now (was 0) |
| zksync | 7 | 6 | ZK/* restored (+anchor prices) |
| linea | 5 | 5 | Economics-blocked |
| scroll | 5 | 5 | MIXED_SOURCE persists |
| mantle | 5 | 4 | 1 excluded; semantic split |
| **Total** | **42** | **40** | |

## 4) Signal Funnel (v1.15 — R39j fresh, see §0.3 for full JSON)

Near-zero attrition (42→41→40). rt_without_signal=7 (mantle semantic split). Funnel shape unchanged from R39i++.

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK
- blocker classification: OK (base reclassified correctly after rq=0→1)
- coverage gate: OK (all chains PASS)
- dual-route contract: OK (locked by R39f tests)
- source coverage: OK
- leg_source_summary: **NEW** — propagated to truth_report via artifacts.py
- WS subscription validation: **NEW** — error detection active in infra.py

## 6) Blockers / Next Steps (prioritized)
1. **base quote-path stability** (P0): rq=0→1 is progress but 1 quote in 36 runs is fragile. Need sustained rq>0 across longer scan. Monitor quoter_v2 skip mechanism (threshold=3, TTL=600s).
2. **scroll/mantle mixed-source** (P1): MIXED_SOURCE still primary blocker. Need both legs using quoter_v2 or both using slot0. Per-leg source aggregation now visible in artifacts — use to diagnose which pairs have mixed legs.
3. **WS connectivity** (P2): chains_ws_connected=0. Public BlastAPI endpoints reject eth_subscribe. Need premium WS endpoints or switch to polling. Subscription validation fix prevents silent spin.
4. **arb economics** (P3): Best -27.36 bps (was -54 bps prior session). Slippage=10.29+gas=17.27 bps. Near-zero is closer but not there.
5. **linea/zksync economics** (P4): Both OE_ECONOMICS. Clean pipeline, thin market.
6. **No intent.txt changes**: 42-pair calibration tier stable.
7. **rt_without_signal**: 7 in fresh scan (was 13). Semantic split narrowing organically.
8. **Session note**: R39j added per-leg quote-source propagation/tests; base partially improved; WS validation active; scroll/mantle MIXED_SOURCE unchanged.
