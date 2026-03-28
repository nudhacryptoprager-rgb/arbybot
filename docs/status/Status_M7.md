# Status: M7 (Triangular Feasibility)

**Status**: **IN PROGRESS** (M7.A — static enumeration + live scorer infrastructure)  
**Updated**: 2026-03-28  
**Scope**: M7.A only — cache-based static enumeration, live measured scorer with per-leg decomposition, same-state provenance classification. No strategy-level verdict is possible until live measured evidence is produced.

---

## M7.A: Triangular Feasibility (read-only research phase)

**Goal** (per `docs/step_M7.md`): build verified pool graph, enumerate 3-hop simple cycles, score with measured-cost discipline, apply provenance and same-state classification, rank by measured final net, and decide whether M7 stops or graduates to M7.B.

**Current sub-step**: steps 1-3 done (static cache), steps 4-7 infrastructure built (live scorer, same-state classifier, runtime graph source). Awaiting live RPC evidence to produce measured artifacts.

### Current Evidence

Evidence source: **local file-backed artifact** `data/tmp/m7a_arbitrum_one_static.json` (not canonical runDir or rolling artifact).  
Generated: 2026-03-28T13:53:22Z  
Provenance tier: **local/session** — sufficient for development iteration, not for strong status claims.

| Metric | Value | Note |
|--------|-------|------|
| Chain | arbitrum_one | — |
| Full graph nodes | 22 | from `pool_resolver_cache` (not live RuntimePair) |
| Full graph edges | 808 | bidirectional |
| M7.A universe nodes | 7 | WETH, USDC, USDT, WBTC, ARB, LINK, PENDLE |
| M7.A universe edges | 278 | filtered by token + adapter + dex |
| Cycles found | >=10000 | **CAP HIT — lower bound, not full count** |
| `max_cycles_cap` | 10000 | enumeration limit |
| `max_cycles_hit` | true | cap was reached |
| `cycles_lower_bound` | true | real count >= 10000 |
| Viable (fee <= 100 bps) | 4838 | 48.4% of capped sample |
| Best diagnostic fee+gas floor (bps) | -50.0 | `total_fee_bps=0.0` + `gas_bps=50.0` |
| Median diagnostic fee+gas cost (bps) | -86.0 | — |
| Worst diagnostic fee+gas cost (bps) | -150.0 | — |
| Two-leg baseline (bps) | -3.5062 | from M4 roundtrip evidence |

**Best cycle decomposition**: 3× Camelot V3 (algebra adapter, dynamic fee=0) → `total_fee_bps=0.0`, `gas_bps=50.0` (placeholder: $0.50 gas on $100 notional), `final_net_bps=-50.0`.

### What this evidence shows

- The M7.A universe (7 tokens × 5 DEXes × 3 adapters) produces at least 10,000 distinct 3-hop cycles on arbitrum_one (capped sample, real count is higher).
- The best diagnostic fee+gas floor (-50.0 bps) is **worse** than the two-leg baseline (-3.5 bps). This is a strong warning but not yet a final stop-condition verdict — live measured scoring may reveal reserve imbalances that overcome this floor.
- This is early static feasibility only. No strategy-level conclusion is allowed until live measured M7.A evidence exists.

### What this evidence does NOT cover

- **No live reserve quotes** — `gross_bps=0.0`, all scores are `same_state_class: AMBIGUOUS`.
- **Placeholder gas model** — `gas_bps=50.0` computed as $0.50 / $100 notional, not measured gas estimation.
- **No slippage modeling** — `total_slippage_bps: 0.0` placeholder.
- **Diagnostic prefilter only** — `score_cycle_fees_only` is not a canonical truth scorer; `provenance_summary: fee_structure_only`.
- **Capped sample** — 10,000 is an enumeration cap, not the full cycle count.
- **Cache-based graph** — built from `pool_resolver_cache`, not from live `RuntimePair` / discovery end-to-end path.

### Remaining M7.A work (per step_M7.md implementation order)

1. ~~Build verified pool graph on arbitrum_one~~ — DONE (cache-based + runtime source via `--source runtime`)
2. ~~Restrict graph to narrow approved universe~~ — DONE
3. ~~Implement 3-hop simple cycle discovery~~ — DONE
4. ~~Score cycles with current measured-cost model~~ — DONE (infrastructure: `score_cycle_measured()` with full per-leg decomposition, gas from quoter estimates + L1, gross_bps from actual quote chain). Awaiting live quote feeding.
5. ~~Emit full decomposition artifacts~~ — DONE (infrastructure: `CycleScore.to_dict()` emits all step_M7.md required fields). Awaiting measured data.
6. ~~Apply provenance and same-state classification~~ — DONE (infrastructure: `classify_same_state()` with block-drift threshold, integrated into `score_cycle_measured()`). Awaiting live block numbers.
7. Rank only by measured final net — **PENDING** (infrastructure ready; needs live quote data to produce non-placeholder rankings)
8. Decide whether M7 stops or graduates to M7.B — **PENDING** (after live measured evidence from steps 4-7)

### Modules

- `engine/triangular_graph.py` — PoolEdge, PoolGraph, M7A constants, graph builders (cache + RuntimePair)
- `engine/triangular_cycles.py` — TriangularCycle, CycleScore, find_3hop_cycles, `score_cycle_fees_only` (diagnostic), `score_cycle_measured` (live per-leg), `classify_same_state`, LegQuote
- `scripts/m7a_enumerate_cycles.py` — CLI with `--source cache|runtime` for static/live graph build
- Tests: 114 M7 tests across 3 test files (2640 total, 0 failures)

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase. It is closed by default and may only open if M7.A proves a repeatable measured edge materially better than the closed public two-leg thesis. Covers atomic multi-hop execution, private submission, and execution state machine for 3-swap trades.
