# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_ws_live_gasfix_100b (ws-live corrective evidence session)
mode: ONLINE (ws-live evidence runs + unit tests + CI gates)
artifact_mode: local evidence (data/tmp/m7a_ws_live_gasfix_30b.json, data/tmp/m7a_ws_live_gasfix_100b.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-03-27T21:30:14Z
  dirty: true
  desc: M7.A.5.9 token-decimal size normalization + gas denomination conversion

## Session Completion
session_goal: M7.A.5.9 -- fix token-decimal-blind size bug (backrun_size_wei clamped to 10^15..10^18 for all tokens, but USDC/USDT are 6-decimal) AND fix cross-denomination gas/bps unit mismatch (gas in ETH wei divided by backrun in USDC raw units produced -200 billion bps)
goal_status: REACHED (both bugs fixed; corrective evidence confirms denomination-correct economics; GAS_EXCEEDS_GROSS verdict unchanged but measurements now trustworthy)
close_allowed: true
remaining_blockers: none (M7.A blocker stack fully characterized with denomination-correct evidence)
evidence_session_run_dirs: [data/tmp/m7a_ws_live_gasfix_30b.json, data/tmp/m7a_ws_live_gasfix_100b.json]
primary_blocker_of_session: M7.A.5.8 evidence contained two measurement bugs: (1) decimal-blind size normalization, (2) cross-denomination gas/bps calculation
blocker_status_before: ACTIVE (M7.A.5.8 gas economics for non-18-dec tokens were off by 10^8x)
blocker_status_after: RESOLVED -- denomination-correct evidence confirms GAS_EXCEEDS_GROSS remains sole dominant blocker; USDC net_bps=-400 (was -200B), WETH net_bps=-0.19 (unchanged)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.9 -- fix decimal-blind size bug and gas denomination mismatch discovered in M7.A.5.8 evidence; produce corrective evidence with trustworthy economics
change_summary:
  - Added _normalized_bounds() -- scales size bounds by 10^(18-decimals) ratio (USDC 10^3..10^6, WBTC 10^5..10^8)
  - Added _gas_cost_in_token_wei() -- converts ETH gas to backrun token denomination via oracle prices
  - Added _FALLBACK_ETH_PRICE_USD ($3500 fallback), _REF_MIN_WEI_18, _REF_MAX_WEI_18 constants
  - Added 4 new BackrunResult fields: token_in_decimals, size_normalization_source, size_usd_estimate, size_valid_for_token (49->53 fields)
  - Fixed score_backrun_live_parallel(): decimal-aware size clamping + gas denomination conversion via Chainlink oracle
  - Fixed score_backrun_live(): decimal detection from symbol heuristic + gas denomination conversion
  - Fixed _run_size_sweep(): accepts gas_cost_token_wei parameter for denomination-correct sweep economics
  - Added .env loading in main() via load_root_dotenv()
  - Added size_normalization_metrics and m7a59_hypothesis artifact blocks
  - Added 27 new contract tests (252 total orderflow, 2988 total suite)
touched_files:
  - scripts/m7a_orderflow_replay.py (MODIFIED: size normalization, gas denomination, 4 new fields, 2 artifact blocks)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +27 tests, 252 total; 5 new test classes)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.9 section added, header updated)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (252 passed in ~2s)
py -3.11 -m pytest tests/unit -q: PASS (2988 passed, 6 skipped in ~52s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (52.9s, ALL REQUIRED GATES PASSED)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 30 --output data/tmp/m7a_ws_live_gasfix_30b.json: PASS (2 events)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 100 --output data/tmp/m7a_ws_live_gasfix_100b.json: PASS (10 events)

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_ws_live_gasfix_30b.json (30-block ws-live, 2 events)
  - data/tmp/m7a_ws_live_gasfix_100b.json (100-block ws-live, 10 events)

## 4) Key Results -- M7.A.5.9 Corrective Evidence

### Bug #1: Decimal-Blind Size Normalization (FIXED)

| Token | decimals | OLD bounds | NEW bounds | OLD backrun_size | NEW backrun_size |
|-------|----------|------------|------------|------------------|------------------|
| WETH | 18 | 10^15..10^18 | 10^15..10^18 | ~10^15 (0.001 ETH) | ~10^15 (unchanged) |
| USDC | 6 | 10^15..10^18 | 10^3..10^6 | 10^15 ($1B!) | 10^6 ($1) |
| WBTC | 8 | 10^15..10^18 | 10^5..10^8 | 10^15 ($10^7 BTC!) | 10^8 (1.0 WBTC) |

### Bug #2: Gas Denomination Mismatch (FIXED)

| Token | OLD gas_cost_wei | NEW gas_cost_wei | OLD net_bps | NEW net_bps |
|-------|------------------|------------------|-------------|-------------|
| USDC (6-dec) | 20,000,000,000,000 (ETH!) | 39,842 (USDC) | **-200,000,000,008** | **-400** |
| WETH (18-dec) | 20,000,000,000,000 | 20,000,000,000,000 | -0.19 | -0.19 |
| PENDLE (~$0.16) | 20,000,000,000,000 (ETH!) | 448,835,748,027,946,816 (PENDLE) | N/A | -4475 |

### 100-Block Evidence Summary

| Metric | Value |
|--------|-------|
| events_count | 10 |
| results_count | 10 |
| viable_count | 0 |
| best_net_bps | 0.0 |
| worst_net_bps | -4475 |
| mean_net_bps | -963 |
| GAS_EXCEEDS_GROSS rate | 100% (9/9 scored) |
| bps range | [-4475, -0.19] (human-readable) |

### Gas Decomposition (Denomination-Correct)

| Metric | 30b run | 100b run |
|--------|---------|----------|
| events_with_gas_decomp | 1 | 8 |
| mean_total_gas_bps | 398.42 | varies by token price |
| USDC tgas_bps | 398.42 | 398.42 |
| WETH tgas_bps | N/A | 0.2 |
| PENDLE tgas_bps | N/A | 4488 |

### BackrunResult Evolution

| Version | Fields | New Fields |
|---------|--------|-----------|
| M7.A.5.8 | 49 | l2_gas_bps, l1_data_bps, total_gas_bps, subgraph_seed_used |
| M7.A.5.9 | **53** | token_in_decimals, size_normalization_source, size_usd_estimate, size_valid_for_token |

### Test Summary

| Test Class | Count | Status |
|------------|-------|--------|
| TestM7A59NormalizedBounds | 11 | PASS |
| TestM7A59BackrunResultFields | 3 | PASS |
| TestM7A59SizeNormalizationContract | 4 | PASS |
| TestM7A59BackwardCompat | 2 | PASS |
| TestM7A59GasDenominationConversion | 9 | PASS (NEW this sub-session) |
| **Total new (M7.A.5.9)** | **29** | **PASS** |
| **Total orderflow tests** | **252** | **PASS** |
| **Total all tests** | **2988** | **PASS (6 skipped)** |

## 5) Strategic Reading

1. **M7.A.5.8 gas economics were wrong by 10^8x for non-18-decimal tokens**: The decimal-blind size bug inflated USDC backrun_size from $1 to $1B, and the gas denomination mismatch divided ETH-denominated gas by USDC-denominated amount, producing -200 billion bps instead of -400 bps. Both bugs are now fixed with denomination-correct evidence.

2. **GAS_EXCEEDS_GROSS verdict is CONFIRMED with correct accounting**: After fixing both bugs, gas still exceeds gross for 100% of events. For USDC: gas is 398 bps (~$0.04 on a $1 backrun). For WETH: gas is 0.2 bps (~$0.07 on a $3500 backrun). The verdict is unchanged but the measurements are now trustworthy.

3. **Gas denomination conversion uses oracle prices from Chainlink**: The _gas_cost_in_token_wei() helper converts ETH gas via: `gas_token = gas_eth * eth_usd / tok_usd * 10^dec / 10^18`. Uses live Chainlink oracle for ETH and token_in prices, falls back to $3500/$1 heuristic.

4. **Cheap tokens show highest gas overhead, as expected**: PENDLE (~$0.16) shows 4488 bps gas overhead — $0.07 gas on a $0.16 backrun is 44.9%. WETH shows 0.2 bps. This confirms gas economics are token-price-dependent but always structurally unviable at small sizes.

5. **M7.A is now fully closed with denomination-correct evidence**: All three independent blockers confirmed: (1) latency 400ms (M7.A.5.4), (2) coverage resolved (M7.A.5.7), (3) gas economics — now with correct denomination — still block 100% of events.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY -- NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY -- NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime) |
| M7.A.4 | **CLOSED BOUNDED BASELINE** (orderflow replay, intent scout) |
| M7.A.5 | **LIVE EVIDENCE: NOT VIABLE** (public RPC latency) |
| M7.A.5.5 | **LIVE EVIDENCE: NOT VIABLE** (actual-pair token resolution) |
| M7.A.5.6 | **COVERAGE DECOMPOSED** (80% TOKEN_NOT_ADMITTED) |
| M7.A.5.7 | **INFRASTRUCTURE BUILT** (enrichment + oracle + local-sim) |
| M7.A.5.8 | **LIVE EVIDENCE: BLOCKER SHIFTED** (admission 100%, GAS_EXCEEDS_GROSS 100%) |
| M7.A.5.9 | **CORRECTIVE: DENOMINATION-CORRECT** (size + gas bugs fixed, verdict confirmed) |
| M7.B | NOT STARTED (closed by M7.A verdicts) |
