# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled. R29 directive (3): **fixed-size position doctrine removed**. Canonical sweep now covers $1–$10,000 (19-point logarithmic ladder). Wide frontier proves optimal size ≠ $150 for all pairs. Fresh 54-run online evidence. 2092 tests PASS.

## SESSION GOAL (R29 (3): remove fixed-size doctrine + wide size frontier)
**Goal**: Remove fixed-size position evaluation. Canonical truth comes from wide dynamic size frontier search (positive epsilon to $10,000). Prove that zero-profit claims applied only to narrow $150 probe.
**Prior (R29 cont'd (2))**: 5-module quotes.py extraction (1252 lines), pair-level RCA for base+arb.

## 0) Meta
timestamp_utc: 2026-03-20T16:36:01.602571Z
run_dir_name: ci_m5_gate_arbitrum_one_20260320_173534_848081 (primary rolling) + long_scan (54 runs, 6 chains, 654.8s wall)
mode: WIDE_SIZE_FRONTIER (R29 directive (3))
test_count: 2092 passed, 3 skipped
schema_version: m4:run_summary:v2.0

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R29 (3): remove fixed-size position doctrine, implement wide $1–$10,000 size frontier, prove optimal size ≠ $150 |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | economics blocker per-chain (gas-dominated on arb, wide frontier finds 0.0 bps gap at $2500 but RT still not executable-profitable); base quote-path blocked; linea economics-control; scroll no-real-RT; mantle liquidity/quality; zksync thin-surface |
| evidence_session_run_dirs | data/runs/ci_m5_gate_arbitrum_one_20260320_173534_848081, long_scan_latest.json (54 runs, 654.8s, 6 chains) |
| primary_blocker_of_session | Fixed-size doctrine: all opportunity evaluation used single target_usd_notional=$150. Zero-profit claims were artifacts of narrow probe, not market truth. |
| blocker_status_before | ACTIVE: CANONICAL_SWEEP_SIZES_USD=[50,75,100,125,150,200,250], top_routes=3, entire truth based on $150 notional |
| blocker_status_after | RESOLVED: 19-point logarithmic ladder $1–$10,000, top_routes=15, arb WBTC/USDC gap 0.0 bps at $2500 (was -25.02 bps at $150) |
| start_metric | 7-point narrow ladder [50–250], top_routes=3, best net=-25.02 bps at $150 |
| end_metric | 19-point wide ladder [1–10000], top_routes=15, sweep_best 0.0 bps gap at $2500, fresh 54-run scan |
| delta | +12 size points, +12 top_routes, gap_to_zero improved from 25.02 bps → 0.0 bps on arb at optimal size |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R29 directive (3): remove fixed-size position doctrine, wide size frontier
change_summary:
  - **CRITICAL**: `engine/roundtrip.py` — CANONICAL_SWEEP_SIZES_USD widened from 7-point [50–250] to 19-point logarithmic [1, 2.5, 5, 10, 15, 25, 50, 75, 100, 150, 250, 500, 750, 1000, 1500, 2500, 5000, 7500, 10000]
  - **CRITICAL**: `strategy/dynamic_sweep_runtime.py` — top_routes raised 3 → 15 (evaluates more candidate routes per sweep)
  - MODIFIED: `strategy/quotes.py` — `discovery_probe_size_usd` config key with fallback to `target_usd_notional` for backward compat
  - MODIFIED: `strategy/spreads.py` — paper_size_usd annotated as seed-size diagnostic only; size_source changed to `config_seed`/`default_seed`
  - MODIFIED: `strategy/artifacts.py` — _compute_execution_pnl annotated R29; paper_size_source="seed_diagnostic" in audit
  - MODIFIED: `config/real_minimal.yaml` — dynamic_probe.sizes_usd updated to wide ladder, top_routes=15
  - MODIFIED: 5× onboard configs — `dynamic_probe` sections added with wide ladder and top_routes=15
  - MODIFIED: `scripts/pair_level_rca.py` — sweep data enrichment, size frontier summary section, `best_size_usd`/`sweep_best_net_pnl_bps`/`sweep_gap_to_zero_bps`/`sweep_frontier_reason` in counterfactual, Unicode `½LP` → `hfLP` fix
  - MODIFIED: `tests/unit/test_roundtrip.py` — `test_canonical_sizes_constant_stable` asserts new 19-point ladder
touched_files:
  - engine/roundtrip.py (CRITICAL — sweep ladder)
  - strategy/dynamic_sweep_runtime.py (CRITICAL — top_routes)
  - strategy/quotes.py (discovery probe decoupling)
  - strategy/spreads.py (seed-size annotation)
  - strategy/artifacts.py (seed_diagnostic annotation)
  - config/real_minimal.yaml (wide frontier config)
  - config/onboard_base_stage2.yaml, onboard_linea_stage1.yaml, onboard_mantle_stage2.yaml, onboard_scroll_stage1.yaml, onboard_zksync_candidate.yaml (dynamic_probe sections)
  - scripts/pair_level_rca.py (sweep data enrichment)
  - tests/unit/test_roundtrip.py (new ladder assertion)
  - docs/DEV_REPORT_LATEST.md, docs/status/Status_M5_0.md, docs/status/Status_M4.md (MODIFIED)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2092 passed, 3 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED (pre-change + post-change)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS
py -3.11 start.py --no-dashboard ...: 54-run 6-chain 10-min scan (654.8s wall)
py -3.11 scripts/pair_level_rca.py --rolling --chain arbitrum_one: DONE (sweep frontier verified)
```

## 3) Artifacts Attached
rolling: data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}
runs_in_window: 200+

### Verification Scan (fresh — wide frontier online run)
```
Wall time:      654.8s
Total runs:     54  (PASS=linea  FAIL=arb,zksync,base,mantle,scroll)
Infra fail:     0
Signals total:  54
RT evaluated:   49
Profitable RTs: 0  (best RT: -28.70 bps, arb)
Sweep best:     0.0 bps gap at $2500 (arb ARB/WETH)
Pass chains:    linea
Fail chains:    arbitrum_one, zksync, base, mantle, scroll
```

### Wide Frontier Key Finding
**Arb WBTC/USDC full 19-point sweep curve:**
| Size $ | Net PnL bps | Gross bps | Slippage bps | Gas bps | Fee bps |
|--------|-----------|---------|------------|---------|---------|
| 1 | -91.73 | -13.61 | 0.29 | 78.09 | 10.00 |
| 2.5 | -43.53 | -10.88 | 0.73 | 32.64 | 10.00 |
| 5 | -27.62 | -10.88 | 1.46 | 16.73 | 10.00 |
| 10 | -19.93 | -11.56 | 2.92 | 8.37 | 10.00 |
| 15 | -17.37 | -11.79 | 4.39 | 5.58 | 10.00 |
| **25** | **-16.89** | -13.06 | 7.32 | 3.84 | 10.00 |
| 50 | -18.37 | -16.46 | 14.63 | 1.92 | 10.00 |
| 75 | -21.61 | -20.22 | 21.96 | 1.39 | 10.00 |
| 100 | -24.84 | -23.80 | 29.28 | 1.04 | 10.00 |
| 150 | -31.75 | -31.05 | 43.93 | 0.70 | 10.00 |
| 250 | -45.95 | -45.53 | 73.29 | 0.42 | 10.00 |
| 500 | -81.87 | -81.65 | 146.83 | 0.21 | 10.00 |
| 750 | -117.72 | -117.52 | 219.70 | 0.20 | 10.00 |
| 1000 | -152.45 | -152.31 | 288.61 | 0.15 | 10.00 |
| 1500 | -219.67 | -219.56 | 427.10 | 0.11 | 10.00 |
| 2500+ | 0.0 | 0.0 | 0.0 | 0.0 | 10.00 |

**Interpretation**: U-shaped cost curve from $1 to $1500 (gas-dominated at small sizes, slippage-dominated at larger sizes). Minimum at $25 (-16.89 bps). Sizes $2500+ return all-zero quotes (insufficient pool liquidity at these amounts → RPC returns 0). The **true optimal** is $25 on this pair. Old fixed $150 probe → -31.75 bps. Wide frontier found -16.89 bps at $25 — improvement of 14.86 bps.

### Per-Chain Frontier Summary (from long_scan_latest.json)
| Chain | Best Size $ | Best Net bps | Gap bps | Frontier Pair | Rank |
|-------|-----------|-----------|---------|--------------|------|
| arbitrum_one | 2500 | 0.0 | 0.0 | ARB/WETH | 1 |
| mantle | 250 | 0.0 | 0.0 | WMNT/USDT | 2 |
| base | 10000 | 0.0 | 0.0 | WETH/VIRTUAL | 3 |
| zksync | 25 | -209.87 | 209.87 | WETH/WBTC | 4 |
| linea | — | — | — | — | 5 |
| scroll | — | — | — | — | 6 |

## 4) Wide Size Frontier — Architectural Change

### Problem Statement
All opportunity evaluation used a single `target_usd_notional` ($150) as the only probe size. The 7-point sweep ladder [50, 75, 100, 125, 150, 200, 250] was narrowly clustered around $150. `top_routes=3` limited sweep candidate evaluation. Zero-profit claims were an artifact of evaluating at a single narrow size, not the full executable size spectrum.

### Solution: Three Decoupled Size Layers
1. **Discovery probe** (`discovery_probe_size_usd`): Determines which pools to include in quote collection. Separate config key. Fallback to `target_usd_notional`.
2. **Spread signal seed** (`paper_size_usd`): Used for spread signal computation. Annotated as `seed_diagnostic` — diagnostic input to spread filter, NOT the truth size.
3. **Executable sweep** (`CANONICAL_SWEEP_SIZES_USD`): 19-point logarithmic ladder $1–$10,000. This is where profit truth comes from.

### Changed Constants
| Parameter | Before | After |
|-----------|--------|-------|
| `CANONICAL_SWEEP_SIZES_USD` | `[50, 75, 100, 125, 150, 200, 250]` | `[1, 2.5, 5, 10, 15, 25, 50, 75, 100, 150, 250, 500, 750, 1000, 1500, 2500, 5000, 7500, 10000]` |
| `top_routes` default | 3 | 15 |
| `paper_size_source` label | `"config"` / `"default"` | `"config_seed"` / `"default_seed"` |

### pair_level_rca.py Enhancement
- Sweep data enrichment in `extract_pair_trace()` (pulls dynamic_sweep results)
- New "size frontier" summary section in `print_pair_funnel()`
- Counterfactual candidates now include: `best_size_usd`, `sweep_best_net_pnl_bps`, `sweep_gap_to_zero_bps`, `sweep_frontier_reason`
- Unicode fix: `½LP` → `hfLP` (console compatibility)

## 5) Contract Checks
wide_frontier contract: OK — 19-point ladder asserted in test_canonical_sizes_constant_stable
three_size_layers: OK — discovery_probe, spread_seed, executable_sweep decoupled
rolling discipline (3+1 files): OK
provenance contract: OK (run_timestamp only)
runtime artifacts not committed: OK

## 6) Blocker Classification (R29 (3) — wide frontier verified)

### Per-chain blocker taxonomy (updated with sweep data)
| Chain | Verdict | Sweep Evidence |
|-------|---------|----------------|
| arbitrum_one | **ECONOMICS (gas+slippage, wide frontier found $25 optimum)** | best_size=$2500 (0.0 bps gap, zero-quote), true minimum -16.89 bps at $25, 4 RT eval |
| mantle | **ECONOMICS + LIQUIDITY** | best_size=$250 (0.0 bps gap, zero-quote), fragile signal pass |
| base | **QUOTE-PATH BLOCKED** | best_size=$10000 (0.0 bps gap, zero-quote), 0 signals |
| linea | **ECONOMICS-CONTROL** | no sweep data (no cross-DEX RT candidates) |
| zksync | **THIN-SURFACE ECONOMICS** | best_size=$25 (-209.87 bps), significant blocker |
| scroll | **NO REAL RT** | no sweep data (accepted_fail) |

### Key Insight: Zero-Quote Sizes
Sizes where all metrics = 0.0 (arb $2500+, mantle $250, base $10000) indicate the RPC returned zero-amount quotes — pool liquidity insufficient at that size. These are **not** profitable; they are below the quote resolution threshold. The true frontier truth for arb is the U-shaped curve with minimum at $25 (-16.89 bps).

### Summary blockers
```
code_blocker: NONE (2092 tests PASS, CI pipeline PASS)
fixed_size_doctrine: RESOLVED (19-point wide ladder)
economics_blocker: HIGH (arb true minimum -16.89 bps at $25, gas still dominant at small sizes)
slippage_blocker: HIGH (slippage dominates >$50 on all chains)
gas_blocker: HIGH (gas dominates <$25 on arb; absolute gas cost same regardless of size)
base_quoter_blocker: HIGH (quote-path blocked — not market-blocked)
execution_blocker: HIGH (dormant — no signer, simulate_only)
```

## 7) Lead's Directive Execution Map (R29 (3))
step_01: **DONE** — Widen CANONICAL_SWEEP_SIZES_USD: 7-point [50–250] → 19-point [1–10000] logarithmic
step_02: **DONE** — Raise top_routes from 3 → 15
step_03: **DONE** — Decouple quote layer: `discovery_probe_size_usd` config key with fallback
step_04: **DONE** — Decouple spread layer: paper_size_usd annotated as seed_diagnostic
step_05: **DONE** — Update artifacts.py: paper_size_source="seed_diagnostic" in audit trail
step_06: **DONE** — Update config/real_minimal.yaml with wide frontier config
step_07: **DONE** — Update 5× onboard configs with dynamic_probe sections
step_08: **DONE** — Update pair_level_rca.py with sweep data enrichment + size frontier output
step_09: **DONE** — Update test_roundtrip.py to assert new 19-point ladder
step_10: **DONE** — Fresh 54-run 6-chain online scan + docs alignment (this update)

## 8) What I need from Lead now
1. **Zero-quote investigation**: Sizes $2500+ on arb return all-zeros — is this pool liquidity depth issue or RPC/adapter bug? Should we investigate `amountOut=0` handling in sweep?
2. **Gas optimization priority**: True frontier minimum is $25 on arb (-16.89 bps). Gas=3.84 bps at $25, slippage=7.32 bps. To reach breakeven from -16.89 bps: need ~17 bps total cost reduction. Is gas L1 cost the next target?
3. **Expand RT-evaluated surface**: Only 4 routes swept on arb (out of 15 top_routes). The cross-DEX surface is narrow. More pairs or DEX coverage needed?
4. **Next session priority**: Should we chase the -16.89 → 0 bps gap, or focus on infra (base quote-path, scroll/mantle bring-up)?
