# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-13
**Tests**: 1685 passed, 2 skipped
**Evidence runDirs**: ci_m5_gate_20260313_113747 (arb, rolling R20), ci_m5_gate_20260313_113853 (base R20), ci_m5_gate_20260313_113421 (mantle R20), ci_m5_gate_20260313_113506 (zksync R20), ci_m5_gate_20260313_113635 (scroll R20), ci_m5_gate_20260313_113707 (linea R20)
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}`
**Evidence long scan**: `data/runs/_rolling/long_scan_latest.json` (multi-chain frontier ranking)

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.

---

## Chain Quality Classification (current)

```
arbitrum_one:   SIGNAL_PRODUCING (primary, rolling, cross-dex=3, 2/2 PASS in R20 scan)
base:           SIGNAL_PRODUCING (cross-dex=15, SUSPECT_SPREAD on pancakeswap_v3 WETH/USDC, 2/2 PASS)
mantle:         SIGNAL_PRODUCING (same-dex agni_v3, LOW_SAMPLE, 1/1 PASS)
zksync:         SIGNAL_PRODUCING (cross-dex=10, 40.4% drift rejection, 1/1 PASS)
linea:          SIGNAL_PRODUCING (same-dex pancakeswap_v3, LOW_SAMPLE, 1/1 PASS)
scroll:         INFRA_READY (single DEX, probe-only, accepted-fail, 0/1 PASS)
```

**R20 scan result**: 5 PASS chains / 1 accepted-fail (scroll) / 8 total runs / 39 signals / $27.46 net
**Roundtrip evaluation**: CANONICAL SWEEP (gap_to_zero=10.44 bps latest, 4.10 bps best ever, WETH/USDT frontier, 184 runs in window)
**Profit truth**: NOT YET — economics blocker: LP fees + slippage exceed captured spread at all sizes
**base anomaly**: 1 ROUNDTRIP_PROFITABLE detected but is FALSE POSITIVE (pancakeswap_v3 PRICE_OUTLIER, 2488 bps spread)

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

## Next Steps

- M4.2: Track `best_roundtrip_net_bps` trend; gap_to_zero=4.10 bps (best), 13.44 bps (latest), 18.74 bps (median)
- Dashboard live at `py -3.11 -m monitoring.dashboard_server` (port 8099)
- Frontier: zksync #1 (gap=0.0), arb_one #2 (gap=13.44), base #3 (gap=59.38)
- Base: Reduce TOP_PAIR_DOMINANCE_HIGH via pair diversification
- Mantle/Linea/zkSync: Address SAME_DEX_PRESENT and LOW_SAMPLE warnings
- Scroll: Keep probe-only/accepted-fail until second DEX venue appears