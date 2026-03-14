# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-14 (R27.4)
**Tests**: 1806 collected / 1803 passed / 3 skipped
**Schema**: start:long_scan_summary (latest, R26 bump)
**Evidence runDirs**: ci_m5_gate_20260314_211452 (R27.4 arb primary NORMAL, fresh), ci_m5_gate_20260314_192514 (R27.2 arb primary), ci_m5_gate_20260314_192713 (R27.2 arb 4-DEX candidate), ci_m5_gate_20260314_193000 (R27.2 scroll stage1), ci_m5_gate_20260314_193819 (R27.2 long_scan)
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}`
**Evidence long scan**: `data/runs/_rolling/long_scan_latest.json` (REFRESHED 2026-03-14T18:40:26Z: 8 runs, 17 signals, $23.49)
**Strategy**: Full universe preserved, staged chain onboarding via configs/adapters (R27). Config inventory frozen to 16 active files (R27.4).

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> R27.4: Config layer audit — 15 stale YAMLs deleted, inventory frozen to 16 active files with TestConfigInventoryGuard. validate_universe.py regression FIXED (is_strict_run used before defined). ve33 adapter IMPLEMENTED (dex/adapters/ve33.py + registry). Fresh online evidence: ci_m5_gate_20260314_211452 (4 signals, $5.55).
> R27.3: Scanner pipeline contract hardening — removed synthetic suspect metrics, strict discovery_runtime, intent forbidden for NORMAL, unified economics, pre-scan validation wired. +7 tests.
> R27.2: Rolling contamination FIXED — NORM-only guard in m4/gates.py prevents COVERAGE/SMOKE runs from overwriting pointer files. check_repo_safety detects contamination (check [20]). +7 regression tests. Fresh online evidence: arb primary + 4-DEX candidate + scroll stage1 + long scan (6 chains, 8 runs, $23.49).
> R27.1: Online proof — arb 4-DEX candidate PASS (14 signals, $14.61, dexes_active=4), scroll stage1 PASS (3 signals, $0.14, nuri_v3 quoter_v2 confirmed).
> R27: Strategy shift — full universe preserved, staged chain onboarding via `onboard_<chain>_stageN.yaml` configs. Scroll nuri_v3 contract mismatch fixed (was incorrectly classified as algebra, actually uniswap_v3/quoter_v2). Coverage matrix: `docs/ONBOARDING_MATRIX.md`.
> R26: `run_context.run_timestamp` added to long_scan; frontier_ranking enriched with triage fields (status, route_health, blocker_reasons).
> R25: `discovery_coverage` now populated from scan_*.json stats; `_warn_missing_chains()` is FATAL.

---

## Chain Quality Classification (R27.2)

```
arbitrum_one:   SIGNAL_PRODUCING (primary, rolling, truth_probe, cross-dex=3, PASS, blocker=NONE, gap=15.77 bps, drift=0.17)
base:           SIGNAL_PRODUCING (discovery, cross-dex=15, PASS, blocker=MIXED, rt_profitable=2 — COVERAGE evidence only)
mantle:         SIGNAL_PRODUCING (discovery, same-dex agni_v3, PASS, blocker=STRUCTURAL — ve33 adapter not implemented)
zksync:         SIGNAL_PRODUCING (discovery, cross-dex=10, PASS, blocker=MIXED, drift=0.27 — needs <0.25)
linea:          SIGNAL_PRODUCING (discovery, cross-dex=12, PASS, blocker=STRUCTURAL — lynex_v3 algebra path unstable)
scroll:         CROSS_DEX_VERIFIED (monitoring_only=true, nuri_v3 confirmed R27.1+R27.2, accepted-fail=true, blocker=THIN_LIQUIDITY)
```

**Rollout Queue (R27.2 — additive model, with fresh long_scan + online proof)**:
1. **arbitrum_one** (primary, NORMAL) — 4-DEX candidate PASS (R27.2: 14 sims). Gap=15.77 bps. Exit gate: 5 consecutive.
2. **zksync** — drift_rejection_rate_median=0.27 (above 0.25 threshold), needs improvement
3. **base** — ve33 adapter (aerodrome) needed for full coverage, 4 signals in long_scan
4. **mantle** — COVERAGE only until ve33 adapter (stratum) implemented, 1 signal in long_scan
5. **linea** — COVERAGE only until lynex_v3 Algebra path stabilized, 2 signals in long_scan, rank #2
6. **scroll** — nuri_v3 confirmed (R27.1+R27.2), 0 signals in long_scan (accepted-fail), needs sustained evidence

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

**R27.2 online verification**:
- arb primary: ci_m5_gate_20260314_192514, PASS, 4 signals, $5.62 (NORMAL, rolling refreshed)
- arb candidate: ci_m5_gate_20260314_192713, PASS, 87 quotes, cross_dex=27, 14 simulations (4-DEX)
- scroll stage1: ci_m5_gate_20260314_193000, PASS, 3 signals, nuri_v3 confirmed (rolling NOT overwritten — NORM-only guard)
- long scan: ci_m5_gate_20260314_193819 (arb final), 6 chains, 8 runs, 17 signals, $23.49

**R27.2 code changes**:
- `m4/gates.py`: NORM-only rolling pointer policy — non-NORMAL runs skip writing pointer files
- `check_repo_safety.py`: check [20] rolling chain purity (validates run_kind=NORMAL + chain_key=arbitrum_one)
- `test_rolling_chain_keys.py`: +7 regression tests (4 pointer protection + 3 chain purity)
- ONBOARDING_MATRIX: camelot_v3+nuri_v3 "pending"→"verified" with runDir evidence
- onboard_scroll_stage1.yaml: PURPOSE softened, nuri_v3 VERIFIED

**R27.1 online verification**:
- arb candidate: ci_m5_gate_20260314_101735, PASS, 14 signals, $14.61, dexes_active=4, cross_dex=27
- scroll stage1: ci_m5_gate_20260314_102036, PASS, 3 signals, $0.14, dexes_active=2, cross_dex=8
- nuri_v3 quoter_v2 CONFIRMED: 3 cross-DEX signals on scroll (1 PASS ≠ exit from ECOSYSTEM_BLOCKED)

**R27 key changes**:
- Strategy: full universe preserved, staged onboarding via `onboard_<chain>_stageN.yaml` configs
- Scroll nuri_v3 contract mismatch FIXED (dexes.yaml=uniswap_v3/quoter_v2, was excluded as algebra)
- Coverage matrix: `docs/ONBOARDING_MATRIX.md` — chain/dex/adapter/quoter/blocker
- Adapter readiness tests: +48 tests (per-chain adapter/factory/quoter validation)
- ve33 gap explicitly documented (base/aerodrome, mantle/stratum)
- `base roundtrip_profitable=2` is COVERAGE evidence, NOT promotion evidence

**R27.4 config audit**:
- validate_universe.py: FIXED — is_strict_run/run_kind moved above intent check block (R27.3 regression)
- 15 stale YAMLs deleted: coverage_intent_* (6), real_debug, real_expanded, real_hunting, real_hunting_lowfee, real_nonstop, real_test_coverage, real_minimal_discovery_runtime, real_minimal_intent_forced, real_scan_linea_smoke
- real_m5_0_golden.yaml: MOVED to docs/artifacts/golden/ (golden fixture, not a scanner config)
- Active inventory frozen: 6 registry + 4 primary/probes + 6 onboard = 16 files
- TestConfigInventoryGuard: ALLOWED_YAML_FILES (16 entries) + 2 tests (no unexpected + all exist)
- ve33 adapter: dex/adapters/ve33.py (Ve33Adapter class), registered in dex/registry.py
- All 10 scanner configs pass validate_universe
- Online verification: ci_m5_gate_20260314_211452, PASS, 17 quotes, 4 signals, 3 cross-dex
- Tests: 1803 passed, 3 skipped (-2 net: removed hunting tests, added inventory/adapter tests)

**R27.3 code changes**:
- `strategy/jobs/run_scan_real.py`: removed _compute_sanity_rejects() (synthetic suspect fabrication), replaced with _extract_suspect_from_rejects() (real data only); discovery_runtime strict-by-default; intent/intent_forced forbidden for NORMAL/COVERAGE; strategy_mode/same_dex_only encoded in stats; pre-scan validate_universe wired; paper_slippage_bps passed to opportunity_engine
- `engine/opportunity_engine.py`: paper_slippage_bps parameter (was hardcoded 5.0)
- `scripts/validate_universe.py`: intent forbidden for strict run_kinds, same_dex_mode warning
- `tests/unit/test_suspect_provenance.py`: +7 tests (extract/purity validation)

**Long scan (REFRESHED 2026-03-14)**: 5 PASS chains + 1 accepted-fail / 8 runs / 17 signals / $23.49 net / 2 profitable roundtrips
**Profit truth**: NOT YET — Arbitrum profit-truth blocker remains (roundtrip.profitable_count=0 on primary chain, gap=20.41 bps R27.4)

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
| Non-NORMAL run_kind (COVERAGE/SMOKE) | **SKIP** pointer file writes (R27.2 NORM-only guard, m4/gates.py) |
| check_repo_safety check [20] | **FAIL** if run_kind!=NORMAL or chain_key!=arbitrum_one in pointer files |

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

## Next Steps (R27.2)

- **Adapter gaps**: implement `ve33` adapter for aerodrome (Base) and stratum (Mantle)
- **Arbitrum exit gate**: 5 consecutive online runs with signals>=4, cross_dex>=3, drift_rate<=0.20
- **Arbitrum frontier**: gap regressed from 8.41→15.77 bps — monitor for market recovery
- **zksync promotion**: drift_rejection_rate_median=0.27 (above 0.25) — pair tuning may help
- **Scroll sustained evidence**: 0 signals in long_scan vs 3 in stage1 — needs more runs
- **Linea stability**: run `onboard_linea_stage1.yaml` to stabilize lynex_v3 Algebra path
- **Coverage matrix**: `docs/ONBOARDING_MATRIX.md` — single source of truth for adapter readiness
- Scroll: ECOSYSTEM_BLOCKED until sustained evidence (not just single-run proof)
- Test delta: +7 R27.2 rolling protection tests (1791 → 1798)