# Status: M7 (Triangular Feasibility)

**Status**: **IN PROGRESS** (M7.A — runtime+measured size-sweep evidence produced; blocker decomposition confirms all 6 structural blockers active. Verdict pending formal review.)  
**Updated**: 2026-03-28  
**Scope**: M7.A only — runtime graph sourcing, live measured scoring with per-leg RPC quotes, same-state provenance classification, measured-only ranking separated from fee-only fallback, bounded size sweep over canonical size ladder (19 notionals, $1–$10K), machine-readable blocker summary with 6 canonical blocker tags. Size sweep executed: 10 top cycles × 19 sizes = 190 RPC quote sets. All cycles negative at all sizes. Blocker RCA: GROSS_NEGATIVE_CORE + GAS_DOMINANT_SMALL + SLIPPAGE_DOMINANT_LARGE dominate. Triangular consistently 6× worse than two-leg baseline.

---

## M7.A: Triangular Feasibility (read-only research phase)

**Goal** (per `docs/step_M7.md`): build verified pool graph, enumerate 3-hop simple cycles, score with measured-cost discipline, apply provenance and same-state classification, rank by measured final net, and decide whether M7 stops or graduates to M7.B.

**Current sub-step**: steps 1-7 done (runtime graph + live measured + measured-only ranking). Step 8 (verdict) now informed by three evidence tiers: (a) temporal repeatability across 5 blocks, (b) bounded size sweep across 19 notionals on top 10 cycles, (c) machine-readable blocker RCA with 6 canonical tags. All tiers confirm negative sign at all sizes with structural blockers identified. Formal verdict pending review discussion.

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

### Current Evidence — Size Sweep (10 cycles × 19 sizes)

Evidence source: **local file-backed artifact** `data/tmp/m7a_runtime_measured_sweep.json`.  
Generated: 2026-03-28T19:13:34Z  
Provenance tier: **local/session** — first bounded size sweep, reuses `CANONICAL_SWEEP_SIZES_USD` from `engine/roundtrip.py`.  
Block: **446635245** — all 190 quote sets at same block (same_state_proven=100%).

| Rank | Route (DEX combo) | Best Size (USD) | Best Net (bps) | Quoted | Curve Shape |
|------|-------------------|-----------------|----------------|--------|-------------|
| 1 | ARB→USDC→WETH→ARB (cam/pcs/pcs) | **100** | **-20.96** | 19/19 | U-shape, min at $100 |
| 2 | ARB→USDC→WETH→ARB (cam/uni/pcs) | **100** | **-20.99** | 19/19 | U-shape, min at $100 |
| 3 | ARB→USDC→WETH→ARB (cam/cam/pcs) | **150** | **-22.97** | 19/19 | U-shape, min at $150 |
| 4 | ARB→USDC→WETH→ARB (cam/pcs/cam) | **250** | **-22.31** | 19/19 | U-shape, min at $250 |
| 5 | ARB→USDC→WETH→ARB (cam/uni/cam) | **150** | **-23.42** | 19/19 | U-shape, min at $150 |
| 6 | ARB→USDC→WETH→ARB (cam/pcs/uni) | **250** | **-24.36** | 19/19 | U-shape, min at $250 |
| 7 | ARB→USDC→WETH→ARB (cam/uni/uni) | **150** | **-25.31** | 19/19 | U-shape, min at $150 |
| 8 | ARB→USDC→WETH→ARB (cam/cam/cam) | **250** | **-24.24** | 19/19 | U-shape, min at $250 |
| 9 | ARB→USDC→WETH→ARB (pcs/pcs/cam) | **150** | **-25.51** | 19/19 | U-shape, min at $150 |
| 10 | ARB→USDC→WETH→ARB (cam/cam/uni) | **250** | **-26.29** | 19/19 | U-shape, min at $250 |

Key observations:
- **All cycles negative at all 19 sizes** — no profitable notional exists in $1–$10K range.
- **Size curve universally U-shaped**: small sizes ($1–$10) dominated by gas (~-1000 bps); optimal at $100–$250; large sizes ($5K+) dominated by slippage.
- **Best overall: -20.96 bps at $100** — even the optimal size+route is 6× worse than two-leg baseline (-3.5 bps).
- **100% quote success**: 190/190 size×cycle combinations quoted at block 446635245.
- **All routes are ARB→USDC→WETH→ARB**: identical token triple, only differing by DEX combination.

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
- **Triangular consistently worse than two-leg**: best measured -13.42 bps (single-shot) / -20.96 bps (sweep-optimized) vs two-leg baseline -3.5 bps — triangular adds 10-17 bps extra cost for the third leg.
- **Size sweep confirms no profitable notional**: U-shaped size curves across all 10 top cycles; gas dominates at small sizes, slippage dominates at large sizes; optimal range $100–$250 is still deeply negative.
- **VE33 adapters have high failure rate**: ~33-40% of attempted cycles fail with VE33 (Ramses) reverts on-chain.

### Current Evidence — Blocker Decomposition (machine-readable RCA)

Evidence source: `blocker_summary` block from `scripts/m7a_enumerate_cycles.py` with `--score measured --sweep-top N`.  
Computed against: block **446635245**, 10 top cycles × 19 sizes, 67 measured routes.

| Metric | Value | Interpretation |
|--------|-------|----------------|
| `best_route_gross_bps` | **-9.305** | Best route loses money before any costs |
| `best_route_gas_bps` | **11.6555** | Gas adds 11.66 bps on top of negative gross |
| `best_route_total_fee_bps` | **6.0** | Protocol fees add another 6 bps |
| `best_route_net_bps` | **-20.9605** | Final net at optimal $100 |
| `best_route_best_size_usd` | **100** | Optimal notional (from sweep) |
| `small_size_gas_domination` | **true** | At $1: -1052 bps (gas crushes small sizes) |
| `large_size_slippage_domination` | **true** | At $10K: -802 bps (slippage crushes large) |
| `same_state_proven_rate` | **1.0** | 100% same-state proven |
| `route_failure_rate` | **0.33** | 33% VE33 adapter quote failures |
| `token_triple_concentration` | **1.0** | 100% ARB/USDC/WETH — zero diversity |

**Blocker tags** (ordered by frequency, 10 cycles analyzed):

| Tag | Count | Meaning |
|-----|-------|---------|
| `GROSS_NEGATIVE_CORE` | 10/10 | Reserve economics negative before costs |
| `GAS_DOMINANT_SMALL` | 10/10 | Gas dominates at small notionals |
| `SLIPPAGE_DOMINANT_LARGE` | 10/10 | Slippage dominates at large notionals |
| `THIRD_LEG_FEE_BINDING` | 6/10 | Third leg fee adds ≥5 bps |
| `SINGLE_TRIPLE_CONCENTRATION` | all | Zero token-path diversity |
| `QUOTE_FAILURE_BREADTH_LIMIT` | all | VE33 failures limit route breadth |

**Key diagnostic insight**: The problem is NOT only gas. The top route has `gross_bps = -9.305` — the reserve economics themselves are negative. Gas (-11.66 bps) and fees (-6.0 bps) compound the loss. The third leg adds cost without creating enough value to offset the inherent negative gross of the triangular path through current on-chain reserves.

### What this evidence does NOT yet cover

- **L1 gas is a static estimate** — `l1_cost_wei` uses a fixed 6 Gwei heuristic, not live L1 calldata cost from the chain.
- **Artifact is `data/tmp/` provenance** — not in `data/runs/<runDir>/` or rolling artifacts; not operational-grade.
- **Narrow universe only** — 7 tokens on arbitrum_one; other tokens or chains may have different economics.
- **Single-block sweep** — all 190 quotes at block 446635245; no temporal diversity within this sweep (but 5-block temporal diversity from prior runs).

### Remaining M7.A work (per step_M7.md implementation order)

1. ~~Build verified pool graph on arbitrum_one~~ — DONE (cache-based + runtime source via `--source runtime`)
2. ~~Restrict graph to narrow approved universe~~ — DONE
3. ~~Implement 3-hop simple cycle discovery~~ — DONE
4. ~~Score cycles with current measured-cost model~~ — **DONE** (live: `score_cycle_measured()` fed by `leg_quote_from_rpc_result()` from live per-leg RPC quotes via `_quote_single_leg()` → `quote_cycle_3legs()`)
5. ~~Emit full decomposition artifacts~~ — **DONE** (measured artifacts include provenance, same_state, gross_bps, gas_bps, fee metadata)
6. ~~Apply provenance and same-state classification~~ — **DONE** (100% same_state_proven across all 5 temporal runs)
7. ~~Rank only by measured final net~~ — **DONE** (`--score measured` mode ranks measured-only cycles by `final_net_bps`; fee-only fallback rows emitted separately in `diagnostic_fee_only_fallbacks`)
8. Decide whether M7 stops or graduates to M7.B — **PENDING** (evidence strongly negative: 5 temporal runs + 1 size sweep + blocker RCA, 0 promoted at any size, best -20.96 bps at optimal $100 notional vs two-leg baseline -3.5 bps; all 6 blocker tags active (GROSS_NEGATIVE_CORE 10/10, GAS_DOMINANT_SMALL 10/10, SLIPPAGE_DOMINANT_LARGE 10/10, THIRD_LEG_FEE_BINDING 6/10, SINGLE_TRIPLE_CONCENTRATION, QUOTE_FAILURE_BREADTH_LIMIT); all evidence tiers confirm M7.A should not graduate to M7.B; formal verdict requires review discussion)

### Modules

- `engine/triangular_graph.py` — PoolEdge, PoolGraph, M7A constants, graph builders (cache + RuntimePair)
- `engine/triangular_cycles.py` — TriangularCycle, CycleScore (with `scored_size_usd`, slippage `_heuristic` fields), find_3hop_cycles, `score_cycle_fees_only` (diagnostic), `score_cycle_measured` (live per-leg), `classify_same_state`, LegQuote, `leg_quote_from_rpc_result`, SizeSweepResult, SizeSweepPoint
- `scripts/m7a_enumerate_cycles.py` — CLI with `--source cache|runtime`, `--score fees|measured`, `--max-scored N`, `--sweep-top N`. Measured mode: measured-only ranking (`top_10_by_net`, `best_net_bps`) with fee-only fallback rows emitted separately in `diagnostic_fee_only_fallbacks`. Size sweep reuses `CANONICAL_SWEEP_SIZES_USD` from `engine/roundtrip.py`. Token prices imported from `strategy.quotes.DEFAULT_TOKEN_USD_PRICES`. Blocker analysis: `_build_blocker_summary()` and `classify_blocker_tags()` produce machine-readable RCA with 6 canonical blocker tags (`GROSS_NEGATIVE_CORE`, `GAS_DOMINANT_SMALL`, `SLIPPAGE_DOMINANT_LARGE`, `THIRD_LEG_FEE_BINDING`, `SINGLE_TRIPLE_CONCENTRATION`, `QUOTE_FAILURE_BREADTH_LIMIT`).
- Tests: 151 M7 tests across 3 test files (2675 total, 0 failures)

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase. It is closed by default and may only open if M7.A proves a repeatable measured edge materially better than the closed public two-leg thesis. Covers atomic multi-hop execution, private submission, and execution state machine for 3-swap trades.
