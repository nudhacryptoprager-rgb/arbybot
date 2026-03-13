# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-13 (R26)
**Tests**: 1740 collected / 1738 passed / 2 skipped
**Schema**: start:long_scan_summary (latest, R26 bump)
**Evidence runDirs**: ci_m5_gate_20260313_221453 (arb rolling R26), ci_m5_gate_20260313_223350 (arb rolling latest), 21 total runs across 6 chains
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}`
**Evidence long scan**: `data/runs/_rolling/long_scan_latest.json` (multi-chain frontier ranking with run_context provenance + triage fields, generated 2026-03-13T21:37:23Z)

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> R26: `run_context.run_timestamp` added to long_scan; frontier_ranking enriched with triage fields (status, route_health, blocker_reasons).
> R25: `discovery_coverage` now populated from scan_*.json stats; `_warn_missing_chains()` is FATAL.

---

## Chain Quality Classification (R26)

```
arbitrum_one:   SIGNAL_PRODUCING (primary, rolling, truth_probe, cross-dex=3, 4/4 PASS, blocker=NONE)
base:           SIGNAL_PRODUCING (discovery, cross-dex=10, 4/4 PASS, blocker=MIXED, rt_profitable=2)
mantle:         SIGNAL_PRODUCING (discovery, same-dex agni_v3, 3/3 PASS, blocker=STRUCTURAL)
zksync:         SIGNAL_PRODUCING (discovery, cross-dex=3, 4/4 PASS, blocker=MIXED, gap=0.0 bps)
linea:          SIGNAL_PRODUCING (discovery, same-dex pancakeswap_v3, 3/3 PASS, blocker=STRUCTURAL)
scroll:         INFRA_READY (monitoring_only=true, single DEX, accepted-fail=true, 0/3 PASS, blocker=ECOSYSTEM_BLOCKED)
```

**Rollout Queue (R26 — per lead directive)**:
1. **arbitrum_one** (primary, NORMAL) — must pass exit gate before others promoted
2. **zksync** — drift_rejection_rate_median must drop below 0.25
3. **base** — quality/mixed-source noise cleanup, economics gap=67 bps
4. **mantle/linea** — COVERAGE only (no cross-DEX surface)
5. **scroll** — monitoring_only (ECOSYSTEM_BLOCKED)

**Universe Split (R26)**:
- **truth_probe**: arbitrum_one (config-based, target_for_truth_probe=true)
- **discovery**: base, linea, mantle, zksync (discovery_coverage now populated)
- **monitoring_only**: scroll (PROBE_ONLY, accepted-fail=true)

**R26 scan result**: 5 PASS chains / 1 accepted-fail (scroll) / 21 total runs / 68 signals / $56.40 net / 2 roundtrip_profitable (base)
**Roundtrip evaluation**: CANONICAL SWEEP (gap_to_zero in frontier_ranking) + triage fields for promotion decisions
**Profit truth**: NOT YET — Arbitrum profit-truth blocker remains (roundtrip.profitable_count=0)
**Provenance**: `run_context.run_timestamp` now in long_scan_latest.json (R26 fix)
**discovery_coverage**: populated (R25 fix preserved)

---

## Per-Chain Discovery Coverage (R26)

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
| long_scan_summary | `LATEST` | R26: run_context provenance + frontier triage fields |

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

## Next Steps (R26)

- **Arbitrum exit gate**: 5 consecutive online runs with signals>=4, cross_dex>=3, drift_rate<=0.20
- **zksync promotion**: reduce drift_rejection_rate_median below 0.25 via pair quarantine
- **base economics**: reduce gap_to_zero_bps from 67 bps (quality/mixed-source cleanup first)
- **Provenance**: long_scan_latest now has run_context.run_timestamp (R26 fix)
- **Frontier triage**: status, route_health, blocker_reasons now in frontier_ranking (R26 fix)
- Scroll: ECOSYSTEM_BLOCKED — do not invest engineering time
- Test delta: +5 tests (1733 → 1738 passed)