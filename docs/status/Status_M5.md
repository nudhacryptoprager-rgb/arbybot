# Milestone 5 — Production small

> **Оновлено**: 2026-02-05 18:30 UTC  
> **SHA**: `0c84e19`  
> **Статус**: ⏳ В роботі

---

## Deliverables (Roadmap)

- Daily reporting artifact (daily_report_*.json) with schema_version and run coverage
- Stable definitions: win_rate, net_pnl_usdc, tail_losses, top_reject_reasons
- Auto-sizing rules (min/max/clamp and back-off/restore heuristics)
- Transparent health metrics (rpc/dex/system)
- CI validation for M5 (ci_m5_gate)

DoD-commands (канонічні команди)

- Двокрокова — коли вже є runDir:
  - `python -m scripts.ci_m5_gate --run-dir data/runs/<runDir>`

- Однокрокова (runner) — scan + generate + validate:
  - `python -m scripts.ci_m5_gate --online --config config/real_minimal.yaml --cycles 1 --strict --gas-usd-estimate 0.10`

- Юніт-тести:
  - `python -m pytest tests/unit -q`

Execution policy

DO NOT enable execution yet — execution remains disabled until a validated cost model and execution engine exist.

Daily report artifact

We add a new artifact: `daily_report_<YYYYMMDD>.json`.
Minimal fields (schema_version v1):

- `schema_version`: string (e.g. "m5:daily:v1")
- `run_id`: string or list of run directories included
- `period`: {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
- `date`: YYYY-MM-DD (report date)
- `runs_included`: int
- `net_pnl_usdc`: number (net pnl for paper trades in USDC)
- `win_rate`: number (fraction 0..1) — defined for M5 as: paper trades/opportunities that passed gates and would have executed (execution disabled)
- Note: For clarity these are *paper* metrics in M5. The canonical field names produced by the generator will be `paper_net_pnl_usdc` and `paper_win_rate` and `pnl_mode: "paper"`.
 - Note: For clarity these are *paper* metrics in M5. The canonical field names produced by the generator will be `paper_net_pnl_usdc` and `paper_win_rate` and `pnl_mode: "paper"`.
- `trades_count`: int

Important: `trades_count` is a legacy name kept for backwards compatibility and is equivalent to `checks_count` produced by the generator. This field is deprecated and consumers should prefer `checks_count`.
- `tail_losses`: list of top-k worst trade outcomes (by pnl)
- `top_reject_reasons`: list of {reason, count}
- `health`: {rpc: {...}, dex: {...}, system: {...}}

Additional recommended fields (required for M5 progression):
- `autosize`: {`new_size_usd`, `reason`, `cooldown_remaining`} — auto-size decisions must be surfaced in the report even if only as metadata.
- `top_opportunities`: list of top-5 opportunity summaries: {`spread_pct`, `size_usd`, `confidence`, `source`} — should be derived from `truth_report.spread_signals` or from `scan.quotes` when signals absent.

Cost model (мінімальна газова модель)

Для M5 початкова cost model — gas-only і явно задана в config або CLI.

- У config: `gas_usd_estimate: 0.10` (приклад).
- CLI: `--gas-usd-estimate 0.10`.
- Env: `ARBY_GAS_USD_ESTIMATE=0.10`.

```
paper_net_pnl_usdc = gross_spread_usd - gas_usd_estimate - slippage_usd_estimate
```

Коли `gas_usd_estimate` задано, репорт ПОВИНЕН мати `pnl_available: true` і `pnl_reason: null`.

Важливо: `daily_report.paper_net_pnl_usdc` — це окрема paper-оцінка, НЕ з truth_report. У truth_report `cost_model_available` може бути `false`, а у daily_report pnl_available=true (бо daily застосовує gas-only модель незалежно).

Price provenance (on-chain доказовість ціни)

Для M5 quotes ПОВИННІ містити:
- `pool_address` — адреса пулу (для v3).
- `block_number` — номер блоку.
- (рекомендовано) `tick` або `sqrtPriceX96` для v3 пулів.

Це підтверджує, що ціна прийшла з on-chain стану.

Golden artifact policy

- Maintain golden `daily_report_*.json` files under `docs/artifacts/` for regression testing.
- Update golden only when the `schema_version` changes or a deliberate addition of fields is accepted by the team. Do NOT auto-update golden from the latest run unless schema changed.

Negative tests (required):
- `current_block` mismatch (already present)
- `quotes_total` mismatch (unit test added)
- `rejects_total` mismatch (unit test added)

DoD additions

- The daily report MUST include provenance fields: `source_run_dir` and `artifacts` with explicit paths: `scan_path`, `truth_report_path`, `reject_histogram_path`.
- The generator will write default reports under `runDir/reports/daily_report_*.json` to ensure reproducibility.

Definitions (short)

- `win_rate`: for M5 initial phase, count paper trades (opportunities) that pass gates divided by total opportunities considered; execution disabled so this is paper win-rate.
- `net_pnl_usdc`: net pnl estimated for paper trades in USDC terms (consistent currency for M5).

Validation & CI

- `ci_m5_gate.py` will validate daily report schema and consistency with artifacts (quotes_total, total_rejects, current_block) when artifact paths present.
- `ci_m5_gate.py` will also ensure `paper_win_rate` in [0,1], `top_reject_reasons` present (or explicit empty explanation), and health keys (`rpc`,`dex`,`system`) present.
- `tail_losses`: for example the top-5 worst trade outcomes for the period, by pnl.
- `reject reasons`: include origin stage (normalize: normalize_price|sanity_check|execution|rpc)

Auto-size (initial rules)

- `min_size` and `max_size` must be configured.
- On high-impact/slippage events: if `ticks_crossed > T1` or `slippage_bps > S1` then `size *= 0.5` (clamped to `>= min_size`).
- Restore rule: if 3 cycles in a row with low slippage/ticks, `size *= 1.2` (clamped to `<= max_size`).

Health score (transparent components)

- `rpc_health`: {`success_rate`, `p50_latency_ms`, `ws_connected_rate`}
- `dex_health`: {`quote_fetch_rate`, `revert_rate`}
- `system_health`: {`gate_pass_rate`, `artifacts_ok_rate`}

Retention & golden artifacts

- Preserve 1–2 golden `daily_report_*.json` files under `docs/artifacts/` for regressions.
- Document retention: add `scripts/clean_runs.py` (or manual instruction) to remove old runDir(s).

M5_0 closure

M5_0 closed on SHA: `e56cfd5`. Close only if:

- `scripts/ci_m5_0_gate.py --online --strict` passes
- `pytest -q` green

---

## Статус виконання M5

| # | Задача | Статус |
|---|--------|--------|
| 1 | daily_report generator | ✅ |
| 2 | gas-only cost model у config | ✅ |
| 3 | pool_address у quotes | ✅ |
| 4 | tick/sqrtPriceX96 структура | ✅ (placeholder) |
| 5 | top_opportunities policy | ✅ |
| 6 | autosize завжди об'єкт | ✅ |
| 7 | strict режим у gate | ✅ |
| 8 | негативні тести (3 шт) | ✅ |
| 9 | paper PnL документація | ✅ |
| 10 | slot0() для tick | ⏳ Наступний крок |

## Останній прогін

**RESULT: PASS + data\runs\manual_run_20260205_190141**

## Юніт-тести

```
443 passed, 5 subtests passed
```

## Наступні кроки

- Реалізувати RPC call до `slot0()` для заповнення `tick` і `sqrtPriceX96`
- Додати генерацію `spread_signals` у truth_report
- Заповнити `top_opportunities` з реальних signals

## SHA закриття M5

_(заповнюється при закритті milestone)_

---

Next: Milestone 6
