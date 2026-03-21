# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled. R32 directive: **Connect wide sweep to OE re-check, auto-compute blocker taxonomy, reduce QUOTER_V2_FAILED.** R31 resolved artifact clarity (truth_verdict/OE funnel), not profit discovery. R32 addresses the 0-RT problem via sweep reprieve and economics re-check at multiple sizes.

## SESSION GOAL (R32: sweep reprieve + quoter skip cache + blocker taxonomy)
**Goal**: Implement lead's 10-step directive: connect wide-sweep ladder to OE re-check, aggregate R31 fields per-chain, prominence for truth_verdict, pair-level economics, base quote-path fix, blocker_classification auto-computation, docs framing fix.
**Prior (R31)**: OE bottleneck diagnosis. truth_verdict + quote_source_summary + oe_rejection_funnel. 43-run scan: 0 profitable RT. 2101 tests PASS.

## 0) Meta
timestamp_utc: (pending fresh scan)
run_dir_name: (pending fresh scan)
mode: SWEEP_REPRIEVE + QUOTER_SKIP_CACHE + BLOCKER_TAXONOMY (R32 directive)
test_count: 2126 passed, 5 skipped
schema_version: m4:run_summary:v2.1, start:long_scan_summary:v1.15

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R32: Connect wide-sweep to OE re-check, auto-compute blocker taxonomy, reduce QUOTER_V2_FAILED, fix R31 framing |
| goal_status | **IN_PROGRESS** (code changes complete, fresh scan pending) |
| close_allowed | false (need same-session evidence) |
| remaining_blockers | Fresh scan bundle required to validate sweep reprieve effect |
| evidence_session_run_dirs | (pending) |
| primary_blocker_of_session | 0-RT problem: OE rejects all at $10 probe (NET_PROFIT_TOO_LOW=57%), sweep never runs (eligible_opps empty) |
| blocker_status_before | ACTIVE: sweep disconnected from OE re-check; blocker_classification always null; quoter_v2 failures waste RPC |
| blocker_status_after | CODE_COMPLETE: sweep reprieve wired; blocker auto-computed; quoter skip cache active. Runtime validation pending. |
| start_metric | 2101 tests, 0 sweep reprieve, null blocker_classification, 59 QUOTER_V2_FAILED per base cycle |
| end_metric | 2126 tests, sweep reprieve for NET_PROFIT_TOO_LOW rejects, auto blocker taxonomy (6 values), quoter_v2 skip cache (3-fail threshold) |
| delta | +25 tests, +3 new test files, 7 files changed |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 - R32 directive: address 0-RT problem
change_summary:
  - **CRITICAL**: `strategy/roundtrip_selection.py` — `select_sweep_reprieve_candidates()`: when OE rejects all at $10 probe, NET_PROFIT_TOO_LOW rejects with both legs quoter_v2 + cross-DEX get swept at full 19-point size ladder.
  - **CRITICAL**: `strategy/jobs/run_scan_real.py` — sweep reprieve wiring: empty `eligible_opps` → reprieve candidates → `run_sweep()`.
  - **CRITICAL**: `start.py` — 4 new per-chain fields (last_truth_verdict, last_quote_source_summary, last_oe_rejection_funnel, blocker_evidence). `_compute_blocker_evidence()` auto-taxonomy: ROUNDTRIP_PROFITABLE | INFRA_FAIL | NO_SIGNAL | QUOTE_PATH_BLOCKED | OE_ECONOMICS | MIXED_SOURCE.
  - **CRITICAL**: `strategy/quotes.py` — quoter_v2 skip cache: after 3 consecutive failures, skip quoter_v2 for 10min (straight to slot0). Reduces QUOTER_V2_FAILED count + RPC waste.
  - `m4/fixtures.py` — truth_verdict moved to first status field in run_summary.
  - `scripts/pair_level_rca.py` — `_rt_gas_bps()` fixes latent bug (gas always 0 in counterfactuals), `_print_oe_funnel()` for console diagnostics.
  - `strategy/quote_metrics.py` — `quoter_v2_skipped` counter.
touched_files:
  - strategy/roundtrip_selection.py (CRITICAL — sweep reprieve)
  - strategy/jobs/run_scan_real.py (CRITICAL — sweep reprieve wiring)
  - start.py (CRITICAL — blocker_evidence auto-taxonomy + per-chain R31 fields)
  - strategy/quotes.py (CRITICAL — quoter_v2 skip cache)
  - m4/fixtures.py (truth_verdict prominence)
  - scripts/pair_level_rca.py (gas_bps fix + OE funnel printer)
  - strategy/quote_metrics.py (quoter_v2_skipped counter)
  - tests/unit/test_roundtrip_selection.py (+8 sweep reprieve tests)
  - tests/unit/test_blocker_evidence.py (NEW — 10 taxonomy tests)
  - tests/unit/test_quoter_v2_skip_cache.py (NEW — 7 skip cache tests)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2126 passed, 5 skipped)
```
Fresh scan: (pending)

## 3) R32 Architecture Changes

### Sweep Reprieve (connecting wide-sweep to OE re-check)
Problem: OE evaluates at single $10 probe → 57% rejected as NET_PROFIT_TOO_LOW → eligible_opps empty → sweep never runs.
Fix: `select_sweep_reprieve_candidates()` picks NET_PROFIT_TOO_LOW rejects where both legs are quoter_v2 + cross-DEX, deduplicates by pair (best spread), caps at 15. These are passed to `run_sweep()` which evaluates the full 19-point [$1-$10,000] size ladder. If ANY size is profitable at the frontier, the route is found.

### Quoter V2 Skip Cache (reducing QUOTER_V2_FAILED)
Problem: Base has 59/63 pools where quoter_v2 fails every cycle (dust liquidity), wasting RPC calls.
Fix: Module-level `_quoter_v2_fail_counts` tracks consecutive failures per pool_key. After 3 failures, quoter_v2 is skipped for 10 minutes (straight to slot0 diagnostic). Cache resets on success (liquidity recovery).

### Blocker Evidence Taxonomy (auto-computed per-chain)
Problem: `blocker_classification` was always null in long_scan_latest.json (only set from config YAML).
Fix: `_compute_blocker_evidence()` auto-computes from fresh evidence with priority:
1. ROUNDTRIP_PROFITABLE (≥1 profitable RT)
2. INFRA_FAIL (>50% run failure rate)
3. NO_SIGNAL (0 signals with runs > 0)
4. QUOTE_PATH_BLOCKED (>50% quoter_v2 failure rate)
5. OE_ECONOMICS (>40% NET_PROFIT_TOO_LOW in OE rejections)
6. MIXED_SOURCE (>30% MIXED_SOURCE in OE rejections)

## 4) Contract Checks
sweep_reprieve: 8 tests (filtering, dedup, max_candidates, source filtering, empty input)
blocker_evidence: 10 tests (full priority chain, truth_verdict fallback, no-evidence case)
quoter_v2_skip_cache: 7 tests (threshold, TTL expiry, success reset, pool independence)
truth_verdict first in run_summary: verified in fixtures.py
rolling discipline (3+1 files): OK
provenance contract: OK (run_timestamp only)
CI pipeline: 2126 tests PASS

## 5) R31 Framing Correction
R31 resolved artifact clarity (truth_verdict, quote_source_summary, oe_rejection_funnel) — not profit discovery. The 0-RT problem is an arb-specific OE economics bottleneck at the $10 probe, while base remains quote-path blocked. Chain-global "market-blocked" claims are premature. R32 addresses economics directly via sweep reprieve.

## 6) What I need from Lead now
1. **Fresh scan validation**: R32 changes are code-complete. Need same-session scan to validate sweep reprieve effect (does the 19-point ladder find profitable sizes for NET_PROFIT_TOO_LOW rejects?).
2. **Aerodrome re-enablement**: Base quote-path is QUOTE_PATH_BLOCKED. Aerodrome (ve33) was disabled R28.24 because `getAmountOut()` returns 0. Root cause investigation needed for R33.
3. **Per-chain priority**: linea and scroll are SIGNAL_PRODUCING with 100% pass rate. Push these toward roundtrip evaluation first?
4. **Adapter implementation**: iziswap/syncswap/ambient stubs still pending. Which first?
5. **Sweep integration with OE**: R29 wide ladder ($1-$10,000) never reaches OE because OE uses paper_size_usd=$10. Connect sweep to OE evaluation?
