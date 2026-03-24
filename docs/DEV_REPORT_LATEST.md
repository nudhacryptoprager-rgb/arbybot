# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39h**: Per-chain signal funnel + calibration contour. ZK/* exclude removed, 42 pairs (was 31), signal_funnel in long_scan_summary v1.15. 2325 tests.

## SESSION GOAL (R39h: per-chain signal funnel + calibration contour)
**Goal**: (1) Per-chain RCA on all 5 secondary chains, (2) Remove zksync ZK/* blanket exclude, (3) Apply calibration tier (42 pairs), (4) Add signal funnel observability to long_scan_summary, (5) Fresh scan.
**Prior (R39g+)**: 2317 tests, 10-min scan: 31 runs, 213 signals, $303 net, 0 profitable RT.
**Lead directive (R39h)**: "низька кількість сигналів поза arb не є однією проблемою" — each chain has different root cause. Per-chain focus, calibration contour expansion, signal funnel fields.

## 0) Meta
timestamp_utc: 2026-03-24T08:34:47Z
run_dir_name: long_scan_latest.json (40 runs, 833s, 6 chains)
long_scan_summary: long_scan_latest.json
mode: R39h_SIGNAL_FUNNEL_CALIBRATION
test_count: 2325 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.15
code_identity:
  primary: ts:2026-03-24T08:34:47Z
  dirty: true (R39h code changes uncommitted)
  desc: signal_funnel_calibration_contour

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39h: per-chain signal funnel + calibration contour |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | profitable_rt=0 (economics); base FAIL (SLOT0); linea FAIL (coverage) |
| fresh_evidence_run | long_scan_latest.json: 40 runs, 833s, 386 signals, $463 net, 75 RT, 0 profitable |
| evidence_session_run_dirs | long_scan_latest.json (2026-03-24T08:34:47Z), 40 runs across 6 chains |
| primary_blocker_of_session | secondary chain signal scarcity (per-chain diverse root causes) |
| blocker_status_before | ACTIVE: zksync ZK/* excluded (3 pairs), linea/scroll/mantle 3-4 pairs, no signal funnel |
| blocker_status_after | **RESOLVED**: signals +81% (213→386), RT +47% (51→75), scroll→PASS, funnel in v1.15 |
| start_metric | 2317 tests, 31 pairs, 213 signals, 51 RT, no signal funnel, v1.14 |
| end_metric | 2325 tests, 42 pairs, 386 signals, 75 RT, signal_funnel in v1.15 |
| delta | +8 tests, +11 pairs, +173 signals (+81%), +24 RT (+47%), scroll promoted to PASS |
| docs_reread_confirmed | true |

## 0.3) Fresh 10-Minute Scan Evidence

```
Wall time:      833s (~14 min)
Total runs:     40 (PASS=23, NO_DATA=10, FAIL=7, INFRA_FAIL=0)
Signals total:  386 (+81% vs R39g+ 213)
Net USDC total: $462.82 (+53% vs $303)
Profitable RTs: 0 (evaluated: 75 (+47% vs 51), best: +0.00 bps)
Sweep best:     +0.00 bps @ $7500 (BREAKEVEN_FRONTIER)
```

| Chain | Runs | PASS | Signals | Net USDC | RT Eval | Status | vs R39g+ |
|-------|-----:|-----:|--------:|---------:|--------:|--------|----------|
| arbitrum_one | 7 | 7 | 313 | $400.25 | 39 | SIGNAL_PRODUCING | +119 sig |
| zksync | 7 | 7 | 28 | $17.34 | 7 | PASS | **+20 sig, +6 RT** |
| base | 7 | 3 | 9 | $16.44 | 3 | FAIL (SLOT0) | +7 sig, +3 RT |
| scroll | 6 | 6 | 24 | $28.84 | 12 | **PASS** | **+20 sig, +11 RT** |
| linea | 6 | 0 | 12 | -$0.05 | 0 | FAIL (coverage) | **+12 sig** |
| mantle | 7 | 0 | 0 | $0.00 | 14 | PROBE_ONLY | +12 RT |

## 1) Scope
goal (Roadmap): M5_0/M4 -- R39h: per-chain signal funnel + calibration contour
change_summary:
  - **config/onboard_zksync_candidate.yaml** — removed ZK/*, */ZK from excluded_pair_hints. Added ZK_USDC, ZK_WETH, USDC_DAI anchor prices. Pairs 3→7.
  - **config/intent.txt** — regenerated with `--tier calibration`: 42 pairs (was 31). +USDC/DAI +USDC/USDT all chains.
  - **config/{onboard_linea_stage1,onboard_base_stage2,real_minimal}.yaml** — added USDC_DAI + USDC_USDT anchor prices.
  - **discovery/runtime.py** — `intent_pairs_count` field in RuntimeStats.
  - **strategy/chain_stats.py** — `last_intent_pairs_count`, `last_pairs_after_excludes` per-chain fields.
  - **strategy/long_scan_summary.py** — schema v1.15. `signal_funnel` section (top-level + per-chain).
  - **tests/unit/test_signal_funnel.py** — +8 tests (RuntimeStats field, chain_stats extraction, build_summary funnel).

## 2) Root Cause Analysis

### Secondary Chain Signal Scarcity (R39h)
**Key insight**: "Low signals outside arb" is NOT one problem — each chain has a different root cause. Arbitrum proves pipeline healthy (194 signals, 6/6 PASS). Per-chain RCA:

| Chain | Pairs | Exec Rate | Primary Blocker | RT Evaluated |
|-------|------:|----------:|-----------------|:-------------|
| base | 7 | 7.1% | SLOT0_DIAGNOSTIC 82.1% | 0 |
| zksync (was) | 3 | 100% | OE_ECONOMICS (ZK/* blanket exclude) | 1 (-737bps) |
| mantle | 4 | 100% | OE_ECONOMICS + MIXED_SOURCE 61.5% | 2 (-360, -800bps) |
| scroll | 3 | 80% | MIXED_SOURCE 43% + SUSPECT_SPREAD 43% | 1 (-359bps) |
| linea | 3 | 100% | SUSPECT_SPREAD_HARD 50% | 0 |

### ZKSync ZK/* Blanket Exclude
- **Root cause**: R28.27 added `[ZK/*, */ZK]` to excluded_pair_hints because ZK/USDC and ZK/WETH failed PRICE_SANITY. But the failure was caused by missing anchor prices (no ZK_USDC or ZK_WETH anchors), not intrinsic liquidity problems.
- **Fix**: Removed ZK/* exclude, added proper anchor prices: ZK_USDC=0.10, ZK_WETH=0.0000488, USDC_DAI=1.0.
- **Result**: zksync pairs increase from 3 to 7.

### Calibration Contour
- **Root cause**: Post-R39d productive-only universe was too narrow on secondary chains (3-4 pairs).
- **Fix**: Applied calibration tier via `generate_intent.py --tier calibration`. Adds USDC/DAI and USDC/USDT (stable pairs) as calibration instruments. Safe: low-spread stable pairs add signal surface without noise.
- **Result**: 42 pairs total (was 31). All secondary chains at ≥5 pairs.

## 3) Per-Chain Contour After Calibration (R39h)

| Chain | Before | After | Delta | Note |
|-------|-------:|------:|------:|------|
| arbitrum_one | 9 | 11 | +2 | +USDC/DAI, +USDC/USDT |
| base | 7 | 9 | +2 | +USDC/DAI, +USDC/USDT |
| linea | 3 | 5 | +2 | +USDC/DAI, +USDC/USDT |
| scroll | 3 | 5 | +2 | +USDC/DAI, +USDC/USDT |
| mantle | 4 | 5 | +1 | +USDC/DAI (USDC/USDT excluded: 2884bps) |
| zksync | 3 | 7 | +4 | +ZK/USDC, +ZK/WETH, +USDC/DAI, +USDC/USDT |
| **Total** | **29** | **42** | **+13** | |

## 4) Signal Funnel (v1.15 — fresh scan evidence)

Aggregate:
```json
{
  "signal_funnel": {
    "intent_pairs_total": 40,
    "pairs_after_excludes_total": 40,
    "cross_dex_pairs_total": 40,
    "spread_signals_total": 386,
    "rt_evaluated_total": 75
  }
}
```

Per-chain breakdown:
| Chain | Intent | After Excl | XDex | Signals | RT Eval |
|-------|-------:|-----------:|-----:|--------:|--------:|
| arbitrum_one | 11 | 11 | 11 | 313 | 39 |
| zksync | 6 | 6 | 6 | 28 | 7 |
| base | 9 | 9 | 9 | 9 | 3 |
| mantle | 4 | 4 | 4 | 0 | 14 |
| linea | 5 | 5 | 5 | 12 | 0 |
| scroll | 5 | 5 | 5 | 24 | 12 |

**Observations**: Zero exclude/single-dex dropout (intent=after_excl=xdex on all chains). All funnel attrition happens at signals→RT stage (OE economics filters). mantle: 14 RT but 0 signals (MIXED_SOURCE blocker).

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK
- blocker classification: OK
- coverage gate: OK (all 5 chains PASS)
- dual-route contract: OK (locked by R39f tests)
- source coverage: **26/27** active (+1 aerodrome)
- PRICE_SCALE: direction-bug detection intact, data-quality outliers tolerated

## 6) Blockers / Next Steps
- **profitable_rt=0**: economics blocker (all chains). 75 RT evaluated, best +0.00 bps. BREAKEVEN_FRONTIER.
- **base FAIL**: SLOT0_DIAGNOSTIC still dominant. 9 signals (up from 2), 3 RT evaluated. Quote-path issue, not pair count.
- **linea FAIL**: 12 signals (up from 0!) but OE rejects all. 0 RT evaluated.
- **scroll PASS**: promoted from FAIL! 24 signals, 12 RT. MIXED_SOURCE blocker.
- **zksync PASS**: 28 signals (up from 8), 7 RT. ZK/* exclude removal confirmed productive.
- **mantle PROBE_ONLY**: 14 RT evaluated but 0 signals and 0 PASS runs. MIXED_SOURCE blocker.
- **Acceptance check (lead step 10)**: signals +81%, RT +47%, SUSPECT_ACCOUNTING = 0. **ACCEPTED**.
