# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-27T09:31:31Z
run_id: data/runs/_rolling (rolling artifact; M8+M8.1+M9 pipeline soak8)
mode: ONLINE
artifact_mode: rolling
config: config/exotic_base_anchor.yaml
code_identity:
  primary: ts:2026-05-27T09:31:31Z
  dirty: true
  desc: GPT steps 7+9 implemented; soak8 run (5000 blocks M8, 284 sweeps M9); 5977 tests pass

## 1) Scope
goal (Roadmap): M9 — досягти positive_cycles_with_m8_pool > 0 через raw_http+dynamic-sizes; CI gate exit=0
goal_status: IN_PROGRESS
change_summary:
  - Step 7: m8_context_token_pool_breakdown в bridge_source_metrics (per-token base route count)
  - Step 9: cycle_origin поле в top_cycles entries ("m8" або "base")
  - Tests: TestCycleOriginAnnotation (4) + TestM8ContextTokenPoolBreakdown (2) — 5977 passed
  - M8 soak8: 1270 подій (5000 blocks back, 10 хв), m8_context_tokens=['VIRTUAL']
  - M8.1: qsr=0.9465, passes=318, near_miss=50
  - Bridge: graph_ready_from_m8=15, graph_ready_total=125
  - M9 soak8: 284 sweeps, 1411 cycles, qsr=0.961, 32 positive gross
  - CI gate strict-bridge: PASS EXIT 0, STRATEGIC_WARNING (positive_with_m8=0)
  - check_repo_safety.py: PASS

## 2) Runtime Claims

### M9 Scanner (soak8)
| Метрика | Значення |
|---------|---------|
| generated_at_utc | 2026-05-27T09:31:31Z |
| qsr | 0.961 |
| sweeps_completed | 284 |
| cycles_total | 1411 |
| cycles_positive_gross | 32 |
| best_cycle_gross_bps | 1.3455 |
| cycles_with_m8_pool | 92 |
| positive_cycles_with_m8_pool | 0 |
| m8_context_token_pool_breakdown | {VIRTUAL: 19} |
| top_cycles[0].cycle_origin | "base" |
| multicall_success_rate | 1.0 |
| all_pass | true |

### Bridge (soak8)
| Метрика | Значення |
|---------|---------|
| m8_new_pools_input | 24 |
| graph_ready_from_m8 | 15 |
| graph_ready_total | 125 |
| m8_stale | False |
| m8_1_stale | False |
| m8_context_tokens | ['VIRTUAL'] |
| m8_context_pool_count | 19 |
| m8_context_token_pool_breakdown | {VIRTUAL: 19} |

### CI Gate (ci_m9_productive_gate --strict-bridge)
| Метрика | Значення |
|---------|---------|
| exit_code | 0 |
| STRATEGIC_WARNING emitted | true |
| cycles_with_m8_pool | 92 (>0) PASS |

### check_repo_safety.py
| Метрика | Значення |
|---------|---------|
| exit_code | 0 |
| result | PASS (2 warnings -- Status_M7/M8 line count) |

### pytest
| Метрика | Значення |
|---------|---------|
| passed | 5977 |
| skipped | 6 |
| failed | 0 |

## 3) M8 Integration Analysis

### positive_cycles_with_m8_pool=0 — стратегічна проблема
- M8-sniped pools входять до активних циклів (92 cycles)
- Але жоден цикл не має positive gross spread через M8 пул
- Позитивні цикли (32 шт.) ідуть через base inventory (WETH/USDC/EURC), cycle_origin="base"
- best_cycle_net_bps=1.3455 — у базових маршрутах

### Нові поля (steps 7+9)
- m8_context_token_pool_breakdown: для кожного M8-context токена — кількість base inventory routes
  Поточний стан: {VIRTUAL: 19} — VIRTUAL має 19 base routes для arb
- cycle_origin: кожен top_cycle тепер має анотацію "m8" або "base"
  Поточний стан: всі positive cycles = "base" (M8 цикли не позитивні)

## 4) Chain Quality
chain: base
rpc: https://base-rpc.publicnode.com
chain_quality: NORMAL
multicall: success_rate=1.0

## 5) Open Issues / Blockers
- positive_cycles_with_m8_pool=0 -- НАСТУПНИЙ MILESTONE
- токен VIRTUAL має 19 base routes, але M8-new пули для VIRTUAL не знаходять arb spread
- economics_gate_status: PENDING

## Session Completion
session_goal: Завершити GPT review steps 7+9 (код + тести), запустити повний pipeline soak8
goal_status: IN_PROGRESS
close_allowed: false
remaining_blockers: positive_cycles_with_m8_pool=0 (наступний milestone не досягнутий)
evidence_session_run_dirs: data/runs/_rolling (m9_graph_latest.json ts=2026-05-27T09:31:31Z)