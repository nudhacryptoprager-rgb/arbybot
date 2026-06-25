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
| M8 - New-Pool Sniping Pivot | [OPEN] | [Status_M8.md](Status_M8.md) |
| M8.1 - Stable-Anchor Inventory & Diagnostics | [ACTIVE] | [Status_M8_1.md](Status_M8_1.md) |
| M8.2 - Cross-DEX Expansion & Mirror Handoff | [HANDOFF_REACHED] | [Status_M8_2.md](Status_M8_2.md) |
| M8.3 - Token Metadata Registry & Decimals | [STRICT_PASS] | [Status_M8_3.md](Status_M8_3.md) |
| M9 - Graph-Arb Long-Tail Shadow Scanner | [IN PROGRESS] | [Status_M9.md](Status_M9.md) |

## Current Focus

**M4 - DEX<->DEX Atomic Execution**: current public-infrastructure branch is frozen by economics evidence; milestone remains open only because online profitable core truth was not reached. See [Status_M4.md](Status_M4.md).

**M7 - Triangular Feasibility (M7.A)**: bounded R&D branch with verdict-ready no-graduate result for the current `arbitrum_one` narrow-universe scope. Live measured scoring, size sweep, blocker RCA, and bounded verdict are complete; `M7.B` remains closed. See [Status_M7.md](Status_M7.md).

**M8 - New-Pool Sniping Pivot**: next production-profit path after M7 economics evidence; starts as documentation-aligned OPEN milestone and must produce its own artifacts before any production claim. See [Status_M8.md](Status_M8.md).

**M8.1 - Stable-Anchor Inventory & Diagnostics**: inventory layer for stable/near-peg pairs; feeds M9 graph builder. `gate_acceptance=true`, `strategy_gate_acceptance=false` (NO_STABLE_EDGE). See [Status_M8_1.md](Status_M8_1.md).

**M8.2 - Cross-DEX Expansion & Mirror Handoff**: graph-handoff **REACHED** (`handoff_ready=true`); mirror quote / economics remain out of scope for M8.2. Quality gates in `m8_2_acceptance_report.py`. See [Status_M8_2.md](Status_M8_2.md).

**M8.3 - Token Metadata Registry & Decimals Service**: **STRICT_PASS** (`m8_3_acceptance_report.py --strict` REACHED); Curve `coin_indices` handoff via `m8/metadata/curve_indices.py`. Rolling artifact: `m8_3_token_metadata_registry_latest.json`. See [Status_M8_3.md](Status_M8_3.md).

**M9 - Graph-Arb Long-Tail Shadow Scanner**: **M8_3_STRICT_PASS / M9_CAPACITY_BLOCKED** — production bridge `active=407`, `cycles_total=3632`, but `cycles_at_floor=0` all profiles; `depth_known_rate=0.4275`. Shadow not run. See [Status_M9.md](Status_M9.md).

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
