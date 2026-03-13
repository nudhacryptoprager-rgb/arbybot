# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-13 (R25)
**Tests**: 1735 passed, 2 skipped (+10 from R24)
**Schema**: start:long_scan_summary (latest)
**Evidence runDirs**: ci_m5_gate_20260313_213616 (arb rolling R25), 16 total runs across 6 chains
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}`
**Evidence long scan**: `data/runs/_rolling/long_scan_latest.json` (multi-chain frontier ranking with discovery_coverage, generated 2026-03-13T20:40:48Z)

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> R25: `discovery_coverage` now populated from scan_*.json stats; `_warn_missing_chains()` is FATAL.

---

## Chain Quality Classification (R25)

```
arbitrum_one:   SIGNAL_PRODUCING (primary, rolling, truth_probe, cross-dex=3, 3/3 PASS, blocker=NONE)
base:           SIGNAL_PRODUCING (discovery, cross-dex=10, 3/3 PASS, blocker=MIXED)
mantle:         SIGNAL_PRODUCING (discovery, same-dex agni_v3, 3/3 PASS, blocker=STRUCTURAL)
zksync:         SIGNAL_PRODUCING (discovery, cross-dex=3, 3/3 PASS, blocker=MIXED)
linea:          SIGNAL_PRODUCING (discovery, same-dex pancakeswap_v3, 2/2 PASS, blocker=STRUCTURAL)
scroll:         INFRA_READY (monitoring_only=true, single DEX, accepted-fail=true, 0/2 PASS, blocker=ECOSYSTEM_BLOCKED)
```

**Universe Split (R25)**:
- **truth_probe**: arbitrum_one (config-based, target_for_truth_probe=true)
- **discovery**: base, linea, mantle, zksync (discovery_coverage now populated)
- **monitoring_only**: scroll (PROBE_ONLY, accepted-fail=true)

**R25 scan result**: 5 PASS chains / 1 accepted-fail (scroll) / 16 total runs / 45 signals / $42.43 net
**Roundtrip evaluation**: CANONICAL SWEEP (gap_to_zero in frontier_ranking)
**Profit truth**: NOT YET — economics blocker: LP fees + slippage exceed captured spread at all sizes
**discovery_coverage**: FIXED (populated for zksync, base, mantle, linea from scan_*.json stats)

---

## Per-Chain Discovery Coverage (R25)

| Chain | Pairs Evaluated | Pairs Resolved | Cross-DEX | Skipped Excluded |
|-------|-----------------|----------------|-----------|------------------|
| zksync | 15 | 4 | 3 | 11 |
| base | 18 | 10 | 10 | 6 |
| mantle | 14 | 10 | 0 | 3 |
| linea | 17 | 12 | 0 | 0 |
| arbitrum_one | n/a | n/a | n/a | n/a (config) |
| scroll | blocked | blocked | blocked | blocked |

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
| long_scan_summary | `latest` | R25: discovery_coverage populated from scan_*.json stats |

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

## Next Steps (R25)

- M4.2: Track `best_roundtrip_net_bps` trend in frontier_ranking
- discovery_coverage: Now populated from scan_*.json stats (FIXED in R25)
- _warn_missing_chains: Now FATAL (hard fail) instead of WARNING
- monitoring_only_chains: scroll properly marked (FIXED in R25)
- Schema: LATEST (bumped from previous)
- Scroll: ECOSYSTEM_BLOCKED — do not invest engineering time
- Test delta: +10 tests (1725 → 1735)