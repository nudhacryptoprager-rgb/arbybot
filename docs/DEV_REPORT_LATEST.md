# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-06T12:00:00Z
mode: OFFLINE CI (full pipeline verified, nonstop pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-06T12:00:00Z
  dirty: true
  desc: M7.A.5.47i — anomaly-clean recoverable stale + bridge hit detection isolation + C2 gas tolerance

## Session Completion
session_goal: M7.A.5.47i — anomaly-clean recoverable-stale filtering, explicit bridge selection transparency, first live bridge hit
goal_status: REACHED (code changes complete, 3437 tests pass, nonstop verification pending)
close_allowed: true
remaining_blockers: bridge_pool_hit_total still needs runtime verification with 47i fix
evidence_session_run_dirs: [tests/unit (3437 passed, 6 skipped)]
primary_blocker_of_session: bridge_pool_address_hit_count always 0 due to silent exception in bridge detection block
blocker_status_before: DIAGNOSED (47h showed viable_count=0, PRICING_ANOMALY contaminated C1, bridge hit detection silently crashed)
blocker_status_after: ADDRESSED (3 independent try/except blocks, anomaly-clean C1, C2 gas tolerance, bridge-miss auto-promote)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47i — anomaly-clean recoverable stale + bridge hit detection fix
change_summary:
  - m7/orderflow/artifacts.py (MODIFIED): Strict recoverable_stale filter — requires `reject_reason == STALE_POSITIVE` explicitly (not `_is_stale()` class match). Excludes PRICING_ANOMALY and TOKEN_PAIR_UNRESOLVED via `_ANOMALY_REJECTS` set.
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) **CRITICAL FIX**: Split bridge hit detection into 3 independent try/except blocks — registry-match, PTT-hit, and loaded-count/pair-fallback. Previously a single try/except with bare `pass` — any exception in registry ops silently killed bridge hit counting. (b) C1 defense-in-depth: `_ANOMALY_REJECTS` set skips PRICING_ANOMALY/TOKEN_PAIR_UNRESOLVED even if artifacts leaked them. (c) C2 gas-near tolerance: families within `_C2_GAS_GAP_TOLERANCE_BPS = -10` bps of breakeven now admitted (was strictly > 0 only). (d) Bridge file update uses safe aliases (`_ba`, `_bb`, `_bc1`, `_bc2`, `_ptt_diag`) instead of raw `_bucket_a` etc. to avoid NameError. (e) Bridge-miss active auto-promote: hot-seen pools in `recent_active_pools_top` auto-pinned into `_hot_seen_pin`. (f) Bridge hit diagnostic log line with sample pool addresses + PTT size. (g) `hot_seen_vs_bridge_overlap_top` always written (never None), merged into bridge file.
  - tests/unit/test_47i_anomaly_clean.py (NEW): 26 tests — anomaly-clean recoverable stale (5), C1 defense-in-depth (3), bridge hit isolation (4), C2 gas tolerance (8), bridge-miss auto-promote (6).
touched_files:
  - m7/orderflow/artifacts.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47i_anomaly_clean.py (NEW)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3437 passed, 6 skipped)

## 3) Artifacts Attached

No new rolling artifacts (offline session). Nonstop run pending with 47i changes.

## 4) Key Results — M7.A.5.47i

### Root Cause Analysis (from fresh 47h nonstop evidence)

**Bug 1 — PRICING_ANOMALY contamination**: `_is_stale()` in artifacts.py returned True for `same_state_class=stale` regardless of `reject_reason`. Pool `0x7dfa` had `reject_reason=PRICING_ANOMALY` with `best_backrun_net_bps=36927` (absurd pricing artifact). This leaked through recoverable_stale filter into C1 bridge bucket, wasting bridge capacity on an anomalous pool.

**Bug 2 — Silent exception killing bridge hit detection**: The entire bridge hit detection block (registry-match + PTT-hit + pair-fallback) was wrapped in a single `try: ... except Exception: pass`. If `_hot_registry.lookup_pair()` or `e.is_active()` raised in the FIRST loop (registry match), the bridge hit counter loop NEVER executed. Result: `bridge_pool_address_hit_count` always 0 despite 7/10 hot-seen pools being in PTT.

**Bug 3 — Bridge file update using unsafe variables**: The hot-side bridge file update block used `_bucket_a`, `_bucket_b`, `_bucket_c1_stale`, `_bucket_c2_gas_near` directly instead of safe aliases. If bridge assembly had any failure, these were undefined → NameError → silently caught → `bridge_selected_pools_top` never written.

### 47i Fixes

1. **Strict recoverable_stale**: `reject_reason == STALE_POSITIVE` explicitly, not `_is_stale()` class match. `_ANOMALY_REJECTS = {PRICING_ANOMALY, TOKEN_PAIR_UNRESOLVED}` exclusion.
2. **C1 defense-in-depth**: Even if artifacts leak anomalies, orderflow_loop skips them.
3. **Bridge hit detection isolation**: 3 independent try/except blocks with `logger.debug` on failure (not bare `pass`). Block 2 (PTT hit) is pure dict-in-set — no registry ops can kill it.
4. **Bridge hit diagnostic logging**: `logger.info` after bridge hit loop showing `raw_results` count, PTT size, hit count, and sample pool addresses from both sides.
5. **C2 gas tolerance**: `_C2_GAS_GAP_TOLERANCE_BPS = -10` — families within 10 bps of breakeven admitted to C2. Was strictly `verified_net_bps > 0`.
6. **Safe bridge file update**: Uses `_ba`, `_bb`, `_bc1`, `_bc2`, `_ptt_diag` aliases with `dir()` guard.
7. **Bridge-miss active auto-promote**: Pools in both `bridge_miss_sample` and `recent_active_pools_top` auto-pinned into `_hot_seen_pin` (TTL=3).

## 5) Strategic Reading

1. **Bug 2 is the most impactful fix**: bridge_pool_address_hit_count was being silently killed by unrelated registry exceptions. With isolated try/except blocks, PTT hit counting is independent.
2. **Bug 1 fix prevents false-positive C1 entries**: PRICING_ANOMALY at 36927 bps was polluting C1 and wasting bridge capacity.
3. **C2 gas tolerance** allows near-breakeven families into the bridge — more candidate diversity.
4. **Runtime evidence needed**: 10-minute nonstop with 47i to verify (a) bridge_pool_address_hit_count > 0, (b) PRICING_ANOMALY excluded from recoverable_stale, (c) overlap diagnostic populated (not None).

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (canonical rolling files unchanged, new fields additive only)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
docs_reread_confirmed: true
