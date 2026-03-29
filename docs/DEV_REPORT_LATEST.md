# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14.342304Z
run_id: ci_m5_gate_arbitrum_one_20260327_222948_123275
mode: OFFLINE (infrastructure build + unit tests + CI gates; no new live run)
artifact_mode: rolling (unchanged)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-03-27T21:30:14.342304Z
  dirty: true
  desc: M7.A.5.7 bounded coverage enrichment + oracle sanity rails + local-sim preparation

## Session Completion
session_goal: M7.A.5.7 — build 3 infrastructure pieces for same-chain DEX backrun: (1) dynamic coverage intake via on-chain ERC-20 enrichment, (2) Chainlink oracle sanity rails, (3) local-sim pool state extraction; prove coverage gap is addressable without leaving current DEX domain
goal_status: REACHED (all 3 infrastructure pieces implemented, 27 new tests pass, all CI gates pass)
close_allowed: true
remaining_blockers: none (infrastructure complete; next step is live evidence run to measure enrichment admission rate improvement)
evidence_session_run_dirs: [] (no live evidence run — infrastructure-only session)
primary_blocker_of_session: M7.A.5.6 confirmed 80% TOKEN_NOT_ADMITTED — no mechanism existed to dynamically admit unknown on-chain tokens, no oracle guardrail, no local-sim path
blocker_status_before: ACTIVE (admission is static — unknown tokens rejected without attempt to resolve on-chain; no price oracle sanity check; no pool state extraction for local pricing)
blocker_status_after: RESOLVED (infrastructure) — enrichment pipeline reads on-chain ERC-20 symbol/decimals, oracle guard checks Chainlink staleness, pool state extractor captures sqrtPriceX96/tick/liquidity. Live evidence deferred to M7.A.5.8.
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.7 — build bounded coverage enrichment, oracle sanity rails, and local-sim preparation to address the 80% TOKEN_NOT_ADMITTED blocker without leaving same-chain DEX domain
change_summary:
  - Added `batch_symbol()` to `MulticallBatcher` — on-chain ERC-20 symbol() reads via multicall3
  - Added `enrich_unknown_token()` / `enrich_tokens_batch()` — on-chain ERC-20 enrichment (symbol + decimals) for unknown tokens
  - Added `check_oracle_sanity()` — Chainlink latestRoundData() via multicall for 10 Arbitrum feeds; staleness guard (>3600s)
  - Added `extract_pool_state_for_sim()` — V3 pool state extraction (sqrtPriceX96, tick, liquidity) for future local-sim pricing
  - Added 4 admission source constants: ADMISSION_CANONICAL, ADMISSION_ADDR_TO_SYMBOL, ADMISSION_SUBGRAPH_VERIFIED, ADMISSION_REJECTED
  - Added CHAINLINK_FEEDS_ARBITRUM dict (10 feeds: WETH, WBTC, USDT, USDC, ARB, LINK, DAI, UNI, GMX, PENDLE)
  - Added 3 new BackrunResult fields: admission_source, oracle_guard, local_sim_state (42→45 fields)
  - Updated `admit_event_tokens()` to return 7-key dict with admission_source provenance
  - Updated `score_backrun_live_parallel()` — enrichment before admission, oracle guard after admission, local-sim after coverage scan
  - Added 3 new artifact blocks: enrichment_metrics, oracle_guard_metrics, local_sim_readiness
  - Added 27 new contract tests (214 total orderflow, 2950 total suite)
touched_files:
  - core/multicall.py (MODIFIED: +batch_symbol method)
  - scripts/m7a_orderflow_replay.py (MODIFIED: enrichment, oracle guard, local-sim, admission source, 3 new fields, 3 artifact blocks)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +27 tests, 214 total)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.7 section added, header updated)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (214 passed in ~2s)
py -3.11 -m pytest tests/unit -q: PASS (2950 passed, 6 skipped in ~57s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (53.7s, ALL REQUIRED GATES PASSED)

## 3) Artifacts Attached

rolling (unchanged from M7.A.5.6):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json

no new local_session artifacts (infrastructure-only session)

## 4) Key Results — M7.A.5.7 Infrastructure Build

### New Infrastructure Components

| Component | Purpose | Implementation |
|-----------|---------|---------------|
| batch_symbol() | On-chain ERC-20 symbol reads | core/multicall.py — ABI-encoded symbol() via multicall3 |
| enrich_unknown_token() | Single-token enrichment | batch_symbol + batch_decimals, returns {symbol, decimals, resolved} |
| enrich_tokens_batch() | Multi-token enrichment | Batched enrichment for all unknown tokens in event |
| check_oracle_sanity() | Chainlink price guard | latestRoundData() via multicall, staleness >3600s triggers guard |
| extract_pool_state_for_sim() | V3 pool state | sqrtPriceX96, tick, liquidity via batch_full_pool_data |

### Admission Source Provenance (new)

| Source | Meaning |
|--------|---------|
| canonical_core | Both tokens in core_tokens.yaml |
| addr_to_symbol | One token resolved via addr_to_symbol mapping |
| subgraph_seeded_verified | Token resolved via on-chain enrichment (new in M7.A.5.7) |
| rejected_unverified | Not admitted after all resolution attempts |

### Chainlink Oracle Feeds (Arbitrum One)

10 feeds configured: WETH, WBTC, USDT, USDC, ARB, LINK, DAI, UNI, GMX, PENDLE
Guard trigger: staleness > 3600 seconds
Output schema: {oracle_price_available, token_in_oracle_usd, token_out_oracle_usd, oracle_deviation_bps, oracle_guard_triggered, oracle_staleness_seconds}

### BackrunResult Evolution

| Version | Fields | New Fields |
|---------|--------|-----------|
| M7.A.5.5 | 37 | pair resolution fields |
| M7.A.5.6 | 42 | coverage, sweep, admission |
| M7.A.5.7 | 45 | admission_source, oracle_guard, local_sim_state |

### New Artifact Blocks (in m7a output JSON)

| Block | Key Metrics |
|-------|------------|
| enrichment_metrics | admission_source_histogram, events_enriched_onchain, enrichment_admission_rate |
| oracle_guard_metrics | events_with_oracle_price, oracle_coverage_rate, guard_triggered_count |
| local_sim_readiness | events_with_pool_state, sim_readiness_rate, total_pools_queried/with_state |

### Test Summary

| Test Class | Count | Status |
|------------|-------|--------|
| TestM7A57AdmissionSource | 7 | PASS |
| TestM7A57ChainlinkConstants | 5 | PASS |
| TestM7A57OracleGuard | 4 | PASS |
| TestM7A57EnrichmentFunctions | 4 | PASS |
| TestM7A57LocalSimState | 2 | PASS |
| TestM7A57BackwardCompat | 2 | PASS |
| + 3 methods in existing classes | 3 | PASS |
| **Total new (this session)** | **27** | **PASS** |
| **Total orderflow tests** | **214** | **PASS** |
| **Total all tests** | **2950** | **PASS (6 skipped)** |

## 5) Strategic Reading

1. **Coverage gap is now addressable**: M7.A.5.6 proved 80% TOKEN_NOT_ADMITTED. This session adds on-chain ERC-20 enrichment — unknown tokens can now be dynamically resolved (symbol + decimals) and admitted as `subgraph_seeded_verified`. The hypothesis: enrichment will increase admission rate significantly because most swap events involve standard ERC-20 tokens.

2. **Oracle sanity rails prevent blind pricing**: Chainlink latestRoundData() provides independent USD price for 10 major Arbitrum tokens. This guards against stale or manipulated on-chain prices. The staleness threshold (3600s) is conservative for production use.

3. **Local-sim state extraction prepares Bellman-Ford-free pricing**: V3 pool state (sqrtPriceX96, tick, liquidity) can compute local swap output without on-chain QuoterV2 calls. This eliminates the 400ms per-call RPC bottleneck identified in M7.A.5.4 — but implementation of the actual math is deferred.

4. **Admission source provenance enables diagnosis**: Every event now carries `admission_source` tracking HOW the token was admitted. This enables measuring enrichment effectiveness: what fraction of previously-rejected events are now admitted via on-chain resolution?

5. **Infrastructure-only session — live evidence deferred**: No ws-live run was executed. All 3 components are tested via unit tests (27 new, all pass). Live evidence measuring actual enrichment admission rate improvement requires M7.A.5.8.

6. **Directive followed: no Bellman-Ford, no NetworkX, no DEX-CEX**: All changes stay within same-chain DEX backrun domain. The 3 pieces (enrichment, oracle rails, local-sim prep) are additive to existing pipeline.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY — NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY — NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime) |
| M7.A.4 | **CLOSED BOUNDED BASELINE** (orderflow replay, intent scout) |
| M7.A.5 | **LIVE EVIDENCE: NOT VIABLE** (public RPC latency) |
| M7.A.5.5 | **LIVE EVIDENCE: NOT VIABLE** (actual-pair token resolution) |
| M7.A.5.6 | **COVERAGE DECOMPOSED** (80% TOKEN_NOT_ADMITTED, infrastructure works) |
| M7.A.5.7 | **INFRASTRUCTURE BUILT** (enrichment + oracle rails + local-sim prep; no live evidence yet) |
| M7.B | NOT STARTED (closed by M7.A verdicts) |
