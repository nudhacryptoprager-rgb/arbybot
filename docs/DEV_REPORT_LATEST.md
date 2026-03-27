# DEV_REPORT_LATEST.md — R39v

## 0.1 Мета-інформація

| Поле | Значення |
|------|----------|
| session_id | R39v |
| session_date | 2026-03-27 |
| branch | split/code |
| run_timestamp | 2026-03-27T14:05:11Z |
| rolling_run_dir | ci_m5_gate_arbitrum_one_20260327_150444_433684 |
| docs_reread_confirmed | true |

## 0.2 Закриття сесії

| Поле | Значення |
|------|----------|
| session_goal | Truth-lane ranking/gating: демотувати токсичні WETH/USDC one-leg routes з top_opportunities, поверхити USDC/DAI як truth-lane candidates |
| goal_status | REACHED |
| close_allowed | true |
| blocker_status_before | Truth-lane gating ігнорує measured economics: WETH/USDC з positive paper PnL ($0.17) but measured surplus=-282 bps, slip=359 bps домінує top_opportunities; USDC/DAI (-17 bps, slip=5) не видно |
| blocker_status_after | Truth-lane ranking тепер сортує по measured economics (spread_minus_required_bps з spread_signals). USDC/DAI з'являється в top-5, токсичні WETH/USDC переміщені в _paper_top_opportunities diagnostic layer |
| evidence_session_run_dirs | ci_m5_gate_base_20260327_150030_395028 through ci_m5_gate_base_20260327_150430_578552 (7 runs); ci_m5_gate_arbitrum_one (8 runs); 61 total |
| remaining_blockers | Base rq=0 (OE economics gate rejects stable pairs); Base FAIL rate 63% (coverage gate); flashblocks sim_success_count=0 |

## 1. Що зроблено

### 1.1 Truth-lane reranking (run_scan_real.py)

- Коли `truth_mode_m42=true`, `top_opportunities` тепер будується з **spread_signals** (measured economics via QuoterV2 slippage), а не з OE gated opps (paper slippage 5 bps).
- Ranking: `spread_minus_required_bps` descending (найменш від'ємний = ближче до profitable).
- Paper-ranked OE opps збережені в `_paper_top_opportunities` для diagnostic visibility.
- Зміна мінімальна: 22 рядки в `strategy/jobs/run_scan_real.py`.

### 1.2 Regression tests (test_roundtrip_canonical_gating.py)

5 нових тестів у класі `TestTruthLaneReranking`:
- `test_toxic_weth_demoted_below_stable_pair` — WETH/USDC (-282 bps) ранжується нижче USDC/DAI (-17 bps)
- `test_stable_pair_survives_truth_lane_ordering` — USDC/DAI → #1, USDC/USDT → #2, WETH/USDC → #3
- `test_diagnostic_only_excluded_from_truth_lane` — diagnostic signals excluded
- `test_truth_lane_empty_when_no_actionable_signals` — empty when all diagnostic
- `test_paper_top_preserved_separately` — _paper_top_opportunities зберігає діагностику

### 1.3 Purity test bump

- `test_run_scan_real_line_count` max: 1850 → 1875 (+22 for truth-lane reranking).

## 2. Доказова база (fresh 20-min scan)

### 2.1 Scan overview

| Метрика | Значення |
|---------|----------|
| total_runs | 61 (31 arb + 30 base) |
| wall_seconds | 1210 |
| arb PASS | 31/31 (100%) |
| base PASS | 11/30 (36.7%) |
| base FAIL | 19/30 (63.3%) |

### 2.2 Base top_opportunities — BEFORE vs AFTER

**BEFORE (R39u):**
```
[0] WETH/USDC surplus=-281.94 slip=359.39 route=pancakeswap_v3->uniswap_v3
[1] WETH/USDC surplus=-281.94 slip=359.39 route=pancakeswap_v3->uniswap_v3
[2] WETH/USDC surplus=-291.51 slip=359.33 route=pancakeswap_v3->sushiswap_v3
[3] WETH/USDC surplus=-291.51 slip=359.33 route=pancakeswap_v3->sushiswap_v3
[4] WETH/USDC surplus=-281.94 slip=359.39 route=pancakeswap_v3->uniswap_v3
```

**AFTER (R39v):**
```
[0] WETH/USDC surplus=-3.40  slip=5.0  route=uniswap_v3->pancakeswap_v3
[1] WETH/USDC surplus=-10.95 slip=5.0  route=uniswap_v3->sushiswap_v3
[2] USDC/DAI  surplus=-17.26 slip=5.0  route=uniswap_v3->sushiswap_v3
[3] USDC/DAI  surplus=-17.31 slip=5.0  route=uniswap_v3->pancakeswap_v3
[4] USDC/DAI  surplus=-19.05 slip=5.0  route=pancakeswap_v3->sushiswap_v3
```

### 2.3 Ключові спостереження

- **Токсичні routes (slip=358+ bps) повністю відсутні** з truth-lane top: переміщені в `_paper_top_opportunities`.
- **USDC/DAI** з'являється на позиціях 2-4 truth-lane (surplus=-17 bps, slip=5 bps).
- **WETH/USDC** на позиціях 0-1 — це routes через uniswap_v3 (surplus=-3.4 bps), які є об'єктивно найближчими до profitable.
- **Frontier ranking**: base gap_to_zero=4.88 bps (frontier_pair=WETH/USDC via uniswap_v3).
- **Base PASS rate**: 36.7% (was 18.5% in R39u; improvement may partly reflect market conditions).

### 2.4 Profit classification (unchanged from R39u)

| Поле | Значення |
|------|----------|
| profit_realism_status | ROUNDTRIP_NOT_PROFITABLE |
| profit_is_diagnostic | false |
| profit_truth_source | ROUNDTRIP_CANONICAL |
| measured_economics.available | true |
| best_net_pnl_bps | -8.74 |

## 3. CI Gates

| Gate | Результат |
|------|-----------|
| pytest | 2495 passed, 5 skipped |
| check_repo_safety | PASS (0 warnings, 20/20) |
| ci_full_pipeline | ALL REQUIRED GATES PASSED |
| M4 offline profit strict | PASS |
| 20-min scan | 61 runs complete |
| inspect_rolling | WARN_QUALITY (arb primary) |

## 4. Наступні кроки

1. **Base rq=0**: OE economics gate rejects USDC/DAI (NET_PROFIT_TOO_LOW) — stable pairs can't pass $0.50 minimum. Потрібно або знизити поріг для stablecoins, або додати truth-lane bypass.
2. **Base FAIL rate 63%**: coverage gate stricter than current contour can satisfy.
3. **Flashblocks**: sim_success_count=0, tx_status_reachable=false — external blocker.
4. **Arb gap -25.4 bps**: stable but not profitable.

## 5. Змінені файли

| Файл | Зміна |
|------|-------|
| strategy/jobs/run_scan_real.py | +22 lines: truth-lane reranking (measured economics priority for top_opportunities) |
| tests/unit/test_roundtrip_canonical_gating.py | +93 lines: TestTruthLaneReranking (5 tests) |
| tests/unit/test_run_scan_real_purity.py | max_lines 1850→1875 |
