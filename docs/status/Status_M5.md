# Milestone 5 — Production small

Roadmap Milestone 5 deliverables

- Daily reporting artifact (daily_report_*.json) with schema_version and run coverage
- Stable definitions: win_rate, net_pnl_usdc, tail_losses, top_reject_reasons
- Auto-sizing rules (min/max/clamp and back-off/restore heuristics)
- Transparent health metrics (rpc/dex/system)
- CI validation for M5 (ci_m5_gate)

DoD-commands

- Run the gate in strict online mode and produce artifacts:
  - `python scripts/ci_m5_gate.py --validate-daily report.json`
- Unit tests green: `python -m pytest -q`

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
- `trades_count`: int
- `tail_losses`: list of top-k worst trade outcomes (by pnl)
- `top_reject_reasons`: list of {reason, count}
- `health`: {rpc: {...}, dex: {...}, system: {...}}

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

M5_0 closed on SHAs: add your SHAs here. Close only if:

- `scripts/ci_m5_0_gate.py --online --strict` passes
- `pytest -q` green

Next: Milestone 5 — Production small (see Status_M5.md)
