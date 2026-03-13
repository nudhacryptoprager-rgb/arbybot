# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-13, Session 4 Round 25)
**Goal**: R25 AUDIT - Fix `discovery_coverage=None` in frontier_ranking, fix scroll `accepted_fail` mismatch, convert `_warn_missing_chains` to hard fail, 17-min 6-chain verification scan.

## 0) Meta
timestamp_utc: 2026-03-13T20:37:04Z
rolling_provenance: 2026-03-13T20:40:48Z (6-chain, 16 runs)
mode: ONLINE
test_count: 1735 passed, 2 skipped (+10 from R24)
schema_version: start:long_scan_summary:v1.6

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R25: fix discovery_coverage source, scroll accepted_fail, _warn_missing_chains hard fail |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb; scroll ECOSYSTEM_BLOCKED (single DEX) |
| evidence_session_run_dirs | 16 runs across 6 chains (17-min scan), last=ci_m5_gate_20260313_213616 |
| primary_blocker_of_session | `discovery_coverage=None` in frontier_ranking; scroll marked as monitoring_only but artifacts showed `accepted_fail=false` |
| blocker_status_before | R24: discovery_coverage always None (read from run_summary, not scan stats); scroll mismatch |
| blocker_status_after | RESOLVED. discovery_coverage now reads from scan_stats.discovery_runtime. scroll in `monitoring_only_chains=['scroll']`. _warn_missing_chains now hard fail. |
| start_metric | R24: 1725 tests, v1.5 schema, discovery_coverage=None, monitoring_only_chains=[] |
| end_metric | R25: 1735 tests, v1.6 schema, discovery_coverage populated (4 chains), monitoring_only_chains=['scroll'] |
| delta | +10 tests, 2 files modified, schema v1.5->v1.6, discovery_coverage fixed, scroll mismatch fixed, hard-fail chain validation |
| docs_reread_confirmed | true |

## 1) Changes This Session (R25)

1. **`discovery_coverage` source fix** (start.py): Changed `update_chain_stats()` to read `discovery_runtime` from `scan_stats` (scan_*.json) instead of `summary` (run_summary_*.json). Added `extract_scan_stats()` function. Added `scan_stats` parameter to `update_chain_stats()`. Now correctly populates for chains using `discovery_runtime` universe.

2. **`_warn_missing_chains` hard fail** (start.py): Converted from WARNING to FATAL + sys.exit(1) when chains.yaml defines chains not covered by config-list. Prevents silent coverage gaps.

3. **scroll `accepted_fail` alignment**: Documentation now correctly reflects that scroll must be passed via `--accepted-fail-chains scroll` to appear in `monitoring_only_chains`. Fixed mismatch between Status_M5_0.md claims and artifacts.

4. **Schema bump** (start.py): `start:long_scan_summary:v1.5` → `v1.6`. Discovery_coverage filter: only set when `pairs_evaluated > 0` (excludes config-based chains like arb).

5. **Unit tests**: +10 tests across 3 test classes:
   - `TestExtractScanStats` (3 tests): scan_*.json reading
   - `TestDiscoveryCoverageFromScanStats` (3 tests): discovery_coverage population
   - `TestWarnMissingChainsHardFail` (2 tests): hard fail on missing chains
   - All existing tests updated with `@patch("start.extract_scan_stats")` and `@patch("start._warn_missing_chains")` mocks

## 2) Evidence Artifacts (R25 - 17-min 6-chain scan)

### Rolling State (R25 - 16-run 6-chain scan, 1018s wall time)

| Artifact | Key Metric | Value |
|----------|-----------|-------|
| long_scan_latest | schema | start:long_scan_summary:v1.6 |
| long_scan_latest | generated_at | 2026-03-13T20:40:48Z |
| long_scan_latest | total_runs | 16 (PASS=14, FAIL=2) |
| long_scan_latest | total_included_signals | 45 |
| long_scan_latest | total_net_usdc | `$`42.43 |
| long_scan_latest | pass_chains | arbitrum_one, base, zksync, mantle, linea |
| long_scan_latest | monitoring_only_chains | **scroll** (R25 fix) |
| run_summary | run_id | ci_m5_gate_20260313_213616 (latest) |
| run_summary | chain_key | arbitrum_one |
| run_summary | timestamp | 2026-03-13T20:37:04Z |
| run_summary | status | PASS |

### Discovery Coverage (R25 - NEW)

| Chain | Evaluated | Resolved | Cross-DEX | Skipped Excluded |
|-------|-----------|----------|-----------|------------------|
| zksync | 15 | 4 | 3 | **11** |
| base | 18 | 10 | 10 | **6** |
| mantle | 14 | 10 | 0 | **3** |
| linea | 17 | 12 | 0 | 0 |
| arbitrum_one | n/a (config) | n/a | n/a | n/a |
| scroll | blocked | blocked | blocked | blocked |

### Multi-Chain Results (R25 - 16 runs, 17 min)

| Chain | Runs | Pass | Fail | Signals | Status |
|-------|------|------|------|---------|--------|
| arbitrum_one | 3 | 3 | 0 | 13 | 100% PASS |
| base | 3 | 3 | 0 | 11 | 100% PASS |
| zksync | 3 | 3 | 0 | 6 | 100% PASS |
| mantle | 3 | 3 | 0 | 5 | 100% PASS |
| linea | 2 | 2 | 0 | 10 | 100% PASS |
| scroll | 2 | 0 | 2 | 0 | ECOSYSTEM_BLOCKED |

### Frontier Ranking (R25)

| # | Chain | Gap bps | Signals | xDex | Discovery Coverage | Status |
|---|-------|---------|---------|------|-------------------|--------|
| 1 | zksync | 0.0 | 6 | 3 | ✓ (15 eval, 11 excl) | frontier_ready |
| 2 | arbitrum_one | n/a | 13 | 3 | n/a (config) | truth_probe |
| 3 | base | n/a | 11 | 10 | ✓ (18 eval, 6 excl) | discovery |
| 4 | mantle | n/a | 5 | 0 | ✓ (14 eval, 3 excl) | discovery |
| 5 | linea | n/a | 10 | 0 | ✓ (17 eval, 0 excl) | discovery |
| 6 | scroll | - | 0 | 0 | blocked | monitoring_only |

### Verification Gates (R25)

| Gate | Result |
|------|--------|
| pytest | 1735 passed, 2 skipped (+10 tests from R24) |
| 17-min online scan | 16 runs (14 PASS, 2 AF scroll) |
| discovery_coverage | **FIXED** (populated for 4 chains) |
| monitoring_only_chains | **FIXED** (['scroll']) |

## 3) Key Results

`theoretical_net_profit`:
- mode: paper_simulated
- gross_pnl_usdc: 42.43 (16 runs, 6 chains, 17 min)
- rate_per_hour: ~149.50 (extrapolated)
- discovery_coverage_verified: populated for 4 discovery chains
- monitoring_only_verified: scroll properly marked
- disclaimer: Theoretical profit based on simulated execution. No real trades.

## 4) Honest Assessment

**R25 Fixes Verified**:
- `discovery_coverage` fix: `extract_scan_stats()` reads from `scan_*.json stats` instead of `run_summary`
- `_warn_missing_chains()` hardened: now FATAL + sys.exit(1) instead of WARNING
- `monitoring_only_chains` fix: scroll properly marked as accepted-fail (pass `--accepted-fail-chains scroll`)
- Schema bump: v1.5 → v1.6

**5/6 chains 100% PASS rate (R25 verification scan)**:
- arbitrum_one: 3/3 PASS, 13 signals, primary chain (config-based)
- base: 3/3 PASS, 11 signals, 10 xdex, 18 pairs evaluated
- zksync: 3/3 PASS, 6 signals, breakeven frontier (gap=0.0 bps)
- mantle: 3/3 PASS, 5 signals, single DEX (STRUCTURAL)
- linea: 2/2 PASS, 10 signals, single DEX (STRUCTURAL)
- scroll: 0/2 PASS, ECOSYSTEM_BLOCKED (monitoring_only=true)

**Per-Chain Blocker Classification**:

| Chain | Classification | Reason | Actionable |
|-------|---------------|--------|------------|
| arbitrum_one | - (primary) | 13 signals, config-based | Fee=100 pool discovery |
| base | MIXED | 11 signals, 10 xdex, 18 pairs evaluated | Fee tier investigation |
| zksync | FRONTIER | 6 signals, 3 xdex, gap=0.0 bps | Pair-specific validation |
| mantle | STRUCTURAL | 5 signals, single DEX (agni_v3) | Wait for 2nd DEX |
| linea | STRUCTURAL | 10 signals, single DEX (pancakeswap_v3) | Wait for 2nd DEX |
| scroll | ECOSYSTEM_BLOCKED | no viable venue, accepted_fail=true | Do not invest engineering time |

**R25 Key Fix**: `discovery_coverage` now populated from `scan_*.json stats` instead of `run_summary`. `_warn_missing_chains()` now FATAL. `scroll` properly marked as `monitoring_only`. +10 regression tests protect these fixes.

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline (3 canonical files): OK
- provenance contract: OK (run_timestamp only, no SHA)
- runtime artifacts not committed: OK
- schema version: **v1.6** (bumped from v1.5)
- test delta: +10 tests (1725 -> 1735)
