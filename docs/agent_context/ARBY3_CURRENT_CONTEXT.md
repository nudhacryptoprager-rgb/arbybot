# ARBY3 Current Agent Context

This file is a compact context handoff for executor agents. It is not runtime
evidence and must not replace `Roadmap.md`, active `docs/status/Status_*.md`
files, or rolling artifacts.

## Operating Model

- GPT/Codex team lead owns planning, review, priority, and acceptance decisions.
- Cursor is the active executor for small, explicit patch tasks.
- Each Cursor task should name 3 to 7 files and one measurable goal.
- After a long exchange on one task, compact the handoff to the latest brief,
  current context, target files, and failing command.
- Use the configured Cursor default model for simple patches. Reserve premium
  models for hard debugging only after user approval.
- Opus/Fable auditors are read-only reviewers; they do not execute patches or
  close milestones.

## Source Of Truth

1. `Roadmap.md`
2. Active milestone status files under `docs/status/`
3. Runtime artifacts supplied by the user or Codex reviewer

Runtime provenance is based on `run_timestamp`, not git SHA. Git branch and
commit are only for reproducibility.

## Current Work Reading

- This section must be refreshed whenever the active development focus changes.
- The current task brief from Codex/user is the immediate executor scope.
- Active milestone details must be read from `docs/status/INDEX.md` and the
  relevant `docs/status/Status_*.md`.
- Execution remains disabled unless the user gives an explicit separate unlock
  instruction after evidence review.

## Cursor Boundaries

- Do not read or edit secrets, `.env`, runtime artifacts, logs, or virtual envs.
- Do not manually edit rolling artifacts.
- Do not update Status or DEV_REPORT before verification evidence exists.
- Do not update `Roadmap.md` without explicit user approval.
- Do not broaden scope beyond the named files without asking.

## Test Discipline

- Start with targeted pytest for the touched area.
- Then run the broader requested gate.
- Use `py -3.11` on Windows.
- Stop after two failed fix attempts for the same test or gate and report the
  blocker back to GPT/Codex team lead.

## Default Verification Commands

```powershell
py -3.11 scripts/check_repo_safety.py
py -3.11 -m pytest tests/unit -q
py -3.11 scripts/ci_full_pipeline.py --mode ci
```

Run online commands only when Codex/user explicitly requests them and any required
RPC preflight is satisfied.

## M8 Coverage Contract

- M8 sniper discovery scans all **configured** DEXes with adapter/event support in
  `config/` and `adapter_metadata.yaml`, not every DEX that exists on-chain.
- Expansion backlog may include tokens seen on DEXes without adapter support; those
  remain backlog until adapter coverage or event sources exist.

## Batched M8 Refresh (`--streaming`)

- Pipeline mode `batched_m8_refresh`: per-batch sniper→M8.1→M8.2→M8.3 under
  `data/tmp/streaming_batches/<session>/batch_N/`, then one M9 pass on the final batch
  bundle (anchor, hints, expansion, M8.3 registry must align).
- M8.1 remains quote/inventory diagnostics only; mirror economics and metadata authority
  stay in M8.2/M8.3 respectively.
- **M8.1 admission contract (streaming):** `gate_acceptance=false` means productive quote
  rate is below the strict perf gate; `strategy_gate_acceptance=true` with
  `perf_gate_fail=false` allows the batched pipeline to continue as a discovery lane.
  `rpc_error_rate < 0.1` is required for soft-exit (exit 0) in streaming batch mode.
  M8.1 does not gate M9 bridge admission — upstream truth gates and M8.2 handoff do.
- **M9 lane acceptance (streaming):** `m9_lane_acceptance` must consume final-batch
  M8.2 acceptance report, expansion, and M8.3 registry from `batch_N/` (not rolling).
  With `--skip-shadow`, `upstream_bundle_status=UPSTREAM_BUNDLE_VALIDATED` is the
  success criterion; `m9_shadow_acceptance_status=SKIPPED` — not production-ready M9.
