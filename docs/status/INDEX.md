# Status Index

_Last updated: 2026-02-19 (v2.3.2)_

> **v2.0+ Provenance**: Evidence based on `run_timestamp` + rolling artifacts, not SHA.
> See `docs/DEV_REPORT_CANONICAL_UA.md` for canonical report format.

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

**M4 — DEX↔DEX Atomic Execution**: M4.1 simulate-only PROVEN; M4 online profit DoD NOT PROVEN.

See `Roadmap.md` Core Truth for release criteria.

## Archive

- [Status_M4_legacy.md](Status_M4_legacy.md) — ARCHIVE (SHA-based, deprecated)
- See [archive/](archive/) folder for historical status documents.

## Rules

1. One active Status file per milestone (`Status_M0.md`, `Status_M1.md`, etc.)
2. New patches = new section in existing milestone file, NOT new file
3. Old versions go to `archive/` folder (mark as ARCHIVE)
4. No files with spaces in names
5. Evidence: rolling artifacts (`_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json`)
