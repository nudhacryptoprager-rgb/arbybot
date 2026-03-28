# Status: M7 (Triangular Feasibility)

**Status**: **IN PROGRESS** (M7.A — first live measured evidence produced, verdict pending)  
**Updated**: 2026-03-28  
**Scope**: M7.A only — cache-based static enumeration, live measured scorer with per-leg RPC quotes, same-state provenance classification. First measured truth produced; verdict requires wider sampling.

---

## M7.A: Triangular Feasibility (read-only research phase)

**Goal** (per `docs/step_M7.md`): build verified pool graph, enumerate 3-hop simple cycles, score with measured-cost discipline, apply provenance and same-state classification, rank by measured final net, and decide whether M7 stops or graduates to M7.B.

**Current sub-step**: steps 1-6 done (static cache + live measured). Step 7 (ranking by measured net) operational. Step 8 (verdict) requires broader universe sampling before decision.

### Current Evidence — Measured (live RPC)

Evidence source: **local file-backed artifact** `data/tmp/m7a_measured_test.json` (not canonical runDir or rolling artifact).  
Generated: 2026-03-28 (during session)  
Provenance tier: **local/session** — first live measured evidence; not yet production-grade.

| Metric | Value | Note |
|--------|-------|------|
| Chain | arbitrum_one | — |
| Score mode | **measured** | live RPC per-leg quotes |
| Block number | 446581074 | single block for all quotes |
| Cycles attempted (measured) | 20 | top-20 by fee-only prerank |
| Cycles successfully quoted | **17** | 3 failed (adapter dispatch or no liquidity) |
| Same-state PROVEN | **17** | 100% of quoted — all quotes from same block |
| Same-state VIOLATED | 0 | — |
| Promoted | **0** | no profitable cycle found |
| Best measured net (bps) | **-372.70** | live gross + gas from quoter |
| Best fee-only prefilter (bps) | -50.0 | diagnostic (unchanged from static pass) |
| Two-leg baseline (bps) | -3.5062 | from M4 roundtrip evidence |

### Current Evidence — Static (cache-based)

Evidence source: **local file-backed artifact** `data/tmp/m7a_arbitrum_one_static.json`.  
Generated: 2026-03-28T13:53:22Z  

| Metric | Value | Note |
|--------|-------|------|
| Full graph nodes | 22 | from `pool_resolver_cache` |
| Full graph edges | 808 | bidirectional |
| M7.A universe nodes | 7 | WETH, USDC, USDT, WBTC, ARB, LINK, PENDLE |
| M7.A universe edges | 278 | filtered by token + adapter + dex |
| Cycles found | >=10000 | **CAP HIT — lower bound, not full count** |
| Viable (fee <= 100 bps) | 4838 | 48.4% of capped sample |
| Median diagnostic fee+gas cost (bps) | -86.0 | — |

### What the measured evidence shows

- **Same-state provenance works**: 17/17 quoted cycles classified as `same_state_proven` (all quotes returned within same block).
- **No profitable triangular path found in top-20**: best measured net is -372.7 bps, far worse than the two-leg baseline (-3.5 bps) and the diagnostic fee-only floor (-50.0 bps).
- **Fee-only was overly optimistic**: the fee-only prefilter estimated -50 bps floor, but real measured quotes (with actual reserve-based pricing) yield -372 bps. This means the "Camelot dynamic-fee=0" cycles have poor reserves — the zero-fee advantage is swamped by adverse reserve ratios.
- **Quote success rate is high**: 85% (17/20) of attempted cycles returned valid quotes.
- **End-to-end wiring confirmed**: RPC quote → `leg_quote_from_rpc_result` → `score_cycle_measured` pipeline operational.

### What this evidence does NOT yet cover

- **Only top-20 cycles measured** — wider sampling (200+) may surface cycles missed in the prerank.
- **Single block snapshot** — no temporal diversity; prices at block 446581074 may not be representative.
- **$100 notional only** — higher/lower notional may change gas_bps ratio.
- **Cache-based graph** — graph built from `pool_resolver_cache`, not from live `RuntimePair` discovery.
- **No L1 gas component** — gas_bps uses quoter-estimated gas at fixed gas price, not L1 calldata cost.

### Remaining M7.A work (per step_M7.md implementation order)

1. ~~Build verified pool graph on arbitrum_one~~ — DONE (cache-based + runtime source via `--source runtime`)
2. ~~Restrict graph to narrow approved universe~~ — DONE
3. ~~Implement 3-hop simple cycle discovery~~ — DONE
4. ~~Score cycles with current measured-cost model~~ — **DONE** (live: `score_cycle_measured()` fed by `leg_quote_from_rpc_result()` from live per-leg RPC quotes via `_quote_single_leg()` → `quote_cycle_3legs()`)
5. ~~Emit full decomposition artifacts~~ — **DONE** (measured artifacts include provenance, same_state, gross_bps, gas_bps, fee metadata)
6. ~~Apply provenance and same-state classification~~ — **DONE** (live: 17/17 proven at block 446581074)
7. ~~Rank only by measured final net~~ — **DONE** (`--score measured` mode ranks by `final_net_bps` mixing measured + fee-only fallback)
8. Decide whether M7 stops or graduates to M7.B — **PENDING** (early evidence strongly negative: -372 bps; wider sampling needed before definitive stop-condition)

### Modules

- `engine/triangular_graph.py` — PoolEdge, PoolGraph, M7A constants, graph builders (cache + RuntimePair)
- `engine/triangular_cycles.py` — TriangularCycle, CycleScore, find_3hop_cycles, `score_cycle_fees_only` (diagnostic), `score_cycle_measured` (live per-leg), `classify_same_state`, LegQuote, `leg_quote_from_rpc_result`
- `scripts/m7a_enumerate_cycles.py` — CLI with `--source cache|runtime`, `--score fees|measured`, `--max-scored N`. Dispatches to `read_quoter_v2`/`read_algebra_quoter`/`read_ve33_amount_out` per adapter type.
- Tests: 125 M7 tests across 3 test files (2651 total, 0 failures)

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase. It is closed by default and may only open if M7.A proves a repeatable measured edge materially better than the closed public two-leg thesis. Covers atomic multi-hop execution, private submission, and execution state machine for 3-swap trades.
