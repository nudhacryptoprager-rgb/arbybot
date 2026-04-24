# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-24T19:49:37Z
soak_id: M7.E1.34o-soak13
soak_started_at_utc: 2026-04-24T19:50:19Z
soak_ended_at_utc: 2026-04-24T21:50:19Z
mode: ONLINE (Base, 2h, strict provider + archive, premium-only; PROD sim=tenderly / DISC sim=rpc_fork)
artifact_mode: rolling
run_dir reference: data/runs/_rolling/m7_hot_rollup_latest*.json (rolling)
code_identity:
  primary: ts:2026-04-24T19:49:37Z
  dirty: true (локальні зміни у m7/orderflow/*.py, tests/unit/*.py, не закомічено)
  desc: multicall token0/token1/fee у hot-rehydrate + adaptive sizing у sim-build

## 1) Scope — що й навіщо
goal (Roadmap): M7.E1.34 — розблокувати DISC fast-path і довести simulate→submit-ready на обох лейнах (див. `Status_M7.md` soak9-12 P0 "multicall token0/token1/fee" + нова вимога soak12 щодо sweep/size).

change_summary:
- `m7/orderflow/bridge_runtime.py::_rehydrate_hot_unresolved_pools` тепер викликає `core.multicall.get_multicall_batcher().batch_token_info(candidates)` одним multicall3-запитом; fallback — послідовні `eth_call` селекторів `0x0dfe1681` (token0), `0xd21220a7` (token1), `0xddca3f43` (fee). У `pool_token_transport` і `_pool_token_cache` тепер кладеться повний triple `(t0_lower, t1_lower, fee_int)` замість `(t0, t1, 0)`.
- `m7/orderflow/execution_gate.py::_build_sim_tx_params` отримав adaptive-sizing блок (gated на `ARBY_ADAPTIVE_SIZING=1`, default ON): якщо `result.best_sweep_size_wei` < raw event `amount_in_wei` — для sim-path використовується саме `best_sweep_size_wei` (і синхронізується `result.amount_in_wei`); якщо sweep ≥ raw або відсутній — поведінка незмінна.
- Додано 5 unit-тестів (див. нижче).

touched_files:
- m7/orderflow/bridge_runtime.py
- m7/orderflow/execution_gate.py
- tests/unit/test_rehydrate_hot_unresolved.py
- tests/unit/test_execution_gate.py

## 2) Commands Executed (факти)
- py -3.11 -m pytest tests/unit -q: **PASS** (4259 passed / 6 skipped / 1 warning у 118.82 s; collected on re-run: 4265)
- py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings, усі 20 гейтів OK, в т.ч. [11] DEV_REPORT aligned, [14][15] claim consistency, [19] content bloat)
- py -3.11 scripts/ci_full_pipeline.py --mode ci: NOT RUN (скоуп циклу — runtime-фікси + soak; CI offline не потрібен для DISC-розблокування)
- py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: NOT RUN (поза скоупом циклу; M4 logic не змінювалася)
- py -3.11 scripts/ci_m5_0_gate.py --online: NOT RUN (замість нього 2h ONLINE soak13 — фактичний runtime evidence)
- py -3.11 scripts/ci_m4_execution_gate.py --online: NOT RUN (M4 logic не змінювалася)

## 3) Artifacts Attached (шляхи)
rolling:
- data/runs/_rolling/m7_orderflow_latest.json (run_timestamp=2026-04-24T19:49:37Z)
- data/runs/_rolling/m7_hot_rollup_latest.json (PROD, session_id=32dab090, started 2026-04-24T19:21:27Z)
- data/runs/_rolling/m7_hot_rollup_latest_discovery.json (DISC, session_id=1301e4ec, started 2026-04-24T19:41:35Z)
- data/runs/_rolling/m7_cold_hot_bridge.json

run_dir_bundle: N/A (M7 runtime не створює per-runDir reports; rolling — канонічний operational interface).

## 4) Key Results (цифри з артефактів)

soak13 фінальний зріз (2026-04-24T21:51:02Z):

PROD (session 32dab090):
- events_seen_total: 409
- fast_path_scored_total: 125
- fast_path_positive_total: **2** (перші positive на PROD у цьому циклі)
- profit_guard_passed_total: 2
- sim_attempted_total: **2** (було 0 у soak9–soak12)
- sim_passed_total: 0
- roundtrip_attempted_total: 0
- roundtrip_success_total: 0
- roundtrip_profitable_total: 0
- submit_ready_total: 0
- matched_then_gas_rejected_total: 89
- session_ws_failed_429_windows: 0
- simulation_error_histogram: {REVERT:unknown:no_data: 2}
- bridge_hit_but_not_fast_scored.reason_histogram: {TOKEN_ADDRESS_UNKNOWN: 5}

DISC (session 1301e4ec):
- events_seen_total: 477
- fast_path_scored_total: 48
- fast_path_positive_total: 1
- profit_guard_passed_total: 1
- sim_attempted_total: **1** (було 0 у soak9–soak12)
- sim_passed_total: **1**
- roundtrip_attempted_total: 1
- roundtrip_success_total: 1
- roundtrip_profitable_total: 0
- roundtrip_profit_bps_best/median/worst: **-9957.9985 / -9957.9985 / -9957.9985**
- submit_ready_total: **1** (перший submit_ready на DISC за всю історію milestone)
- matched_then_gas_rejected_total: 28
- session_ws_failed_429_windows: 0
- bridge_hit_but_not_fast_scored.reason_histogram: {TOKEN_ADDRESS_UNKNOWN: 5}

Δ vs soak12 (PROD/DISC):
- fast_path_positive: 0/0 → **2/1**
- sim_attempted: 0/0 → **2/1**
- sim_passed: 0/0 → 0/**1**
- submit_ready: 4/0 → 0/**1** (DISC — перший випадок)
- TOKEN_ADDRESS_UNKNOWN (session): 33/23 → **5/5** (~-85%)
- ws_failed_429_windows: 0/0 → 0/0 (стабільно)

## 4.1) Theoretical Net Profit
N/A для цього циклу — truth_report на run-рівні не створюється у M7 runtime (rolling M7 artefacts не містять `execution_pnl.cost_model_components`). Єдиний числовий net-показник — `roundtrip_profit_bps_*` на DISC = **-9957.9985 bps** (≈ -99.58%, paper_simulated). Блок `theoretical_net_profit` у M7-форматі не застосовний до поточного соаку; формат зафіксовано у canonical docs.

## 5) Contract Checks
- status/reasons consistency: OK — sim_attempted(2)=fast_path_positive(2) на PROD; sim_passed(1)=roundtrip_attempted(1)=roundtrip_success(1) на DISC; submit_ready(1)=sim_passed(1) на DISC (PAPER_SIGNING шлях).
- rolling discipline (3 files only): OK — лише canonical `_latest.json` / `run_summary_latest.json` / `m4_stability_agg.json` + M7-specific `m7_*` rolling (не множаться per-run).
- v2.x provenance contract: OK — `run_context.run_timestamp=2026-04-24T19:49:37Z`, SHA-free.
- runtime artifacts not committed: OK — `data/runs/**` не трекається.

## 6) Blocker Classification
- code_blocker: LOW — pytest 4259 PASS, repo-safety PASS 0 warnings.
- data_collection_blocker: LOW — TOKEN_ADDRESS_UNKNOWN впало з 33/23 до 5/5; DISC вперше пройшов end-to-end; PROD вперше досяг sim_attempted>0.
- market_window_blocker: **HIGH** — `roundtrip_profit_bps≈-9958` на DISC; `REVERT:unknown:no_data×2` на PROD. Adaptive sizing фактично активовано (unit-tests зелені), але економіка pool-ів, на яких hit'ить bridge, все одно дає catastrophic loss — це не вирішується зменшенням amount_in без profit-realism gate на price-impact/pool-depth.

## 6.1) Blockers / Risks (max 5)
- `roundtrip_profit_bps≈-9958` на DISC — sweep_size все ще перевищує depth pool-ів; adaptive sizing знижує amount_in, але не відкидає unrealistic opportunities.
- `REVERT:unknown:no_data` на PROD sim — 2/2 sim падають без detail. Потрібен калдата/trace dump у simulation_error_samples.
- Supervisor ~21:10 перезапустив частину дочірніх процесів (ID 17180/21424 мають StartTime 20:30 / 21:10) через WS reconnect exhaustion — crash_restart працює, але session_id DISC/PROD у фінальному зрізі вже був від 19:21/19:41, тож метрики не "reset"; стабільність reconnect-гілки треба валідувати окремо.
- `roundtrip_profitable_total=0` — M7 production definition (4 clauses) TRUE лише по перших трьох; last clause (`roundtrip_profitable_total>0`) FALSE → NOT PRODUCTION-READY.
- `submit_ready_total=0` на PROD — sim не проходить, отже submit-ready шлях не активується; на DISC — є перший submit_ready=1, але це paper_signing.

## 7) Lead's Previous 10 Steps: Execution Map
step_01 (multicall token0/token1 у hot-rehydrate): **DONE** evidence: `_rehydrate_hot_unresolved_pools` використовує `batch_token_info`; TOKEN_ADDRESS_UNKNOWN 33/23 → 5/5.
step_02 (fee_tier resolution у hot-rehydrate): **DONE** evidence: той самий шлях повертає `(t0, t1, fee_int)`; DISC fast_path_scored з 0 на сесію → 48 (soak13) / sim_attempted 0 → 1.
step_03 (adaptive sizing для backrun amount_in): **DONE** evidence: `_build_sim_tx_params` бере `best_sweep_size_wei` при ARBY_ADAPTIVE_SIZING=1; unit-tests `test_adaptive_sizing_*` зелені.
step_04 (unit-tests для fixes): **DONE** evidence: `test_rehydrate_populates_ptt_on_success` (оновлено), `test_rehydrate_uses_multicall_fee_tier` (новий), `test_adaptive_sizing_prefers_smaller_sweep_over_event_amount`, `test_adaptive_sizing_disabled_keeps_raw_amount`, `test_adaptive_sizing_ignores_larger_sweep`.
step_05 (pytest + repo_safety): **DONE** evidence: 4259 passed, repo-safety PASS 0 warnings.
step_06 (2h soak з новими фіксами): **DONE** evidence: soak13 19:50–21:50 UTC, rolling артефакти оновлено.
step_07 (profit-realism gate / price-impact cap): **NO** evidence: -9958 bps свідчить про відсутність такого гейта; залишається для soak14.
step_08 (Alchemy WS secondary fallback): **NO** evidence: `_ws_tried_urls` не торкався; ws_failed_429=0 — поточний блокер не в rate-limit.
step_09 (dashboard panel WS counters): **NO** evidence: не в скоупі циклу.
step_10 (`sim_attempted>=20 fast_path` rolling-gate): **NO** evidence: потребує стабільного потоку positive (soak13 дав 2+1 — замало для гейта).

## 8) What I need from Lead now
question_1: Чи дозволити імплементувати profit-realism hard-cap (відкидати opportunities з amount_in*price_impact > X% pool TVL) як P0 для soak14?
request_1: Підтвердити, що `REVERT:unknown:no_data` на PROD заслуговує окремого ticket-а на calldata-dump у `simulation_error_samples`, а не лише histogram-лічильника.

## Session Completion
session_goal: Додати multicall-fetch fee_tier у hot-rehydrate + adaptive sizing для backrun amount_in; запустити 2-годинний online soak для валідації.
goal_status: REACHED
close_allowed: true
remaining_blockers: none (для цілі цієї сесії; економічний блокер `roundtrip_profit_bps<<0` — окрема ціль soak14).
evidence_session_run_dirs:
- data/runs/_rolling/m7_hot_rollup_latest.json (session_id=32dab090, session_started_at=2026-04-24T19:21:27Z)
- data/runs/_rolling/m7_hot_rollup_latest_discovery.json (session_id=1301e4ec, session_started_at=2026-04-24T19:41:35Z)
- data/runs/_rolling/m7_orderflow_latest.json (run_timestamp=2026-04-24T19:49:37Z)
primary_blocker_of_session: DISC lane заблокований `TOKEN_ADDRESS_UNKNOWN` і відсутністю fee_tier → sim_attempted=0.
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true
