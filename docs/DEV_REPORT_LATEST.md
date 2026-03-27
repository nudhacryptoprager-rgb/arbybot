# DEV_REPORT_LATEST.md — R39w

## 0.1 Мета-інформація

| Поле | Значення |
|------|----------|
| session_id | R39w |
| session_date | 2026-03-27 |
| branch | split/code |
| run_timestamp | 2026-03-27T15:11:17Z |
| rolling_run_dir | ci_m5_gate_arbitrum_one_20260327_161054_167481 |
| docs_reread_confirmed | true |

## 0.2 Закриття сесії

| Поле | Значення |
|------|----------|
| session_goal | Repeatability-informed frontier promotion: sweep_best_pair must use per_pair_repeatability evidence instead of single-best-PnL, so USDC/DAI replaces WETH/USDC as Base chain-best pair |
| goal_status | REACHED |
| close_allowed | true |
| blocker_status_before | Base frontier/promotion logic uses single-best sweep PnL: WETH/USDC (gap=4.88, median=49.98) held sweep_best_pair despite USDC/DAI (median=8.77) and USDC/USDT (median=9.22) being significantly more stable |
| blocker_status_after | _apply_repeatability_frontier() now overrides sweep_best_pair when per_pair_repeatability shows a stable pair has 2x+ better median gap. Base frontier_pair=USDC/DAI, WETH/USDC preserved as sweep_benchmark_pair |
| evidence_session_run_dirs | ci_m5_gate_base_20260327_161118_002010, ci_m5_gate_arbitrum_one_20260327_161054_167481 (56 total runs: 28 arb + 28 base) |
| remaining_blockers | Base rq=0 (OE economics gate rejects stable pairs); flashblocks sim_success_count=0; arb gap -6.9 bps |

## 1. Що зроблено

### 1.1 Repeatability-informed frontier promotion (long_scan_summary.py)

- Нова функція `_apply_repeatability_frontier(per_chain)` в `strategy/long_scan_summary.py`.
- Для кожного chain перевіряє `_per_pair_repeat` дані (accumulated across runs).
- Якщо pair з найкращим (найнижчим) `median_gap_to_zero_bps` відрізняється від поточного `sweep_best_pair`, і поточний pair має ≥2x гірший median gap → promote.
- Promoted pair стає `sweep_best_pair` з `source=repeatability`.
- Оригінальний pair зберігається як `sweep_benchmark_pair` для diagnostic visibility.
- Constants: `_REPEAT_MIN_SAMPLES=3`, `_REPEAT_PROMOTION_GAP_RATIO=2.0`.
- Schema bump: `v1.15 → v1.16`.

### 1.2 Frontier ranking enrichment

- Нові поля в `frontier_ranking`: `frontier_pair_source`, `sweep_benchmark_pair`.
- Дозволяють операторам бачити чи frontier_pair прийшов з sweep_pnl чи repeatability evidence.

### 1.3 Regression tests (test_repeatability_frontier.py)

9 нових тестів у класі `TestRepeatabilityFrontierPromotion`:
- `test_stable_pair_promoted_over_weth_usdc` — USDC/DAI (gap=8.5) replaces WETH/USDC (gap=50.0)
- `test_benchmark_pair_preserved_in_diagnostics` — WETH/USDC залишається як sweep_benchmark_pair
- `test_no_promotion_when_current_pair_is_best` — no change if current pair is already repeatability-best
- `test_no_promotion_below_ratio_threshold` — no promotion when gap ratio < 2.0x
- `test_promotion_when_current_pair_has_no_repeatability_data` — promote when current has < 3 samples
- `test_insufficient_samples_skips_promotion` — skip when all pairs have < 3 samples
- `test_empty_per_pair_repeat_skips` — no crash on empty data
- `test_frontier_ranking_surfaces_promoted_pair` — integration test via build_summary
- `test_promotion_breakeven_alternative` — promote when best alternative has gap ≤ 0

## 2. Доказова база (fresh 20-min scan)

### 2.1 Scan overview

| Метрика | Значення |
|---------|----------|
| total_runs | 56 (28 arb + 28 base) |
| wall_seconds | 1203 |
| arb PASS | 28/28 (100%) |
| base PASS | 28/28 (100%) |
| base FAIL | 0/28 (0%) |

### 2.2 Base sweep_best_pair — BEFORE vs AFTER

**BEFORE (R39v):**

| Поле | Значення |
|------|----------|
| sweep_best_pair | WETH/USDC |
| source | sweep_pnl (single best PnL run) |
| sweep_best_net_pnl_bps | -4.88 |
| WETH/USDC median_gap | 49.975 bps |
| USDC/DAI median_gap | 8.765 bps |
| USDC/USDT median_gap | 9.22 bps |

**AFTER (R39w):**

| Поле | Значення |
|------|----------|
| sweep_best_pair | USDC/DAI |
| source | repeatability |
| sweep_benchmark_pair | WETH/USDC (diagnostic) |
| frontier_median_gap_bps | 8.67 |
| WETH/USDC median_gap | 45.61 bps |
| USDC/DAI median_gap | 8.67 bps |
| USDC/USDT median_gap | 8.69 bps |

### 2.3 Frontier ranking (fresh)

| Chain | Rank | frontier_pair | source | median_gap | sweep_pnl | benchmark |
|-------|------|--------------|--------|------------|-----------|-----------|
| base | 1 | USDC/DAI | repeatability | 8.67 | -6.40 | WETH/USDC |
| arbitrum_one | 2 | WBTC/USDC | repeatability | 25.49 | -6.88 | WBTC/USDC |

### 2.4 Key observations

- **`sweep_best_pair` for Base is now `USDC/DAI`** — driven by repeatability evidence (median_gap=8.67 vs WETH/USDC=45.61, ratio=5.3x).
- **WETH/USDC preserved as `sweep_benchmark_pair`** — visible in frontier_ranking and per_chain diagnostics.
- **Base PASS rate: 100%** (28/28) — was 36.7% in R39v. Partly market/timing.
- **Stable contour dominates**: USDC/DAI (8.67) and USDC/USDT (8.69) are the best pairs on Base by repeatability.

## 3. CI Gates

| Gate | Результат |
|------|-----------|
| pytest | 2504 passed, 5 skipped |
| check_repo_safety | PASS (0 warnings, 20/20) |
| ci_full_pipeline | ALL REQUIRED GATES PASSED |
| M4 offline profit strict | PASS |
| 20-min scan | 56 runs complete, 0 failures |
| inspect_rolling | WARN_QUALITY (arb primary) |

## 4. Наступні кроки

1. **Base rq=0**: OE economics gate rejects USDC/DAI (NET_PROFIT_TOO_LOW) — stable pairs can't clear $0.50 minimum. Need lower threshold for stablecoins or truth-lane bypass for measured-viable routes.
2. **Flashblocks**: sim_success_count=0, tx_status_reachable=false — external blocker.
3. **Arb gap -6.9 bps**: stable primary chain, not yet profitable.

## 5. Змінені файли

| Файл | Зміна |
|------|-------|
| strategy/long_scan_summary.py | +55 lines: _apply_repeatability_frontier(), frontier_pair_source/sweep_benchmark_pair in ranking, schema v1.16 |
| tests/unit/test_repeatability_frontier.py | NEW: 9 regression tests for repeatability promotion |
| tests/unit/test_start.py | Schema version v1.15 → v1.16 (3 assertions) |
| tests/unit/test_signal_funnel.py | Schema version v1.15 → v1.16 (1 assertion) |
| docs/status/Status_M5_0.md | Schema header v1.15 → v1.16, removed version strings from body per DOCS_POLICY |
