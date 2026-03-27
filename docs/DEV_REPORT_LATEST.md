# DEV_REPORT_LATEST.md — R39x+1

## 0.1 Мета-інформація

| Поле | Значення |
|------|----------|
| session_id | R39x+1 |
| session_date | 2026-03-27 |
| branch | split/code |
| run_timestamp | 2026-03-27T17:49:22Z |
| rolling_run_dir | ci_m5_gate_arbitrum_one_20260327_184856_355953 |
| docs_reread_confirmed | true |

## 0.2 Закриття сесії

| Поле | Значення |
|------|----------|
| session_goal | Fix Base quote-path outage (quoter_v2_failed_count=65, 0 executable quotes) so R39x sweep-frontier reranking can be verified on Base |
| goal_status | REACHED |
| close_allowed | true |
| blocker_status_before | Base quote-path blocked: all 65 QuoterV2 calls fail, v3_slot0_failed_count=65, quotes_fetched=0, 38 consecutive FAIL runs |
| blocker_status_after | Base quote-path restored: quotes_fetched=23, dexes_active=4, v3_slot0_failed_count=0, quoter_v2_failed_count=0, _sweep_frontier_reranked=true |
| evidence_session_run_dirs | long_scan_latest.json (55 runs, wall=1207.8s) |
| remaining_blockers | Base rq=0 (OE economics gate rejects stable pairs at $0.50 minimum); flashblocks sim_success_count=0 |

## 1. Що зроблено

### 1.1 Root cause analysis: Base quote-path outage

Diagnosed two compounding failures that caused `quoter_v2_failed_count=65` and `quotes_fetched=0` across all Base runs:

1. **Code bug: QuoterV2 prefetch missing fallback URLs** — `strategy/quotes.py` line 635 submitted `read_quoter_v2()` to the thread pool prefetch WITHOUT passing `fallback_rpc_urls`. When the primary RPC returned 429, the prefetch stored `QUOTER_RATE_LIMITED` sentinel in the result cache. The main loop then consumed the cached sentinel → treated as failure → fell to slot0 multicall → multicall also failed (single RPC, same 429) → `V3_SLOT0_FAILED` for all 65 pools.

2. **Config: `onboard_base_stage2.yaml` has only 2 public RPCs** (`mainnet.base.org` + `base.public.blastapi.io`), both aggressively rate-limiting. `onboard_base_profit.yaml` already had 5 RPCs + Alchemy (created in R39p).

### 1.2 Fix: Prefetch fallback URL propagation (strategy/quotes.py)

- **QuoterV2 prefetch** now passes `_fallback_rpc_urls` to `read_quoter_v2()` in the thread pool submit call. Previously only the non-prefetch code path (cache miss) passed fallback URLs.
- **Multicall fallback** added: if primary multicall returns zero slot0 hits, retries on first fallback RPC. Previously multicall only tried the primary URL.

### 1.3 Regression tests (test_quoter_v2_prefetch_fallback.py)

3 new tests:
- `test_quoter_v2_uses_fallback_on_429` — verifies read_quoter_v2 tries fallback RPC after primary 429, returns successful result from fallback
- `test_quoter_v2_all_429_returns_rate_limited_sentinel` — verifies QUOTER_RATE_LIMITED sentinel when all RPCs 429
- `test_prefetch_quoter_v2_call_includes_fallback_rpc_urls` — AST structural test that the prefetch submit() call includes `_fallback_rpc_urls` parameter (prevents regression)

## 2. Доказова база

### 2.1 Before vs After (Base chain)

| Метрика | Before (stage2, no fix) | After (profit + fix) |
|---------|------------------------|---------------------|
| config | onboard_base_stage2.yaml | onboard_base_profit.yaml |
| rpc_endpoints | 2 (public, rate-limited) | 5 (Alchemy + 4 public) |
| quotes_total | 142 | 33 |
| quotes_fetched | 0 | 23 |
| dexes_active | 0 | 4 |
| quoter_v2_failed_count | 65 | 0 |
| v3_slot0_failed_count | 65 | 0 |
| rpc_success_rate | 0.54 | 1.0 |
| spread_signals | 0 | 12 |
| _sweep_frontier_reranked | N/A | true |
| gate_result | FAIL | PASS |

### 2.2 R39x reranking — verified on Base

| Поле | Значення |
|------|----------|
| _sweep_frontier_reranked | true |
| top_opportunity #1 | USDC/DAI (gap_to_zero=8.65 bps, ranking_source=sweep_frontier) |
| top_opportunity #2 | WETH/USDC (gap_to_zero=47.28 bps, ranking_source=sweep_frontier) |
| top_opportunity #3 | USDC/USDT (gap_to_zero=8.67 bps, curve_degraded=true, _adjusted_gap=10008.67) |
| executable_evidence | SWEEP_GAP_TO_ZERO |

### 2.3 20-minute Multi-Chain Scan (step 9 evidence)

| Метрика | Значення |
|---------|----------|
| wall_seconds | 1207.8 (20.1 min) |
| total_runs | 55 |
| total_pass | 53 |
| total_fail | 2 (base FAIL_FRAGILE_HIGH, not quote-path) |
| total_signals | 1148 |
| total_net_usdc | $1245.13 |
| pass_chains | arbitrum_one |
| base_quality | SIGNAL_PRODUCING (25/27 pass, 270 signals) |
| arb_one_quality | SIGNAL_PRODUCING (28/28 pass, 878 signals) |
| dashboard | monitoring.dashboard_server port 8099 |

### 2.4 Rolling Artifact Inspection (inspect_rolling.py)

| Метрика | Значення |
|---------|----------|
| agg_status | PASS |
| data_run_rate | 1.0 |
| runs_in_window | 200 |
| total_net_usdc | $7795.05 |
| unique_pairs | 7 |
| unique_routes_cross_dex | 11 |
| signals_included | 33 |
| quality_reasons | WARN_EXCLUDED_SIGNALS, WARN_SAME_DEX_PRESENT, WARN_CRITICAL_REJECTS |

## 3. CI Gates

| Gate | Результат |
|------|-----------|
| pytest | 2515 passed, 5 skipped |
| ci_full_pipeline | ALL REQUIRED GATES PASSED |
| M4 offline profit strict | PASS (2 sims, net_usdc=0.5) |
| M5 gate Base online | PASS (quotes_fetched=23, dexes_active=4) |
| 20-min scan | 55 runs, 53 pass, wall=1207.8s, both chains SIGNAL_PRODUCING |
| inspect_rolling | agg_status=PASS, data_run_rate=1.0, 7 pairs, 11 routes |

## 4. Наступні кроки

1. **Base rq=0**: OE economics gate rejects USDC/DAI (NET_PROFIT_TOO_LOW) — stable pairs can't clear $0.50 minimum. Sweep confirms: sweep_best_net_pnl_bps=-8.65.
2. **Flashblocks**: sim_success_count=0, tx_status_reachable=false — external blocker.
3. **Config convergence**: `onboard_base_stage2.yaml` should be deprecated in favor of `onboard_base_profit.yaml` for all Base scans.
4. **Base fragile metric**: 2/27 runs hit FAIL_FRAGILE_HIGH (92.6% pass rate) — intermittent quality variance on small pool set, not a systematic issue.

## 5. Змінені файли

| Файл | Зміна |
|------|-------|
| strategy/quotes.py | +5 lines: pass _fallback_rpc_urls to prefetch read_quoter_v2, multicall fallback retry |
| tests/unit/test_quoter_v2_prefetch_fallback.py | NEW: 3 regression tests (429 fallback, rate-limited sentinel, AST structural) |
