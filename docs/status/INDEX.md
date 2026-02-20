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
| M5_0 - Infrastructure Hardening | [ACTIVE] | [Status_M5_0.md](Status_M5_0.md) |

## Current Focus

**M4 - DEX<->DEX Atomic Execution**: See [Status_M4.md](Status_M4.md) for latest evidence.

## Related

- [Roadmap.md](../../Roadmap.md) - Milestone definitions and DoD
- [DEV_REPORT_LATEST.md](../DEV_REPORT_LATEST.md) - Current session report (with versions/timestamps)
- [ARCHIVE_MAP.md](ARCHIVE_MAP.md) - Map to archived status files

## Rules

1. One active Status file per milestone (`Status_M0.md`, `Status_M1.md`, etc.)
2. New patches = new section in existing milestone file, NOT new file
3. Old versions go to `archive/` folder (git history)
4. No files with spaces in names
5. Evidence: rolling artifacts (`_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`)
