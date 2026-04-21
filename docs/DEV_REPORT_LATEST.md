# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
run_id: reviewer 30-min STF validation soak 2026-04-21 (Base, anvil + dRPC)
mode: ONLINE
artifact_mode: rolling
config: Base, strict admission, Step 9 drift mitigation live
code_identity:
  primary: ts:2026-04-17T12:59:11Z
  dirty: true — M7.E1.34d reviewer-fix cycle
  desc: REVERT:unknown sub-buckets, strict-provider hard-fail, profit_guard invariant enforced at source, sim_failed_samples canonical attrs

## 1) Scope
goal: Implement reviewer fix batch from 2026-04-21 STF validation soak.
Counter-only observability was insufficient; runtime must enforce declared
policies (strict provider, profit_guard ≤ route_viable) and the sim
histogram must distinguish REVERT:unknown shapes.

change_summary:
  - `m7/orderflow/sim_backends/rpc_fork_backend.py` — REVERT:unknown split
    into `no_data` / `text:*` sub-buckets (raw_hex already caught by
    Case 5). Fix #4 tightened.
  - `m7/orderflow/mode_ws_live.py` — `ARBY_STRICT_PROVIDER_POLICY=1` now
    (a) implies `ARBY_RPC_PREMIUM_ONLY=1`, (b) rejects public WS fallback
    on 429, (c) hard-exits if primary WS resolves to `public_fallback`.
    Fix #2.
  - `m7/orderflow/profit_guard.py::annotate_profit_guard_results` —
    enforces invariant at source: `route_viable=False` → guard rejected
    with `guard_reject_reason="ROUTE_NOT_VIABLE"`. Fix #6.
  - `m7/orderflow/execution_gate.py` — `sim_failed_samples` now populates
    venue/router/token_in/token_out via canonical BackrunResult attrs
    (`best_sell_venue`, `backrun_token_in_address`, …). Fix #3.
  - `tests/unit/test_m7_e1_34d_reviewer_fixes.py` (NEW, 8 tests).
  - `tests/unit/test_revert_decoder.py`, `tests/unit/test_rpc_fork_backend.py`,
    `tests/unit/test_orderflow_artifacts.py` — assertions updated for the
    new no_data bucket and the viability-gated guard path.

touched_files:
  - m7/orderflow/sim_backends/rpc_fork_backend.py
  - m7/orderflow/mode_ws_live.py
  - m7/orderflow/profit_guard.py
  - m7/orderflow/execution_gate.py
  - tests/unit/test_m7_e1_34d_reviewer_fixes.py (NEW)
  - tests/unit/test_revert_decoder.py
  - tests/unit/test_rpc_fork_backend.py
  - tests/unit/test_orderflow_artifacts.py
  - docs/status/Status_M7.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed
pytest tests/unit: **PASS** 4222 / 0 failed / 6 skipped (133.33s)
pytest target (`test_m7_e1_34d_reviewer_fixes` +
  `test_revert_decoder` + `test_m7_e1_34c_reviewer_fixes`): **PASS** 33 / 0
check_repo_safety.py: expected PASS after this overwrite

## 3) Artifacts
canonical rolling: `_latest.json`, `run_summary_latest.json`,
  `m4_stability_agg.json`, `m7_hot_rollup_latest.json`,
  `m7_hot_rollup_latest_discovery.json`, `m7_orderflow_latest*.json`
run_dir_bundle: `data/runs/ci_m5_gate_arbitrum_one_20260417_145636_478653/reports`
reviewer ephemera: `reviewer_soak_baseline_latest{,_discovery}.json`,
  `reviewer_soak_delta_latest.json`, `reviewer_soak_30m_stdout.log`
new histogram sub-buckets: `REVERT:unknown:no_data`,
  `REVERT:unknown:text:<trim>`.

## 4) Key Results — Reviewer 30-min STF validation soak (2026-04-21)
production: +58 windows / +3 fast_scored / +2 guard_passed /
  +2 sim_attempted / **+2 sim_passed** / +0 BlockOutOfRangeError /
  +15 strict_provider_breaches
discovery:  +59 windows / +3 fast_scored / +3 guard_passed /
  +3 sim_attempted / **+3 sim_passed** / +0 BlockOutOfRangeError /
  +11 strict_provider_breaches
verdict: **ACCEPTANCE FAIL** — strict provider breaches > 0 on both
lanes; roundtrip_success=0; submit_ready=0. sim_passed > 0 for the first
time, but runtime still routed windows through public_fallback.
Counter-only policy insufficient → M7.E1.34d raises strict provider to
hard-fail; next soak must run with premium RPC/WS configured.

## 4.1) Theoretical Net Profit
mode: paper_simulated; net_pnl_usdc: n/a (no profitable roundtrip).
execution_enabled=false, kill_switch_active=true. No real trades.

## 5) Contract Checks
pytest tests/unit: **PASS** 4222 / 0
status/reasons consistency: OK; rolling discipline: OK
new invariants enforced:
  - profit_guard requires route_viable (annotate path + scoring_parallel agree)
  - strict provider policy is active, not observational

## 6) Blocker Classification
code_blocker: **LOW** — 4222 PASS (+8 new fix tests).
data_collection_blocker: **HIGH** — premium RPC/WS required for next
  soak; `ARBY_STRICT_PROVIDER_POLICY=1` will now hard-exit on fallback.
market_window_blocker: **HIGH** — STF / toxic-pair reverts remain
  dominant; canonical M4 still `ROUNDTRIP_NOT_PROFITABLE`.

## 6.1) Risks
- Strict policy now halts runtime on public fallback; if premium WS rate
  limits during a soak the run will abort rather than silently degrade.
  This is intentional, but reviewer must provision headroom.
- REVERT:unknown:text bucket can still grow; treat as triage input.

## 7) Execution Map
step_01 venue fallback: DONE | step_02 block retry: DONE | step_05 quality
gates: DONE | step_06 AMOUNT_ZERO autofill: DONE | step_07 admission
filter: DONE | step_08 TOKEN_ADDRESS_UNKNOWN: NOT STARTED |
step_09 anvil drift: VALIDATED | step_10 reviewer fix batch
(#2/#4/#5/#7): DONE | **step_11 reviewer fix batch
(#2-hard / #3 / #4-sub / #6 / #8): DONE** |
step_12 next 30m soak with strict policy + populated samples: NEXT.

## 8) Requests to Lead
request_1: Confirm premium RPC/WS credentials provisioned before next
  30-min soak; strict policy will hard-exit on 429 fallback.
request_2: Confirm acceptance contract for submit_ready (currently
  excluded; `ARBY_PAPER_SIGNING=1` can be set to exercise the signing
  path if desired).
q_1: Should `REVERT:unknown:text` crossing a threshold escalate to a
  dedicated histogram tag per top-N prefixes?

---

## REVIEWER RUNBOOK — 30-min STF validation soak (M7.E1.34d)

### Term A — anvil fork + refresher
```powershell
.\venv\Scripts\Activate.ps1
$env:PATH = "$PWD\tools\foundry;$env:PATH"
$env:ARBY_FORK_RPC_URL = "<dRPC base archive URL>"
$env:ARBY_ANVIL_AUTO_REFRESH="1"; $env:ARBY_ANVIL_REFRESH_INTERVAL_S="60"; $env:ARBY_ANVIL_REFRESH_DRIFT_BLOCKS="120"
py -3.11 scripts/start_anvil_fork.py --chain base --fork-block-offset 5
```

### Term B — 30m soak with STF classification + strict provider
```powershell
$env:ARBY_SIM_BACKEND="anvil"; $env:ARBY_ANVIL_RPC_URL="http://127.0.0.1:8545"
$env:ARBY_SIM_FALLBACK="rpc_fork"; $env:ARBY_HOT_REHYDRATE="1"
$env:ARBY_SIM_ADMISSION_STRICT="1"; $env:ARBY_SIM_MIN_NET_BPS="1.0"
$env:ARBY_SIM_BYPASS_GUARD="0"; $env:ARBY_ANVIL_CLAMP_BLOCK="1"
$env:ARBY_STRICT_PROVIDER_POLICY="1"
Copy-Item data/runs/_rolling/m7_hot_rollup_latest.json data/runs/_rolling/reviewer_soak_baseline_latest.json
Copy-Item data/runs/_rolling/m7_hot_rollup_latest_discovery.json data/runs/_rolling/reviewer_soak_baseline_latest_discovery.json
py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 0.5 --with-discovery --no-m4
```

### Post-soak acceptance
```powershell
py -3.11 scripts/reviewer_soak_summary.py --discovery   # exit 0=PASS / 2=FAIL
py -3.11 -c "import json,pathlib; d=json.loads(pathlib.Path('data/runs/_rolling/m7_hot_rollup_latest.json').read_text()); [print(s['bucket'],s['pair'],s['venue']) for s in d.get('sim_failed_samples_recent',[])]"
```
**Acceptance:** `Δsim_passed>0` both lanes, `ΔBlockOutOfRangeError==0`,
`Δroundtrip_attempted>0`, `strict_provider_breaches_total==0`.

---

## Session Completion
session_goal: Reviewer fix batch M7.E1.34d (#2 hard-fail, #3 samples,
  #4 sub-buckets, #6 invariant at source, #8 runbook).
goal_status: REACHED (code-level) — 4222 PASS. BLOCKED at field
  validation until next 30m soak with premium RPC/WS provisioned.
close_allowed: true
remaining_blockers: premium provider provisioning; STF root-cause triage;
  Step 8 TOKEN_ADDRESS_UNKNOWN; canonical M4 still NOT_PROFITABLE.
evidence_session_run_dirs: data/runs/_rolling.
primary_blocker_of_session: strict provider enforcement + invariant drift.
blocker_status_before: ACTIVE — strict policy counted but did not halt;
  profit_guard could pass with route_viable=False; sim_failed_samples
  carried None venue/router/token_in/token_out.
blocker_status_after: MITIGATED at runtime level — strict provider now
  hard-fails; guard rejects non-viable routes at source; sim_failed
  samples populated from canonical attrs; REVERT:unknown split into
  no_data/text sub-buckets. Field validation pending next soak.
docs_reread_confirmed: true
