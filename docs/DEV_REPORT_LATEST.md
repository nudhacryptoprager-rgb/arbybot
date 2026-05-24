# DEV REPORT LATEST — M9 Smoke27: Economics RCA Complete + Gate PASS

**mode**: M9_SMOKE27_DASHBOARD_SYNC_ECONOMICS_RCA
**session_date**: 2026-05-24
**schema_family**: m9_graph_arb
**schema_revision**: m9.1
**run_label**: smoke27 (15-min real-RPC soak, publicnode, dynamic_sizes, factory-verified inventory)
**execution_enabled**: false
**kill_switch_active**: true

---

## Smoke27 Summary

**goal**: Validate live dashboard synchronization and determine whether deeply negative M9 economics are caused by metric/dashboard breakage or by real quoted route economics.

**result**: REACHED. Runtime gates PASS on fresh rolling artifact. Dashboard schema `m9_dashboard.3` is live, fresh, and synchronized with the scanner. Deep negative economics are reproduced in canonical artifact data and per-leg RCA; no RPC, quote-decode, quote-revert, stale-dashboard, or factory-verification blocker explains the losses.

### Run stats
- run_timestamp: 2026-05-24T13:16:05Z
- generated_at_utc: 2026-05-24T13:31:05Z
- elapsed=900.5s, duration_fulfilled=True
- sweeps=412, cycles_found=4099, cycles_quoteable=4007
- qsr=0.9776, cycles_positive_gross=0
- rpc_provider=publicnode, http_429_count=0, actual_http_calls=6037
- dynamic_size_enabled=True, selected_count=1212, selection_rate=0.2957

### runtime_gates
| gate | value | threshold | pass |
|---|---:|---:|---|
| multicall_success_rate | 1.0 | 0.90 | PASS |
| data_completeness | 1.0 | 0.98 | PASS |
| unverified_active_routes | 0 | 0 | PASS |
| qsr | 0.9776 | 0.80 | PASS |
| quote_revert_rate | 0.0 | <0.05 | PASS |
| **all_pass** | **true** | | **PASS** |

### Economics RCA
- loss_reason_histogram: `TOXIC_ROUTE_PRICE_IMPACT=4007`, `QUOTE_FAILED=92`
- toxic_route_rate=1.0 across quoteable cycles
- best displayed quoteable cycle: `AERO/TOSHI/WETH/USDC`
- spread_bps=-9176.6129
- pre_fee_gross_bps=-9040.6129
- fee_drag_bps=136.0
- factory_verified=True, factory_class=UNKNOWN

**Interpretation**: The deep negative result is not caused primarily by fees. The cycle is already about -9040 bps before fees and worsens with size. Per-leg RCA shows the closed loop returning far less of the starting token, so the displayed `spread_bps` is directionally justified. The remaining problem is route quality/toxic price impact, not M9 collection quality.

**On-chain root cause (confirmed 2026-05-24)**: Direct slot0+liquidity query via publicnode reveals two thin-pool tiers:
- **AERO/TOSHI UV3 fee=10000** (`0x7e904aaf`): liquidity=8.57e+20, spot_price=2735 TOSHI/AERO (fair), but actual quoter output=229 TOSHI per AERO (8.7% of spot). Price impact=91.6% at any size ≥$100. This pool bottlenecks the top ~10% of cycles (best spread=-9177 bps).
- **USDC/VIRTUAL UV3** pools: liquidity=2.3e+15–3.8e+18 (22000× thinner than VIRTUAL/WETH UV3 fee=500 at 6.3e+22). Cycles through USDC/VIRTUAL lose ≈99.91% per hop. Drives median=-9991 bps (90% of universe).
- NOT a code or infrastructure issue. Scanner correctly classifies 100% cycles as TOXIC_ROUTE_PRICE_IMPACT.

### Verified commands
```powershell
py -3.11 -m pytest tests\unit\test_dashboard_m9_server.py tests\unit\test_m9_invariants.py -q
py -3.11 scripts/ci_m9_productive_gate.py --artifact data/runs/_rolling/m9_graph_latest.json
py -3.11 scripts/check_repo_safety.py
```

Results:
- 57 passed
- M9 productive-state gate: PASS
- Repo safety: PASS (2 pre-existing M7/M8 doc-bloat warnings)

---

## Session Completion

session_goal: Monitor smoke27, validate dashboard synchronization, and investigate deeply negative M9 economics.
goal_status: REACHED
close_allowed: true
remaining_blockers: thin-pool universe drives 100% TOXIC_ROUTE_PRICE_IMPACT; recommended next step: min_usd_liquidity filter in cycle builder to exclude pools with <$1000 effective depth; USDC/VIRTUAL and AERO/TOSHI UV3-1% are primary candidates for pool blacklisting.
evidence_session_run_dirs: data/runs/_rolling/m9_graph_latest.json (run_ts: 2026-05-24T13:16:05Z)
blocker_status_before: Deep negative dashboard economics could be metric breakage, stale artifact, RPC failure, or real route economics.
blocker_status_after: Dashboard sync PASS; infra PASS; deep negative economics attributed to quoteable toxic route price impact.
docs_reread_confirmed: true
