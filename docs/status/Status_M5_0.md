# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-14 (R27)
**Tests**: 1788 collected / 1786 passed / 2 skipped (pending verification)
**Schema**: start:long_scan_summary (latest, R26 bump)
**Evidence runDirs**: ci_m5_gate_20260313_221453 (arb rolling R26), ci_m5_gate_20260313_223350 (arb rolling latest), 21 total runs across 6 chains
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}`
**Evidence long scan**: `data/runs/_rolling/long_scan_latest.json` (multi-chain frontier ranking with run_context provenance + triage fields, generated 2026-03-13T21:37:23Z)
**Strategy**: Full universe preserved, staged chain onboarding via configs/adapters (R27)

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> R27: Strategy shift — full universe preserved, staged chain onboarding via `onboard_<chain>_stageN.yaml` configs. Scroll nuri_v3 contract mismatch fixed (was incorrectly classified as algebra, actually uniswap_v3/quoter_v2). Coverage matrix: `docs/ONBOARDING_MATRIX.md`.
> R26: `run_context.run_timestamp` added to long_scan; frontier_ranking enriched with triage fields (status, route_health, blocker_reasons).
> R25: `discovery_coverage` now populated from scan_*.json stats; `_warn_missing_chains()` is FATAL.

---

## Chain Quality Classification (R27)

```
arbitrum_one:   SIGNAL_PRODUCING (primary, rolling, truth_probe, cross-dex=3, 4/4 PASS, blocker=NONE)
base:           SIGNAL_PRODUCING (discovery, cross-dex=10, 4/4 PASS, blocker=MIXED, rt_profitable=2 — COVERAGE evidence only, NOT promotion evidence)
mantle:         SIGNAL_PRODUCING (discovery, same-dex agni_v3, 3/3 PASS, blocker=STRUCTURAL — ve33 adapter not implemented)
zksync:         SIGNAL_PRODUCING (discovery, cross-dex=3, 4/4 PASS, blocker=MIXED, gap=0.0 bps — drift=0.3077, needs <0.25)
linea:          SIGNAL_PRODUCING (discovery, same-dex pancakeswap_v3, 3/3 PASS, blocker=STRUCTURAL — lynex_v3 algebra path unstable)
scroll:         INFRA_READY (monitoring_only=true, nuri_v3 re-enabled R27, accepted-fail=true, 0/3 PASS, blocker=ECOSYSTEM_BLOCKED)
```

**Rollout Queue (R27 — additive model, per lead directive)**:
1. **arbitrum_one** (primary, NORMAL) — must pass exit gate before others promoted
2. **zksync** — drift_rejection_rate_median must drop below 0.25
3. **base** — ve33 adapter (aerodrome) needed for full coverage, mixed-source cleanup
4. **mantle** — COVERAGE only until ve33 adapter (stratum) implemented
5. **linea** — COVERAGE only until lynex_v3 Algebra path stabilized
6. **scroll** — monitoring_only (nuri_v3 contract aligned R27, online verification pending)

**Onboard Stage Configs (R27)**:
- `config/onboard_arbitrum_one_candidate.yaml` — 4-DEX additive (uni+sushi+camelot+pancakeswap)
- `config/onboard_zksync_candidate.yaml` — 2-DEX candidate (uni+pancakeswap)
- `config/onboard_base_stage1.yaml` — 3-DEX stage1 (uni+sushi+pancakeswap, aerodrome excluded)
- `config/onboard_mantle_stage1.yaml` — 1-DEX stage1 (agni_v3 only, stratum excluded)
- `config/onboard_linea_stage1.yaml` — 2-DEX stage1 (pancakeswap+lynex, algebra stability test)
- `config/onboard_scroll_stage1.yaml` — 2-DEX stage1 (sushi+nuri, cross-DEX test)

**Universe Split (R27)**:
- **truth_probe**: arbitrum_one (config-based, target_for_truth_probe=true)
- **discovery**: base, linea, mantle, zksync (discovery_coverage populated)
- **monitoring_only**: scroll (nuri_v3 re-enabled R27, accepted-fail=true)

**R27 key changes**:
- Strategy: full universe preserved, staged onboarding via `onboard_<chain>_stageN.yaml` configs
- Scroll nuri_v3 contract mismatch FIXED (dexes.yaml=uniswap_v3/quoter_v2, was excluded as algebra)
- Coverage matrix: `docs/ONBOARDING_MATRIX.md` — chain/dex/adapter/quoter/blocker
- Adapter readiness tests: +48 tests (per-chain adapter/factory/quoter validation)
- ve33 gap explicitly documented (base/aerodrome, mantle/stratum)
- `base roundtrip_profitable=2` is COVERAGE evidence, NOT promotion evidence

**R26 scan result**: 5 PASS chains / 1 accepted-fail (scroll) / 21 total runs / 68 signals / $56.40 net / 2 roundtrip_profitable (base, COVERAGE only)
**Profit truth**: NOT YET — Arbitrum profit-truth blocker remains (roundtrip.profitable_count=0)

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

## Next Steps (R27)

- **Adapter gaps**: implement `ve33` adapter for aerodrome (Base) and stratum (Mantle)
- **Arbitrum exit gate**: 5 consecutive online runs with signals>=4, cross_dex>=3, drift_rate<=0.20
- **Arbitrum additive**: test `onboard_arbitrum_one_candidate.yaml` (4-DEX with camelot_v3)
- **zksync promotion**: reduce drift_rejection_rate_median below 0.25
- **Scroll verification**: run `onboard_scroll_stage1.yaml` online to verify nuri_v3 quoter_v2
- **Linea stability**: run `onboard_linea_stage1.yaml` to stabilize lynex_v3 Algebra path
- **Coverage matrix**: `docs/ONBOARDING_MATRIX.md` — single source of truth for adapter readiness
- Scroll: ECOSYSTEM_BLOCKED until nuri_v3 verified + ecosystem matures
- Test delta: +48 adapter readiness tests (R27)