# Technical Debt Tracker

> **Policy**: Track non-blocking technical debt for future cleanup.
> Items here don't block CI/CD but should be addressed proactively.

## Active Items

### TD-002: God-File Splitting (R28.1)
**Added**: 2026-03-14
**Priority**: MEDIUM
**Category**: Architecture

**Description**:
Several files remain oversized (god-files) and need meaningful extraction:

| File | Lines | Extraction Candidates |
|------|-------|----------------------|
| `scripts/ci_m5_0_gate.py` | ~1887 | Validation helpers, artifact builders, report formatters |
| `scripts/check_repo_safety.py` | ~1596 | Individual check functions to dedicated modules |
| `strategy/quotes.py` | ~1722 | Slot0 logic (diagnostic), QuoterV2 logic, price math to core/math.py |
| `strategy/jobs/run_scan_real.py` | ~1346 | Summary builders, universe handlers |

**R28 Progress**: Extracted `core/gate_helpers.py` (discover_artifacts, get_run_dir_candidates, validate_schema_version) and `core/repo_checks.py` (docs policy constants). But total god-file reduction was cosmetic — files still large.

**Impact**: Code comprehension, testing isolation, maintainability.

**Next Steps**:
1. Extract `calculate_price_from_sqrt` and relacionado math to `core/math.py`
2. Extract `read_slot0_v3` + cache functions to `strategy/slot0.py` (diagnostic-only path)
3. Split check_repo_safety into per-check modules under `scripts/checks/`
4. Extract summary builders from run_scan_real.py to dedicated module

**Tracking**: R28.1 acknowledges debt honestly; extraction ongoing.

---

### TD-003: Event-Driven Freshness (R39g+)
**Added**: 2026-03-24
**Priority**: HIGH
**Category**: Architecture / Signal Quality

**Description**:
Current scan loop polls all pairs on a fixed timer. The `DirtySetTracker` (R38) provides the primitive — `wait_for_dirty(timeout)` wakes on WS `newHeads` — but the quote pipeline still re-quotes the entire universe each cycle regardless of which pools actually had state changes.

The lead identifies this as **the highest-leverage protocol-level improvement**: "spread < slippage + LP fee + gas" on every route, but much of the slippage estimate is stale because quotes are seconds old by the time the opportunity engine evaluates them.

**Current state**:
- `DirtySetTracker` exists in `strategy/infra.py` with `threading.Event` wake.
- `DEFAULT_QUOTE_FRESHNESS_MS = 3000` in `core/models.py`.
- Simulator rejects stale quotes (`execution/simulator.py` `_check_quote_freshness()`).
- No per-pool dirty tracking — all pools re-quoted each cycle.

**Target architecture**:
1. Per-pool dirty bits: WS subscription to pool `Swap`/`Sync`/`Mint`/`Burn` events marks specific pools dirty.
2. Selective requote: only dirty pools re-quoted each cycle, reducing RPC load and latency.
3. Fresher quotes → tighter slippage estimates → opportunities that are currently rejected as unprofitable may become viable.
4. Priority integration: dirty pools with cross-dex spread > threshold get front-of-queue requoting.

**Impact**: Currently all 5 chains show slippage >> spread. ARB/USDC (closest to breakeven at $254.97 gap) could narrow significantly with sub-second quote freshness. Estimated improvement: reduced QUOTE_STALE rejections, tighter slippage modeling, potential for profitable RT on high-volume pairs.

**Next Steps**:
1. Extend `DirtySetTracker` with per-pool granularity (pool address → last_dirty_block).
2. Add WS event filters for `Swap` events on tracked pools.
3. Modify scan loop to skip clean pools (or use longer interval for clean pools).
4. Benchmark: measure quote freshness distribution before/after.

**Tracking**: R39g+ documents as architectural priority. Not blocking M5.0 CI.

---

### TD-001: websockets.legacy Deprecation Warning
**Added**: 2026-02-23
**Priority**: LOW
**Category**: Dependencies

**Description**:
`websockets.legacy` is deprecated in websockets major version 14. Test runs show warning:
```
websockets.legacy is deprecated; see https://websockets.readthedocs.io/en/stable/howto/upgrade.html
```

**Impact**: None currently (tests pass), but may break in future websockets versions.

**Resolution Options**:
1. Pin websockets to version below 14 in requirements.txt
2. Upgrade websockets usage to non-legacy API
3. Suppress warning temporarily

**Tracking**: pytest shows 1 warning, non-blocking.

---

## Resolved Items

(None yet)

---

## Guidelines

- Add items when they appear in CI output but don't block
- Include reproduction steps and resolution options
- Move to Resolved when fixed with date and PR reference
