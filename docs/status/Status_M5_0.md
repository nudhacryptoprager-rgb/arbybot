# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-13 (R21)
**Tests**: 1699 passed, 2 skipped
**Schema**: start:long_scan_summary:v1.4
**Evidence runDirs**: ci_m5_gate_20260313_125401 (arb rolling R21), ci_m5_gate_20260313_124714 (base R21), ci_m5_gate_20260313_124927 (mantle R21), ci_m5_gate_20260313_125124 (zksync R21), ci_m5_gate_20260313_125250 (scroll R21), ci_m5_gate_20260313_125321 (linea R21)
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}`
**Evidence long scan**: `data/runs/_rolling/long_scan_latest.json` (multi-chain frontier ranking with drift metrics)

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> R21: operational_truth_source = "measured_economics" (sole truth for profit claims).

---

## Chain Quality Classification (R21)

```
arbitrum_one:   SIGNAL_PRODUCING (primary, rolling, truth_probe, cross-dex=3, 3/3 PASS)
base:           SIGNAL_PRODUCING (discovery, cross-dex=15, SUSPECT_SPREAD on pancakeswap_v3, 2/2 PASS)
mantle:         SIGNAL_PRODUCING (discovery, same-dex agni_v3, LOW_SAMPLE, 2/2 PASS)
zksync:         SIGNAL_PRODUCING (discovery, cross-dex=10, 34.9% drift rejection, 2/2 PASS)
linea:          SIGNAL_PRODUCING (discovery, same-dex pancakeswap_v3, LOW_SAMPLE, 2/2 PASS)
scroll:         INFRA_READY (monitoring_only, single DEX, probe-only, accepted-fail, 0/2 PASS)
```

**Universe Split (R21)**:
- **truth_probe**: arbitrum_one (frontier_ready, target_for_truth_probe=true)
- **discovery**: base, linea, mantle, zksync (cross-dex work, not frontier_ready)
- **monitoring_only**: scroll (PROBE_ONLY, accepted-fail)

**R21 scan result**: 5 PASS chains / 1 accepted-fail (scroll) / 13 total runs / 38 signals / $38.45 net
**Roundtrip evaluation**: CANONICAL SWEEP (gap_to_zero=23.23 bps latest, WETH/USDT frontier, 187+ runs in window)
**Profit truth**: NOT YET — economics blocker: LP fees + slippage exceed captured spread at all sizes
**base anomaly**: 2 ROUNDTRIP_PROFITABLE detected but is FALSE POSITIVE (pancakeswap_v3 SUSPECT_SPREAD, 2549 bps spread)

---

## Per-Chain Drift Summary (R21 — new)

| Chain | Drift Rej Rate | Drift Median bps | Excluded | Pairs w/Data |
|-------|----------------|------------------|----------|--------------|
| arbitrum_one | 16.7% | 315 | 6 | 9 |
| base | 30.3% | 338 | 33 | 10 |
| mantle | 6.3% | 315 | 4 | 6 |
| zksync | 34.9% | 1472 | 36 | 8 |
| linea | 11.5% | 307 | 4 | 10 |
| scroll | 35.2% | 2576 | 10 | 2 |

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

## Next Steps (R21)

- M4.2: Track `best_roundtrip_net_bps` trend; gap_to_zero=23.23 bps (latest), median=23.27 bps
- Dashboard live at `py -3.11 -m monitoring.dashboard_server` (port 8099)
- Frontier (R21): zksync #1 (gap=0.0, drift=1472 bps), arb_one #2 (gap=23.23, drift=315 bps), base #3 (gap=89.06)
- zksync: Reduce 34.9% drift rejection rate (notional_drift_median=1472 bps)
- Base: Investigate pancakeswap_v3 SUSPECT_SPREAD (fee=101 bps cost prohibitive)
- Mantle/Linea: Cross-dex enablement blocked by Algebra quoter incompatibility (drift healthy: 6.3%, 11.5%)
- Scroll: Keep monitoring_only until second DEX venue appears