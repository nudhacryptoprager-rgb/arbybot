# Technical Debt Tracker

> Policy: track non-blocking technical debt that still matters after the current public-infrastructure DEX-DEX audit.

## Active Items

### TD-002: Large File Concentration

**Added**: 2026-03-14  
**Priority**: MEDIUM  
**Category**: Architecture

The repo is now functionally much healthier than it was before the R39 extraction wave, but several files still carry too much orchestration surface:

| File | Current Shape | Why It Still Matters |
|------|---------------|----------------------|
| `strategy/jobs/run_scan_real.py` | primary online orchestration shell | runtime glue still dense |
| `strategy/quotes.py` | large quote pipeline surface | mixed adapter/fallback/policy logic |
| `scripts/ci_m5_0_gate.py` | large gate script | validation/reporting surface still broad |
| `scripts/check_repo_safety.py` | large repo policy checker | many independent checks in one file |

Current reading:

- this is real maintainability debt,
- but it is no longer the main blocker for strategy truth,
- large-file cleanup should follow milestone needs, not become a refactor project by itself.

---

### TD-001: `websockets.legacy` Deprecation Warning

**Added**: 2026-02-23  
**Priority**: LOW  
**Category**: Dependencies

The warning remains non-blocking. It should be cleaned up eventually, but it is not currently affecting milestone truth, CI, or rolling evidence quality.

---

## Resolved / Reclassified

### TD-003: Event-Driven Freshness As Primary Leverage

**Added**: 2026-03-24  
**Reclassified**: 2026-03-27  
**Result**: resolved as a strategic no-go for the current public-infrastructure thesis

What changed:

- the repo now contains enough fresh live evidence to evaluate the claim directly,
- WS/polling freshness improvements did not yield material spread improvement on the current public-infrastructure simple DEX-DEX path,
- `DirtySetTracker`, `PairHotQueue`, and hot-loop scaffolding remain useful infrastructure, but event-driven freshness is no longer a high-priority profit unlock for the current thesis.

This means:

- the code should not be ripped out,
- but it should also not be treated as the current highest-value optimization target.

---

## Current Debt Reading

The main open debt in this repo is no longer "hidden infra weakness". The remaining debt is mostly:

1. code concentration in several large orchestration files,
2. documentation drift if status/docs are not kept aligned with rolling evidence,
3. dormant execution capability that is implemented architecturally but not promoted operationally.
