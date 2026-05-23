# DEV REPORT LATEST — M9 Smoke23: First ALL-PASS 15-min Soak (5/5 runtime_gates PASS, P0 RPC Blocker RESOLVED)

**mode**: M9_SMOKE23_15MIN_SOAK_ALL_PASS
**session_date**: 2026-05-23
**schema_family**: m9_graph_arb
**schema_revision**: m9.1
**run_label**: smoke23 (15-min real-RPC soak, publicnode.com, prequote-min-bps=-9999 bypass, dynamic_sizes)
**execution_enabled**: false
**kill_switch_active**: true

---

## Smoke23 Summary

**goal**: Implement 5 GPT infra fixes → validate with clean 15-min proof-run; gate: qsr≥0.8, mc_rate≥0.9, unverified=0, data_completeness≥0.98, quote_revert_rate<0.05.

**result**: ALL 5 runtime_gates PASS — first ever `all_pass=True`. qsr=0.9742 ✅, mc_rate=1.0 ✅, data_completeness=1.0 ✅, unverified=0 ✅, quote_revert_rate=0.0 ✅. Zero http errors (429/408/5xx). P0 multicall_success_rate blocker RESOLVED (publicnode.com). Scheduler starvation bug fixed. 5883/5883 unit tests pass.

### Run stats
- elapsed=900.7s (full 15 min ✅, duration_fulfilled=True)
- sweeps=452, cycles_found=2248, cycles_quoteable=2190, positive_gross=0 (flat market)
- sizes_usd=[100, 250, 500] ✅ (from config `scan_params`)
- dynamic_size_selected_count=1321 (selection_rate=0.5876, ~59%)

### runtime_gates — ALL PASS (first time)
| gate | value | threshold | pass |
|---|---|---|---|
| multicall_success_rate | 1.0 | 0.90 | ✅ |
| data_completeness | 1.0 | 0.98 | ✅ |
| unverified_active_routes | 0 | 0 | ✅ |
| qsr | 0.9742 | 0.80 | ✅ |
| quote_revert_rate | 0.0 | <0.05 | ✅ |
| **all_pass** | **true** | | ✅ |

### Infra telemetry (zero errors)
- `http_429_count=0` (was 44 artifact / 715 raw in smoke20)
- `http_408_count=0` (was many in smoke21e)
- `http_5xx_count=0`
- `actual_http_calls=4645`
- `rpc_provider=publicnode`

### Dynamic-size telemetry
- `dynamic_size_enabled=true` ✅
- `dynamic_size_selected_count=1321` (smoke20: 224)
- `dynamic_size_selection_rate=0.5876` (~59%)
- `sizes_usd_source=config.scan_params` ✅

### Prequote funnel
- `prequote_cycles_skipped=12` (0.53% across 452 sweeps — non-V3/zero-price pools only)
- `prequote_min_bps=-9999` (bypass for smoke validation)

### Rejects
- `NEGATIVE_GROSS=2190` (97.4%, flat market — expected)
- `CYCLE_QUOTE_FAILED=58` (2.6% — vs 12.6% in smoke20)

### Fixes validated
1. ✅ **CONFIG_ERROR gate**: `--no-prequote` + duration≥5 → EXIT_CONFIG_ERROR
2. ✅ **http_408/500/5xx telemetry**: all counters present and correct (all zero)
3. ✅ **5xx circuit breaker**: `ProviderThrottle` tracks + soft-breaks on HTTP 5xx
4. ✅ **Scheduler prequote-skip demotion**: `record_prequote_skips()` prevents hot-queue starvation
5. ✅ **RPC fix**: publicnode.com → no rate limiting (was dRPC free-tier 429-storm)

### Verdict
- ✅ **FIRST ALL-PASS RUN** — all 5 runtime_gates satisfied simultaneously
- ✅ **P0 multicall blocker RESOLVED** — mc_rate=1.0
- ✅ **5883 unit tests pass** (including new `test_5xx_opens_breaker`)
- ✅ **Repo safety PASS** (2 pre-existing doc-bloat warnings, unrelated)
- 1/3 consecutive all_pass runs achieved for M8→M9 bridge unlock

### Artifacts
- `data/runs/_rolling/m9_graph_latest.json`
- `data/tmp/smoke23_log.txt`

---

## Session Completion

session_goal: Implement 5 GPT infra fixes (CONFIG_ERROR gate, 5xx telemetry, 5xx circuit-breaker, scheduler prequote-skip demotion, test fix) → run clean 15-min proof-run → all_pass=True.
goal_status: REACHED
close_allowed: true
remaining_blockers: Need 2 more consecutive all_pass runs (smoke24, smoke25) for M8→M9 bridge unlock.
evidence_session_run_dirs: data/tmp/smoke23_log.txt (rolling artifact: data/runs/_rolling/m9_graph_latest.json)
primary_blocker_of_session: multicall_success_rate < 0.90 (free-tier dRPC 429-storm) + scheduler starvation
blocker_status_before: ACTIVE
blocker_status_after: RESOLVED
docs_reread_confirmed: true

## Code Changes This Session

| File | Change |
|------|--------|
| `m9/graph_arb/cycle_scheduler.py` | Added `record_prequote_skips()` — demotes prequote-skipped cycles to prevent hot-queue starvation |
| `m9/graph_arb/runner.py` | Collects `_prequote_skipped_ids` per sweep; calls `record_prequote_skips()` after `record_results()` |
| `m9/graph_arb/artifacts.py` | Added `http_408_count`, `http_500_count`, `http_5xx_count` to `infra_telemetry` |
| `core/provider_throttle.py` | Added `total_5xx`, `consec_failures_5xx`; new 5xx branch: `500<=status<600` opens soft breaker |
| `m9/graph_arb/runner.py` | CONFIG_ERROR gate: `--no-prequote` + duration≥5min + !allow_no_prequote_soak → EXIT_CONFIG_ERROR |
| `tests/unit/test_m9_runner_config_gates.py` | Added 3 tests for CONFIG_ERROR gate (all passing) |
| `tests/unit/test_e1_59_provider_throttle.py` | Split `test_other_error_does_not_open_breaker` into `test_5xx_opens_breaker` (new) + updated existing (uses 404 not 500) |

## Previous Report Reference
smoke20: dynamic sizes validated, qsr=0.8738 PASS, multicall_success_rate=0.8716 FAIL (dRPC 429-storm), all_pass=false

