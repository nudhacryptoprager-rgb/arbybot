# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-27T08:20:00Z
run_id: data/runs/_rolling (rolling artifact; M8+M8.1+M9 online runs this session)
mode: ONLINE
artifact_mode: rolling
config: config/exotic_base_anchor.yaml
code_identity:
  primary: ts:2026-05-27T08:18:51Z
  dirty: false
  desc: M9 soak7 (raw_http+dynamic-sizes): cycles_with_m8_pool=98, qsr=0.9614, CI gate exit=0

## 1) Scope
goal (Roadmap): M9 — досягти cycles_with_m8_pool > 0 через правильний профіль raw_http+dynamic-sizes; CI gate exit=0
goal_status: IN_PROGRESS
change_summary:
  - Профіль M9: змінено з direct_http (4 workers) на raw_http (1 worker) + dynamic-sizes — виправлено qsr 0.001->0.9614
  - M8 soak7: 1298 подій за 601s (V4=1206, V2=79, V3=11, pancakeswap_v3=2), publicnode.com, blocks-back 5000
  - M8.1 anchor refresh: qsr=0.9465, passes=336, candidates=1122, elapsed=238s
  - Bridge rebuild: graph_ready_total=125, graph_ready_from_m8=18, m8_context_tokens=['VIRTUAL'], m8_context_pool_count=19
  - M9 soak7: 345 sweeps, 1710 cycles, 3 positive gross, cycles_with_m8_pool=98, elapsed=900s
  - CI gate (strict-bridge) exit=0: qsr=0.9614 >= 0.8, multicall_success_rate=1.0, all_pass=True
  - docs/status/Status_M9.md: milestone "M8 Cycle Participation" DONE

## 2) Runtime Claims

### M8 Sniper (soak — publicnode.com)
| Метрика | Значення |
|---------|---------|
| generated_at_utc | 2026-05-27T07:58:15Z |
| total_events | 1298 |
| elapsed_s | 601.5 |
| V4 events | 1206 |
| V2 events | 79 |
| V3 events | 11 |
| pancakeswap_v3 events | 2 |
| VIRTUAL in recent_events | true |
| status | ACTIVE |

### M8.1 Anchor Refresh
| Метрика | Значення |
|---------|---------|
| generated_at_utc | 2026-05-27T08:02:42Z |
| candidates | 1122 |
| passes | 336 |
| qsr | 0.9465 |
| elapsed_s | 238.4 |

### M9 Bridge
| Метрика | Значення |
|---------|---------|
| generated_at_utc | 2026-05-27T08:03:08Z |
| graph_ready_total | 125 |
| graph_ready_from_m8 | 18 |
| m8_context_token_count | 1 |
| m8_context_tokens | ['VIRTUAL'] |
| m8_context_pool_count | 19 |
| m8_stale | false |
| m8_1_stale | false |

### M9 Scanner (soak7 — raw_http+dynamic-sizes)
| Метрика | Значення |
|---------|---------|
| generated_at_utc | 2026-05-27T08:18:51Z |
| elapsed_s | 900.0 |
| sweeps_completed | 345 |
| cycles_found | 1710 |
| qsr | 0.9614 |
| cycles_with_m8_pool | 98 |
| positive_gross | 3 |
| multicall_success_rate | 1.0 |
| data_completeness | 1.0 |
| quote_rpc_error_rate | 0.0 |
| dynamic_size_selected | 993 |
| selection_rate | 0.5807 |
| all_pass | true |

### CI Gate (ci_m9_productive_gate --strict-bridge)
| Метрика | Значення |
|---------|---------|
| exit_code | 0 |
| multicall_success_rate | 1.0 (>=0.9) PASS |
| qsr | 0.9614 (>=0.8) PASS |
| runtime_gates.all_pass | true PASS |
| cycles_with_m8_pool | 98 (>0) PASS |
| toxic_route_rate | 0.3291 (<0.90) PASS |

## 3) Діагностика / Вирішені Проблеми

### Проблема soak6 -> soak7
- soak6: qsr=0.001, quote_rpc_error_rate=0.997 — V3 QuoterV2 eth_call повертав 0x для всіх публічних RPC
- Причина: direct_http backend з 4 workers — занадто великі amounts викликали revert QuoterV2
- Рішення: raw_http backend + 1 worker + --dynamic-sizes — V3 quotes тепер успішні
- Підтвердження: quote_rpc_error_rate=0.0 у soak7 (проти 0.997 у soak6)

### m8_context механізм (попередня сесія)
- bridge_builder.py: визначає non-anchor токени в нових M8 снайпер-подіях, знаходить їх базові пули
- runner.py: розширює _m8_pool_addrs контекстними пулами
- Результат: m8_context_tokens=['VIRTUAL'], m8_context_pool_count=19

## 4) Chain Quality
chain: base
rpc: https://base-rpc.publicnode.com
chain_quality: NORMAL
multicall: success_rate=1.0

## 5) Open Issues / Blockers

- cycles_with_m8_pool=98 ДОСЯГНУТО
- positive_cycles_with_m8_pool=0 — НАСТУПНИЙ MILESTONE
- economics_gate_status: PENDING

## Session Completion
session_goal: Запустити M8 soak + M8.1 + bridge + M9 (raw_http+dynamic-sizes) + CI gate exit=0; досягти cycles_with_m8_pool > 0
goal_status: IN_PROGRESS
close_allowed: false
remaining_blockers: positive_cycles_with_m8_pool=0 (наступний milestone не досягнутий)
evidence_session_run_dirs: data/runs/_rolling (m9_graph_latest.json ts=2026-05-27T08:18:51Z)
primary_blocker_of_session: qsr=0.001 через неправильний quote backend (direct_http+4workers)
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true