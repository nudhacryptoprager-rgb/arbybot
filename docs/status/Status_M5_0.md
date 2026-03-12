# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-11
**Tests**: 1653 passed, 2 skipped
**Evidence runDirs**: ci_m5_gate_20260311_111734 (arb, rolling), ci_m5_gate_20260311_111132 (base), ci_m5_gate_20260311_111334 (mantle), ci_m5_gate_20260311_111502 (zksync), ci_m5_gate_20260311_111621 (scroll), ci_m5_gate_20260311_111654 (linea)
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
arbitrum_one:   SIGNAL_PRODUCING (primary, rolling, cross-dex=3, 20/20 PASS in 2h scan)
base:           SIGNAL_PRODUCING (cross-dex=15, TOP_PAIR_DOMINANCE_HIGH, 19/19 PASS)
mantle:         SIGNAL_PRODUCING (same-dex, LOW_SAMPLE, SAME_DEX_PRESENT, 19/19 PASS)
zksync:         SIGNAL_PRODUCING (cross-dex=10, LOW_SAMPLE, SAME_DEX_PRESENT, 19/19 PASS)
linea:          SIGNAL_PRODUCING (same-dex, LOW_SAMPLE, SAME_DEX_PRESENT, 19/19 PASS)
scroll:         INFRA_READY (single DEX, probe-only, accepted-fail, 0/19 PASS)
```

**2h scan result**: 5 PASS / 1 NO_DATA (scroll, accepted-fail) / 0 INFRA_FAIL (R14 fresh 6-chain scan)
**Roundtrip evaluation**: CANONICAL SWEEP (gap_to_zero=9.03 bps latest, 4.10 bps best ever, WBTC/USDC frontier, 170 runs in window)
**Profit truth**: NOT YET — economics blocker: LP fees + slippage exceed captured spread at all sizes

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

- M4.2: Track `best_roundtrip_net_bps` trend; gap_to_zero=4.10 bps (best), 9.03 bps (latest), 16.26 bps (median)
- New 2h long scan to collect fresh multi-chain `roundtrip_evaluated_total` and per-chain frontier updates
- Base: Reduce TOP_PAIR_DOMINANCE_HIGH via pair diversification
- Mantle/Linea/zkSync: Address SAME_DEX_PRESENT and LOW_SAMPLE warnings
- Scroll: Keep probe-only/accepted-fail until second DEX venue appears