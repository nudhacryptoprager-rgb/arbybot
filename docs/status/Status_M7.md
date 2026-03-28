# Status: M7 (Triangular Feasibility)

**Status**: **IN PROGRESS** (M7.A Static Enumeration)  
**Updated**: 2026-03-28  
**Scope**: M7.A only — static triangular cycle enumeration and fee-floor analysis.

---

## M7.A: Static Enumeration

**Goal**: prove that triangular (3-hop) cycle paths exist in the discovered pool graph, enumerate their fee structures, and assess whether a fee floor below the two-leg baseline exists.

### Current Evidence

Evidence artifact: `data/tmp/m7a_arbitrum_one_static.json`  
Generated: 2026-03-28T13:53:22Z

| Metric | Value | Note |
|--------|-------|------|
| Chain | arbitrum_one | — |
| Full graph nodes | 22 | from `pool_resolver_cache` |
| Full graph edges | 808 | bidirectional |
| M7.A universe nodes | 7 | WETH, USDC, USDT, WBTC, ARB, LINK, PENDLE |
| M7.A universe edges | 278 | filtered by token + adapter + dex |
| Cycles found | 10000 | **CAP HIT — lower bound, not full count** |
| `max_cycles_cap` | 10000 | enumeration limit |
| `max_cycles_hit` | true | cap was reached |
| `cycles_lower_bound` | true | real count >= 10000 |
| Viable (fee <= 100 bps) | 4838 | 48.4% of sample |
| Best fee floor (bps) | -50.0 | sum of three leg fees |
| Median fee cost (bps) | -86.0 | — |
| Worst fee cost (bps) | -150.0 | — |
| Two-leg baseline (bps) | -3.5062 | from M4 roundtrip evidence |

### Interpretation

- The M7.A universe (7 tokens × 5 DEXes × 3 adapters) produces at least 10,000 distinct 3-hop cycles on arbitrum_one.
- The best fee floor (-50.0 bps) is **worse** than the two-leg baseline (-3.5 bps), meaning fees alone do not justify triangular paths.
- However, this is a **fee-only diagnostic** — live reserves, slippage, and gas are not yet modeled. The hypothesis is that reserve imbalances across three legs may produce gross profit exceeding the fee floor, which requires live scoring (M7.B).

### What M7.A does NOT prove

- No live reserve quotes — all scores are `same_state_class: AMBIGUOUS`.
- No gas estimation — `gas_bps: 0.0` placeholder.
- No slippage modeling — `total_slippage_bps: 0.0` placeholder.
- `score_cycle_fees_only` is a diagnostic prefilter, not a canonical truth scorer.
- 10,000 is a capped sample, not the full cycle count.

### Modules

- `engine/triangular_graph.py` — PoolEdge, PoolGraph, M7A constants, graph builders
- `engine/triangular_cycles.py` — TriangularCycle, CycleScore, find_3hop_cycles, scoring/filtering
- `scripts/m7a_enumerate_cycles.py` — CLI for static enumeration
- Tests: 87+ M7 tests across 3 test files

---

## M7.B: Live Scoring (NOT STARTED)

Planned: live multi-call reserve quoting, same-state verification, gas estimation, slippage modeling. Depends on M7.A completion.

---

## M7.C: Artifact Integration (NOT STARTED)

Planned: feed viable triangular cycles into the opportunity engine pipeline alongside two-leg roundtrips.
