# Status Index

> Timeless index of milestone status files.  
> See [DOCS_POLICY.md](../DOCS_POLICY.md) for documentation rules.

## Active Milestones

| Milestone | Status | File |
|-----------|--------|------|
| M0 - Bootstrap + Quote Pipeline | [DONE] | [Status_M0.md](Status_M0.md) |
| M1 - Real Gas Price + Paper Trading | [DONE] | [Status_M1.md](Status_M1.md) |
| M2 - Registry-driven scanning + Truth Report | [DONE] | [Status_M2.md](Status_M2.md) |
| M3 - Opportunity Engine + Quality & Contracts | [DONE] | [Status_M3.md](Status_M3.md) |
| M4 - DEX-DEX Atomic Execution | [IN PROGRESS] | [Status_M4.md](Status_M4.md) |
| M5_0 - Infrastructure Hardening | [DONE] | [Status_M5_0.md](Status_M5_0.md) |
| M7 - Triangular Feasibility (M7.A) | [IN PROGRESS] | [Status_M7.md](Status_M7.md) |

## Current Focus

**M4 - DEX<->DEX Atomic Execution**: current public-infrastructure branch is frozen by economics evidence; milestone remains open only because online profitable core truth was not reached. See [Status_M4.md](Status_M4.md).

## Related

- [Roadmap.md](../../Roadmap.md) - Milestone definitions and DoD
- [DEV_REPORT_LATEST.md](../DEV_REPORT_LATEST.md) - Current session report (with versions/timestamps)
- [ARCHIVE_MAP.md](ARCHIVE_MAP.md) - Map to archived status files

## Rules

1. One active Status file per milestone (`Status_M0.md`, `Status_M1.md`, etc.)
2. When a milestone is CLOSED per `Roadmap.md`, its Status file is FROZEN (do not keep appending unrelated work)
3. New patches = new section in the existing milestone file, NOT a new variant file
4. Historical variants live outside `docs/` in `archive/status/**` (use `docs/status/ARCHIVE_MAP.md` as the map)
5. No files with spaces in names
6. Evidence: rolling artifacts (`_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`)
