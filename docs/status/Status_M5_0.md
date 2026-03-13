# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-13 (R23)
**Tests**: 1708 passed, 2 skipped
**Schema**: start:long_scan_summary:v1.4
**Evidence runDirs**: ci_m5_gate_20260313_182507 (arb rolling R23), 14 total runs across 6 chains
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}`
**Evidence long scan**: `data/runs/_rolling/long_scan_latest.json` (multi-chain frontier ranking with drift metrics, generated 2026-03-13T17:27:42Z)

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> R23: operational_truth_source = "measured_economics" (sole truth for profit claims).

---

## Chain Quality Classification (R23)

```
arbitrum_one:   SIGNAL_PRODUCING (primary, rolling, truth_probe, cross-dex=3, 3/3 PASS, blocker=NONE)
base:           SIGNAL_PRODUCING (discovery, cross-dex=15, SUSPECT_SPREAD, 3/3 PASS, blocker=MIXED)
mantle:         SIGNAL_PRODUCING (discovery, same-dex agni_v3, 2/2 PASS, blocker=STRUCTURAL)
zksync:         SIGNAL_PRODUCING (discovery, cross-dex=10, 33.7% drift, 2/2 PASS, blocker=MIXED)
linea:          SIGNAL_PRODUCING (discovery, same-dex pancakeswap_v3, 2/2 PASS, blocker=STRUCTURAL)
scroll:         INFRA_READY (monitoring_only, single DEX, accepted-fail, 0/2 PASS, blocker=ECOSYSTEM_BLOCKED)
```

**Universe Split (R23)**:
- **truth_probe**: arbitrum_one (frontier_ready, target_for_truth_probe=true)
- **discovery**: base, linea, mantle, zksync (cross-dex work, not frontier_ready)
- **monitoring_only**: scroll (PROBE_ONLY, accepted-fail)

**R23 scan result**: 5 PASS chains / 1 accepted-fail (scroll) / 14 total runs / 48 signals / $46.63 net
**Roundtrip evaluation**: CANONICAL SWEEP (gap_to_zero=11.2 bps latest arb, WETH/USDT frontier)
**Profit truth**: NOT YET — economics blocker: LP fees + slippage exceed captured spread at all sizes
**base anomaly**: ROUNDTRIP_PROFITABLE detected = FALSE POSITIVE (pancakeswap_v3 SUSPECT_SPREAD)

---

## Per-Chain Drift Summary (R23)

| Chain | Drift Rej % | Median bps | Excluded | Blocker Class | Health |
|-------|-------------|------------|----------|---------------|--------|
| mantle | 6.2% | 315 | 4 | STRUCTURAL | HEALTHY |
| linea | 11.5% | 326 | 6 | STRUCTURAL | OK |
| arbitrum_one | 14.3% | 408 | 6 | — | OK |
| base | 28.9% | 418 | 42 | MIXED | ELEVATED |
| zksync | 33.7% | 1472 | 54 | MIXED | ELEVATED |
| scroll | 35.2% | 2538 | 18 | ECOSYSTEM_BLOCKED | HIGH |

---

## Terminology Contract

| Metric | Source | Meaning |
|--------|--------|---------|
| `quotes_total` | `scan.json stats.quotes_total` | All quote requests attempted |
| `quotes_fetched` | `scan.json stats.quotes_fetched` | Quotes successfully received |
| `infra_gate` | `gate_result.json status` | Artifacts valid, schema OK, quotes_fetched > 0 |
| `run_summary.status` | `run_summary.json status` | Signal flow: NO_DATA/FAIL/PASS |
| `signals_count` | `run_summary.json metrics.signals_count` | Raw spread signals detected |
| `ChainQualityLevel` | `m4/policy.py` | INFRA_READY / SIGNAL_PRODUCING / QUALITY_RAISED |
| `cross_dex_pairs_count` | `gate_result.json` | Unique DEX pairs with buy_dex != sell_dex |

**IMPORTANT**: `infra_gate: PASS` != `run_summary.status: PASS`. Infra gate validates infrastructure; run_summary shows actual opportunity flow.

---

## Rolling Discipline

**PRIMARY_ROLLING_CHAIN**: `arbitrum_one`

| Rule | Behavior |
|------|----------|
| `--refresh-rolling` + non-primary chain | **FAIL** with error |
| Auto-enable `refresh_rolling` + non-primary | **BLOCKED** |

Rolling triplet: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json}`

---

## Canonical Commands

```powershell
# Offline gate (deterministic, no secrets)
py -3.11 scripts/ci_m5_0_gate.py --offline --strict

# Online gate (requires RPC)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1

# Online with rolling refresh
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3 --refresh-rolling --refresh-rolling-strict --prune-keep 50

# Unit tests
py -3.11 -m pytest tests/unit -q

# Full CI pipeline
py -3.11 scripts/ci_full_pipeline.py --mode ci
```

---

## Invariants Validated by Gate

| # | Invariant |
|---|-----------|
| 1 | `execution_enabled=false` (always in M5_0) |
| 2 | `current_block` consistent across artifacts |
| 3 | `chain_id` consistent across artifacts |
| 4 | `run_mode` consistent across artifacts |
| 5 | `quotes_total` consistent (scan == truth) |
| 6 | `schema_version` supported |
| 7 | No sentinel blocks (online only) |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL validation |
| 2 | FAIL missing artifacts |
| 3 | FAIL scanner error |

---

## Schema Versions

| Artifact | Version | Notes |
|----------|---------|-------|
| scan | `3.2.0` | M5 family |
| truth_report | `3.2.0` | M5 family |
| reject_histogram | `3.2.0` | reject samples (not aggregated counts) |
| long_scan_summary | `v1.4` | R21: per_chain_drift_summary, universe_split, notional_drift_bps in frontier |

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/ci_m5_0_gate.py` | M5_0 acceptance gate |
| `scripts/ci_full_pipeline.py` | Full CI pipeline |
| `core/artifact_invariants.py` | Cross-artifact validation |
| `start.py` | Multi-chain orchestrator |

---

## Relationship to M5/M4

| Milestone | Focus | Gate |
|-----------|-------|------|
| M5_0 | Infrastructure hardening | `ci_m5_0_gate.py` |
| M5 | Production features | `ci_m5_gate.py` |
| M4 | Execution layer | `ci_m4_execution_gate.py` |

---

## Next Steps (R24)

- M4.2: Track `best_roundtrip_net_bps` trend; gap_to_zero=11.2 bps (arb latest)
- Dashboard enhanced: Panels 1 ($/run, drift, blocker), 7 (cross-chain drift), 8 (rewritten blockers)
- Frontier (R23): zksync #1 (gap=0.0, drift=33.7%), arb_one #2 (gap=11.2, drift=14.3%), base #3 (gap=83.3)
- zksync: Pair-specific drift control — enforce max_per_pair_rejection_rate=0.40, quarantine worst pairs
- Base: Investigate pancakeswap_v3 SUSPECT_SPREAD + fee=101 bps (MIXED blocker)
- Mantle/Linea: Cross-dex enablement blocked by Algebra quoter incompatibility (drift HEALTHY: 6.2%, 11.5%)
- Scroll: ECOSYSTEM_BLOCKED — do not invest engineering time until second DEX venue appears
- drift_worst_pair: Fix "unknown" — propagate pair field through rejected quote path