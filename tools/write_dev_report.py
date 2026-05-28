"""Write a clean DEV_REPORT_LATEST.md (UTF-8, <=250 lines, 1 session reference).
Updated: Session 17 - M9 pricing taxonomy validation (cycles_by_pricing_model non-null)
"""

# Session 17 data (Session 17c final — throttled run, gate PASS)
_SESSION = "17"
_TS = "2026-05-28T23:01:15Z"
_QSR = "0.9703"
_TOXIC = "0.2329"
_SWEEPS = "13"
_QUARANTINE = "94"
_HTTP_429 = "0"

import textwrap
content = textwrap.dedent(f"""\
# DEV REPORT

## 0) Meta
timestamp_utc: {_TS}
run_id: data/runs/_rolling (rolling artifact; Session {_SESSION})
mode: ONLINE (live BASE_RPC, productive-lane, no dynamic-sizes)
artifact_mode: rolling
config:
  - online M9: python -m m9.graph_arb.runner --productive-lane
code_identity:
  primary: ts:{_TS}
  dirty: true

## 1) Scope
goal: M9 productive gate PASS qsr>=0.80 + h429=0 + pricing taxonomy validated (Session {_SESSION})
goal_status: REACHED
  - M9 productive gate: PASS (exit 0)
    qsr={_QSR}, http_429_count={_HTTP_429}, sweeps={_SWEEPS}, all_pass=True
    multicall_success_rate=1.0, dynamic_size_enabled=True
  - cycles_by_pricing_model non-null: VERIFIED (RUNTIME_VALIDATED__ORTHOGONAL_PRICING_VISIBLE)
    clmm_ticks=2384, cpmm_xyk=139, solidly_volatile_xyk=692
  - Fix #3: aerodrome_stable in _VE33_ADAPTER_TYPES (pool_depth_probe.py)
  - Fix #4: stable vs volatile pricing model tests (6 new + parametrize)
  - Fix #5: _V2_FORK_FEE_BPS_MAP per-adapter fee lookup in pool_depth_probe.py
  - Fix #8: DodoPmmAdapter skeleton (disabled-by-default, POOL_DISABLED error)
  - Fix #9: RfqAdapter skeleton (disabled-by-default, POOL_DISABLED error)
  - Fix #2: ci_m9_productive_gate.py taxonomy INFO check added
  - RPC throttle: ARBY_RPC_RPS_LIMIT=8 eliminates 429-storm
    Sessions 17a/17b: h429=4445/4869; Session 17c: h429=0
  - CI full pipeline: ALL REQUIRED GATES PASSED (exit 0)

change_summary:
  - m9/graph_arb/pool_depth_probe.py: _VE33_ADAPTER_TYPES expanded + _V2_FORK_FEE_BPS_MAP
  - dex/adapters/dodo_pmm.py: new DodoPmmAdapter skeleton (enabled=False by default)
  - dex/adapters/rfq.py: new RfqAdapter skeleton (enabled=False by default)
  - scripts/ci_m9_productive_gate.py: cycles_by_pricing_model taxonomy INFO check
  - tests/unit/test_m9_pool_depth_probe.py: TestVe33AdapterTypes + fee map tests
  - tests/unit/test_dodo_pmm_adapter.py: 10 new tests for DODO PMM skeleton
  - tests/unit/test_rfq_adapter.py: 10 new tests for RFQ skeleton
  - docs/DEV_REPORT_LATEST.md: updated to Session {_SESSION}

touched_files:
  - m9/graph_arb/pool_depth_probe.py
  - dex/adapters/dodo_pmm.py
  - dex/adapters/rfq.py
  - scripts/ci_m9_productive_gate.py
  - tests/unit/test_m9_pool_depth_probe.py
  - tests/unit/test_cost_model_per_adapter.py
  - tests/unit/test_dodo_pmm_adapter.py
  - tests/unit/test_rfq_adapter.py
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

M9 Session {_SESSION}c (15-min, productive-lane, ARBY_RPC_RPS_LIMIT=8, --dynamic-sizes):
  BASE_RPC=https://base.publicnode.com ARBY_RPC_RPS_LIMIT=8 ARBY_RPC_RPS_BURST=8
  py -3.11 -u -m m9.graph_arb.runner --chain base --duration-minutes 15
    --config config/exotic_base_anchor.yaml --quote-backend raw_http
    --require-factory-verified --quote-workers 1 --productive-lane --dynamic-sizes
  result: sweeps={_SWEEPS}, qsr={_QSR} (PASS>=0.8), http_429={_HTTP_429}
  taxonomy: clmm_ticks=2384, cpmm_xyk=139, solidly_volatile_xyk=692

Gates:
  py -3.11 scripts/ci_m9_productive_gate.py  # PASS (exit 0) qsr={_QSR}
  py -3.11 scripts/ci_full_pipeline.py --mode ci  # ALL REQUIRED GATES PASSED
  py -3.11 scripts/check_repo_safety.py  # PASS (2 pre-existing warnings)

## 3) Artifacts
- data/runs/_rolling/m9_graph_latest.json  <- generated_at={_TS}
- data/quarantine/m9_pool_depth_quarantine.json  ({_QUARANTINE} entries)

## 4) Key Results

| Metric                        | Value      | Threshold | Status  |
|-------------------------------|:----------:|:---------:|:-------:|
| cycles_by_pricing_model       | 3 models   | non-null  | PASS    |
| solidly_volatile_xyk          | 692        | present   | PASS    |
| qsr (quote success)           | {_QSR}     | >= 0.80   | PASS    |
| data_completeness             | 1.0000     | >= 0.98   | PASS    |
| multicall_success_rate        | 1.0000     | >= 0.90   | PASS    |
| duration_fulfilled            | True       | True      | PASS    |
| unverified_active_routes      | 0          | 0         | PASS    |
| http_429_count                | {_HTTP_429}| -         | PASS    |
| cycles_positive_gross         | 0          | -         | MARKET  |
| toxic_route_rate              | {_TOXIC}   | < 0.90    | PASS    |
| CI full pipeline              | PASS       | -         | PASS    |
| DODO PMM skeleton tests       | 10/10      | -         | PASS    |
| RFQ skeleton tests            | 10/10      | -         | PASS    |
| pool_depth_probe tests        | 14/14      | -         | PASS    |

## 5) Current State (after Session {_SESSION})

### 5.1 Goals

| Goal                            | Status  | Details                                            |
|---------------------------------|:-------:|----------------------------------------------------|
| cycles_by_pricing_model non-null| REACHED | 3 models: clmm/cpmm/solidly_volatile_xyk           |
| M9 productive gate PASS         | REACHED | qsr={_QSR}>=0.80, h429=0, sweeps={_SWEEPS}          |
| M4 economics (profit proof)     | BLOCKED | cycles_positive_gross=0 (market)                   |
| Taxonomy code fixes #3-9        | REACHED | all done; 34 new tests pass                        |

### 5.2 Resolved Blockers

| Blocker                           | Status   | Evidence                                    |
|-----------------------------------|:--------:|---------------------------------------------|
| M9 gate qsr<0.80 (429-storm)      | RESOLVED | Session 17c: qsr=0.9703, h429=0             |
| cycles_by_pricing_model=None      | RESOLVED | non-null: clmm=2384 cpmm=139 ve33xyk=692    |
| aerodrome_stable not in ve33 path | RESOLVED | _VE33_ADAPTER_TYPES expanded to 7 types     |
| V2 fee always 30bps               | RESOLVED | _V2_FORK_FEE_BPS_MAP per-adapter lookup     |
| Missing PMM taxonomy coverage     | RESOLVED | DodoPmmAdapter skeleton + 10 tests          |
| Missing RFQ taxonomy coverage     | RESOLVED | RfqAdapter skeleton + 10 tests              |

### 5.3 Remaining Work

| Blocker                             | Type     | Next Action                           |
|-------------------------------------|:--------:|---------------------------------------|
| M9 gate: RESOLVED (qsr=0.9703)      | DONE     | Phase A: per-adapter cost model next  |
| BLOCKED_NO_POSITIVE_GROSS           | MARKET   | Phase A: per-adapter cost model       |
| DEX palette uniform (CPMM/CLMM)     | STRATEGY | Phase B: aerodrome_stable, curve      |
| Balancer pool_ids not populated     | CONFIG   | On-chain verify via Vault.getPool()   |

## Session Completion
session_goal: M9 productive gate PASS qsr>=0.80 + h429=0 + pricing taxonomy (Session {_SESSION})
goal_status: REACHED
  M9 productive gate: PASS (qsr={_QSR}, h429={_HTTP_429}, sweeps={_SWEEPS})
  cycles_by_pricing_model non-null: VERIFIED
  RUNTIME_VALIDATED__ORTHOGONAL_PRICING_VISIBLE: TRUE
  taxonomy fixes done; 34 new tests pass; CI full pipeline PASS
close_allowed: true
primary_blocker_of_session: 429-storm (ARBY_RPC_RPS_LIMIT not set)
blocker_status_before: qsr<0.80 (429-storm, effective_rpc_rps_limit=80)
blocker_status_after: RESOLVED
evidence_session_run_dirs:
  - data/runs/_rolling/m9_graph_latest.json ({_TS})
  - data/quarantine/m9_pool_depth_quarantine.json ({_QUARANTINE} entries)
docs_reread_confirmed: true
""")

with open('docs/DEV_REPORT_LATEST.md', 'w', encoding='utf-8') as f:
    f.write(content)
lines = content.count('\n')
print(f'Written: {lines} lines')
back = open('docs/DEV_REPORT_LATEST.md', encoding='utf-8').read()
assert back == content
assert f'Session {_SESSION}' in back, 'session ref missing'
assert 'Session 16' not in back, 'old session ref present'
assert lines <= 250, f'Too many lines: {lines}'
print('All assertions passed')
