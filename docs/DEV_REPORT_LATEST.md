# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39d**: Quality-ranked pair selection. Tiered intent generation: productive/exploratory/diagnostic. core_tokens.yaml metadata for all tokens. Productive contour: 31 pairs (down from 116), focused on volatile + liquid + multi-DEX tokens.

## SESSION GOAL (R39d: quality-ranked pair selection)
**Goal**: (1) Add tier metadata to core_tokens.yaml, (2) Refactor generate_intent.py from blind inventory to tiered selector, (3) Regenerate intent.txt with productive contour per lead's P0 directives.
**Prior (R39c)**: 2259 tests, EXECUTABLE_BEST_NEG distinction, route-level RCA, market surface conclusion.
**Lead directive (R39d)**: Next leverage is not broader inventory coverage but quality-ranked pair selection. Healthy supported chains already reaching real RT and failing on economics. Productive contour: volatile + liquid + multi-DEX pairs (ARB, PENDLE, AERO, VIRTUAL, WMNT, ZK). Stable/stable, LST/LRT, thin long-tail → diagnostic/exploratory.

## 0) Meta
timestamp_utc: 2026-03-23T19:42:43Z
run_dir_name: ci_m5_gate_arbitrum_one_20260323_204211_940499
mode: R39d_TIERED_INTENT
test_count: 2290 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.14
code_identity:
  primary: ts:2026-03-23T19:42:43.862399Z
  dirty: true (R39d code changes uncommitted)
  desc: tiered_intent_quality_ranked

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39d: quality-ranked pair selection — tiered intent generation |
| goal_status | **REACHED** (3 files changed, 31 new tests, 2290 PASS, productive contour 31 pairs, all lead P0 directives implemented) |
| close_allowed | true |
| remaining_blockers | profitable_rt=0 (market economics). Scan density improved: arb 195 sig/6 runs, 28 real_quotes. |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260323_204211_940499 (fresh R39d scan: 36 runs, 203 signals, 37 RT, 0 profitable) |
| primary_blocker_of_session | Blind inventory-based intent generation → 116 noisy pairs, many producing only diagnostic data |
| blocker_status_before | ACTIVE: intent.txt generated blindly from inventory, not from volatility × liquidity × cross-dex fragmentation |
| blocker_status_after | **RESOLVED**: Tiered selector with productive/exploratory/diagnostic. 31 productive pairs focused on volatile + liquid + multi-DEX. |
| start_metric | 2259 tests, 116 blind pairs, stable/LST/thin-tail in default universe |
| end_metric | 2290 tests, 31 productive pairs, quality-ranked by tier metadata |
| delta | +31 tests, +tier metadata (core_tokens.yaml), +tiered selector (generate_intent.py), intent.txt 116→31 productive |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R39d: quality-ranked pair selection
change_summary:
  - **R39d**: `config/core_tokens.yaml` — Tier metadata for all tokens: volatility_tier, liquidity_tier, cross_dex_expected, accounting_sensitive, productive_default.
  - **R39d**: `scripts/generate_intent.py` — Refactored: classify_token() → productive/exploratory/diagnostic. generate_pairs_for_chain(tier_filter). --tier CLI flag.
  - **R39d**: `config/intent.txt` — Regenerated: 31 productive pairs (was 116). Stable/stable, LST/LRT, thin long-tail excluded.
  - **R39d**: `tests/unit/test_tiered_intent.py` — +31 tests: classify_token, per-chain P0-matching, tier expansion, metadata contract, sanity.
  - **R39d**: `docs/status/Status_M5_0.md` — R39d section.
touched_files:
  - config/core_tokens.yaml (tier metadata for all 60+ tokens)
  - scripts/generate_intent.py (tiered selector refactor)
  - config/intent.txt (productive contour: 31 pairs)
  - tests/unit/test_tiered_intent.py (+31 tests)
  - docs/status/Status_M5_0.md (R39d section)
  - docs/DEV_REPORT_LATEST.md (synced to R39d)

## 2) Commands Executed

```
py -3.11 scripts/generate_intent.py: 31 productive pairs (dry-run verified)
py -3.11 scripts/generate_intent.py --write: wrote 31 pairs to intent.txt
py -3.11 -m pytest tests/unit -q: 2290 passed, 5 skipped
```

## 3) R39d Architecture Changes

### Tiered Intent Generation (generate_intent.py)
Problem: intent.txt generated blindly from inventory — every token paired with WETH/USDC regardless of quality. 116 pairs including stable/stable (USDC/DAI -54 bps), LST (SUSPECT_ACCOUNTING mirages), thin long-tail (WETH/MAGIC -421 bps, WETH/RDNT -806 bps).
Fix: `classify_token()` reads tier metadata from core_tokens.yaml and classifies each token into productive (volatile + liquid + multi-DEX), exploratory (interesting but not default), or diagnostic (stable/stable, LST, near-stable). `generate_pairs_for_chain()` accepts `tier_filter` parameter. `--tier` CLI flag controls output.
Impact: Productive contour focused on 31 high-quality pairs. Scanner will spend cycles on tokens most likely to produce real arbitrage (volatile price movement + deep liquidity + multi-DEX fragmentation).

### Per-Chain P0 Productive Sets (from lead's external research)
- **arb**: ARB/USDC, WETH/ARB, PENDLE/USDC, WETH/PENDLE, LINK/USDC, WETH/LINK, WBTC/USDC, WETH/USDC, WETH/WBTC
- **base**: AERO/USDC, WETH/AERO, VIRTUAL/USDC, WETH/VIRTUAL, cbBTC/USDC, cbBTC/WETH, WETH/USDC
- **mantle**: WMNT/USDC, WMNT/USDT, WETH/WMNT, WETH/USDC
- **zksync**: ZK/USDC, ZK/WETH, WBTC/USDC, WETH/USDC, WETH/WBTC
- **scroll**: WETH/USDC, WBTC/USDC, WETH/WBTC
- **linea**: WETH/USDC, WBTC/USDC, WETH/WBTC
  - **R39b**: `strategy/jobs/run_scan_real.py` — Field name fix: `measured_*` → `best_*`.
  - **R39b**: `strategy/chain_stats.py` — Truthiness fix for measured fields.
  - **R39b**: `strategy/pair_trace.py` — Gas computation fix. 
  - **R39a**: `tests/unit/test_r38_changes.py` — +9 tests.
  - **R39b**: `tests/unit/test_r38_changes.py` — +4 tests.
touched_files:
  - strategy/chain_stats.py (EXECUTABLE_BEST_NEG + 0.0 truthiness)
  - strategy/long_scan_summary.py (EXECUTABLE_BEST_NEG fence + ranking + sort key fix)
  - strategy/jobs/run_scan_real.py (EXECUTABLE_BEST_NEG guard + field name fix)
  - scripts/pair_level_rca.py (route-level RCA + gas from reject_reason)
  - strategy/pair_trace.py (gas computation fix)
  - tests/unit/test_r38_changes.py (+21 tests total: R39a:9 + R39b:4 + R39c:8)
  - docs/status/Status_M5_0.md (R39c section)
  - docs/DEV_REPORT_LATEST.md (synced to R39c)

## 2) Commands Executed

```
py -3.11 scripts/generate_intent.py: 31 productive pairs (dry-run verified)
py -3.11 scripts/generate_intent.py --write: wrote 31 pairs to intent.txt
py -3.11 -m pytest tests/unit -q: 2290 passed, 5 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci: (pending post-trim)
```

## 3) R39d Architecture Changes

### Tiered Intent Generation (generate_intent.py)
Problem: intent.txt generated blindly from inventory — every token paired with WETH/USDC regardless of quality. 116 pairs including stable/stable (USDC/DAI -54 bps), LST (SUSPECT_ACCOUNTING mirages), thin long-tail (WETH/MAGIC -421, WETH/RDNT -806).
Fix: `classify_token()` reads tier metadata from core_tokens.yaml. Three tiers: productive (volatile+liquid+multi-DEX), exploratory (interesting but not default), diagnostic (stable/LST/near-stable). `--tier` CLI flag controls output.
Impact: 31 productive pairs (was 116). Scanner cycles focused on high-quality tokens.

### Per-Chain P0 Productive Contour
| Chain | Pairs | Key Tokens | Demoted |
|-------|-------|------------|---------|
| arb | 9 | ARB, PENDLE, LINK, WBTC | DPX, GRAIL, GNS, JOE, MAGIC, RDNT, TBTC |
| base | 7 | AERO, VIRTUAL, cbBTC | BRETT, DEGEN, TOSHI, WELL → exploratory |
| mantle | 4 | WMNT | mETH, cmETH, PUFF → diagnostic/exploratory |
| zksync | 5 | ZK, WBTC | CHEEMS, HOLD → exploratory |
| scroll | 3 | WBTC | SCR → exploratory |
| linea | 3 | WBTC | LYNX, NILE, STONE/ezETH/weETH → exploratory/diagnostic |

## 4) Fresh Evidence (R39d canonical scan — 31 productive pairs)
- 36 runs, 203 signals, 37 RT evaluated, 0 profitable, $337.70 net USDC
- arb: 6/6 PASS, 195 signals, 28 real_quotes, 9 cross_dex — SIGNAL_PRODUCING
- zksync: 2/6 PASS, 6 signals, 2 real_quotes, 3 cross_dex — SIGNAL_PRODUCING
- base: 2/6 PASS (4 NO_DATA), 2 signals, 1 real_quote, 7 cross_dex — INFRA_READY
- mantle: 0/6 PASS, 0 signals, 4 real_quotes, 4 cross_dex — INFRA_READY
- linea: 0/6 PASS, 0 signals, 0 real_quotes, 3 cross_dex — FAIL
- scroll: 0/6 PASS, 0 signals, 2 real_quotes, 3 cross_dex — FAIL_QUALITY (accepted-fail)
- All chains: profitable_rt=0 (market economics — spread < slippage + LP fee + gas)
- Spread gap: +31.54 bps (measured, target >=0)
- Prior R39c (116 pairs): 30 runs/225 signals/70 RT. Density comparable with 73% fewer pairs.

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK — canonical rolling artifacts
- v2.x provenance: OK — run_timestamp based
- frontier contract: OK — post-aggregation fence + EXECUTABLE_BEST_NEG
- sweep guard: OK — promotion requires executable frontier
- LST threshold: _SANE_RT_PNL_MAX_BPS_LST=50 active
- tiered intent: OK — productive_default metadata drives pair selection

## 6) Blockers / Risks
- **profitable_rt=0**: Market economics blocker on all healthy chains. Not infra.
- **base quote-path**: Still needs Aerodrome adapter for full surface. 4/6 NO_DATA.
- **linea FAIL**: 0/6 pass, 0 signals — infra issue persists.
- **mantle/scroll**: No signals. Need adapter coverage investigation.

## 7) What I need from Lead now
1. **Evaluate density**: 31 productive pairs → arb 195 signals/6 runs. Per-pair density UP vs R39c. Good sign.
2. **Next step after R39d**: event-driven re-quote (WS block triggers) + final RT size promotion validation.
3. **base/linea/mantle**: Adapter gaps causing NO_DATA/FAIL — need prioritized adapter work.
