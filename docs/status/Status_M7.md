# Status: M7 (Triangular Feasibility)

**Status**: **IN PROGRESS** (M7.A — temporal repeatability established, bounded size sweep infrastructure added, negative sign consistent, verdict pending)  
**Updated**: 2026-03-28  
**Scope**: M7.A only — runtime graph sourcing, live measured scoring with per-leg RPC quotes, same-state provenance classification, measured-only ranking separated from fee-only fallback, bounded size sweep over canonical size ladder. The first end-to-end runtime+measured M7.A scan is now real and verified across multiple blocks, but it remains a bounded local R&D artifact rather than an operational runDir/rolling scan. Wider sampling and temporal repeatability are now established; the negative sign is consistent across all runs. Size sweep infrastructure (`--sweep-top N`) added to test economics across the full canonical size ladder.

---

## M7.A: Triangular Feasibility (read-only research phase)

**Goal** (per `docs/step_M7.md`): build verified pool graph, enumerate 3-hop simple cycles, score with measured-cost discipline, apply provenance and same-state classification, rank by measured final net, and decide whether M7 stops or graduates to M7.B.

**Current sub-step**: steps 1-7 done (runtime graph + live measured + measured-only ranking). Step 8 (verdict) now informed by temporal repeatability evidence: negative sign confirmed across 5 independent runs at different blocks. Formal verdict requires review discussion.

### Current Evidence — Temporal Repeatability (5 runtime+measured runs)

Evidence source: **local file-backed artifacts** in `data/tmp/` (not canonical runDir or rolling artifacts).  
Generated: 2026-03-28 (during session)  
Provenance tier: **local/session** — R&D evidence with temporal diversity across 5 independent blocks.

| Run | Block | Scored | Failed | Best Net (bps) | Median Net (bps) | Promoted | SS Proven |
|-----|-------|--------|--------|----------------|-------------------|----------|-----------|
| narrow (20) | 446589515 | 12 | 8 | **-13.42** | -1159.12 | 0 | 12 |
| wide (100) | 446620909 | 67 | 33 | **-22.11** | -386.15 | 0 | 67 |
| snap_1 | 446621713 | 12 | 8 | **-27.70** | -1183.86 | 0 | 12 |
| snap_2 | 446621956 | 12 | 8 | **-31.19** | -1183.71 | 0 | 12 |
| snap_3 | 446622133 | 12 | 8 | **-31.11** | -1183.70 | 0 | 12 |

All runs: `graph_source="runtime"`, `score_mode="measured"`, `same_state_proven=100%`, `promoted=0`.  
Two-leg baseline: **-3.5062 bps** (from M4 roundtrip evidence in `long_scan_latest.json`).

Artifacts: `m7a_runtime_measured.json`, `m7a_runtime_measured_wide.json`, `m7a_snap_1.json`, `m7a_snap_2.json`, `m7a_snap_3.json`.

### Previous Evidence — Cache+Measured (historical)

Evidence source: **local file-backed artifact** `data/tmp/m7a_measured_test.json`.  
Generated: 2026-03-28 (earlier in session)  
Provenance tier: **local/session** — superseded by runtime+measured above.

| Metric | Value | Note |
|--------|-------|------|
| Graph source | **cache** | `pool_resolver_cache` |
| Score mode | **measured** | live RPC per-leg quotes |
| Block number | 446581074 | — |
| Cycles quoted | **17**/20 | — |
| Same-state PROVEN | **17** | — |
| Best measured net (bps) | **-372.70** | much worse than runtime path |

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

- **Temporal repeatability established**: negative sign reproduced across 5 independent runs at different blocks (446589515 → 446622133). Best net ranges from -13.42 to -31.19 bps. No run produced a promoted cycle.
- **End-to-end runtime+measured pipeline operational**: graph from live RuntimePair discovery → fee-only prerank → RPC per-leg quotes → `score_cycle_measured` → measured-only ranking, all in one command.
- **Same-state provenance works**: 100% of quoted cycles across all 5 runs classified as `same_state_proven`.
- **Wider sampling confirms negative**: wide run (67 scored cycles) best is -22.11 bps; no hidden profitable cycles in the wider set.
- **All top cycles are ARB→USDC→WETH→ARB variants**: same token triple across all camelot_v3, pancakeswap_v3, uniswap_v3, sushiswap_v3 DEX combinations. No diverse token-path surfaced.
- **Triangular consistently worse than two-leg**: best measured -13.42 bps vs two-leg baseline -3.5 bps — triangular adds ~10 bps extra cost for the third leg.
- **VE33 adapters have high failure rate**: ~33-40% of attempted cycles fail with VE33 (Ramses) reverts on-chain.

### What this evidence does NOT yet cover

- **Size sweep not yet executed** — infrastructure added (`--sweep-top N`) but no live sweep artifact produced yet. Run with `--sweep-top 10` to produce size curves.
- **L1 gas is a static estimate** — `l1_cost_wei` uses a fixed 6 Gwei heuristic, not live L1 calldata cost from the chain.
- **Artifact is `data/tmp/` provenance** — not in `data/runs/<runDir>/` or rolling artifacts; not operational-grade.
- **Narrow universe only** — 7 tokens on arbitrum_one; other tokens or chains may have different economics.

### Remaining M7.A work (per step_M7.md implementation order)

1. ~~Build verified pool graph on arbitrum_one~~ — DONE (cache-based + runtime source via `--source runtime`)
2. ~~Restrict graph to narrow approved universe~~ — DONE
3. ~~Implement 3-hop simple cycle discovery~~ — DONE
4. ~~Score cycles with current measured-cost model~~ — **DONE** (live: `score_cycle_measured()` fed by `leg_quote_from_rpc_result()` from live per-leg RPC quotes via `_quote_single_leg()` → `quote_cycle_3legs()`)
5. ~~Emit full decomposition artifacts~~ — **DONE** (measured artifacts include provenance, same_state, gross_bps, gas_bps, fee metadata)
6. ~~Apply provenance and same-state classification~~ — **DONE** (100% same_state_proven across all 5 temporal runs)
7. ~~Rank only by measured final net~~ — **DONE** (`--score measured` mode ranks measured-only cycles by `final_net_bps`; fee-only fallback rows emitted separately in `diagnostic_fee_only_fallbacks`)
8. Decide whether M7 stops or graduates to M7.B — **PENDING** (evidence strongly negative: 5 runs, 0 promoted, best -13.42 bps vs two-leg baseline -3.5 bps; temporal repeatability established but formal verdict requires review discussion)

### Modules

- `engine/triangular_graph.py` — PoolEdge, PoolGraph, M7A constants, graph builders (cache + RuntimePair)
- `engine/triangular_cycles.py` — TriangularCycle, CycleScore (with `scored_size_usd`, slippage `_heuristic` fields), find_3hop_cycles, `score_cycle_fees_only` (diagnostic), `score_cycle_measured` (live per-leg), `classify_same_state`, LegQuote, `leg_quote_from_rpc_result`, SizeSweepResult, SizeSweepPoint
- `scripts/m7a_enumerate_cycles.py` — CLI with `--source cache|runtime`, `--score fees|measured`, `--max-scored N`, `--sweep-top N`. Measured mode: measured-only ranking (`top_10_by_net`, `best_net_bps`) with fee-only fallback rows emitted separately in `diagnostic_fee_only_fallbacks`. Size sweep reuses `CANONICAL_SWEEP_SIZES_USD` from `engine/roundtrip.py`. Token prices imported from `strategy.quotes.DEFAULT_TOKEN_USD_PRICES`.
- Tests: 136 M7 tests across 3 test files (2660 total, 0 failures)

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase. It is closed by default and may only open if M7.A proves a repeatable measured edge materially better than the closed public two-leg thesis. Covers atomic multi-hop execution, private submission, and execution state machine for 3-swap trades.
