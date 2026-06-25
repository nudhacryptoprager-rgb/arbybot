# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-24T09:34:00Z
goal_status: BLOCKED
blocker_status_after: NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR
docs_reread_confirmed: true
run_id: m9-production-capacity-rebuild-2026-06-24
mode: FRESH_UPSTREAM_TO_PRODUCTION_BRIDGE
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Production-capacity rebuild (10 fix steps): fresh M8→M8.3→wide production bridge→depth→capacity; no shadow until cycles_at_floor>0.
goal_status: BLOCKED
primary_blocker_of_session: NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR
docs_reread_confirmed: true

## Upstream refresh

| Step | Result |
|------|--------|
| M8 sniper 45m | `2026-06-24T08:22:48Z`, 112 events |
| M8.1 anchor | PASS |
| Radar 753 | phase1+verify+secondary complete |
| M8.2 expansion | `2026-06-24T11:00:52Z`, **442 routes** |
| M8.2 strict | **REACHED** |
| Curve indices | **22** `QUOTE_OK_INT128` (116 probed) |
| M8.3 strict | **REACHED**, dex_routes_ready=407/407 |
| Production bridge | **active=407**, curve=116, v4=138 |
| Graph-handoff bridge | active=158 |
| Depth enrich | depth_known_rate=**0.4275**, gte_180=72 |
| Capacity diagnostic | cycles_total=**3632**, cycles_at_floor=**0** |
| Lane acceptance | m8_3_upstream=REACHED, upstream_blockers=[] |
| Shadow | **not run** |

## Production bridge DEX mix

| DEX | Active routes |
|-----|---------------|
| uniswap_v4 | 138 |
| curve_stable | 116 |
| maverick_v2 | 89 |
| balancer_vault | 27 |
| uniswap_v2 | 20 |
| uniswap_v3 | 14 |
| pancakeswap_v3 | 3 |

## M9 blockers
`NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR`, `DEPTH_ENRICHMENT_REQUIRED` (0.4275 < 0.8), `NO_QUOTEABLE_CYCLES`

## Operational notes
- Production bridge built with `--no-enforce-m8-provenance` so quotable Curve routes remain in `active_routes` (otherwise relegated to exploration).
- `discover_curve_indices` uses `data/tmp/m9_bridge_curve_probe.json` (exploration curve routes) when active set lacks curve pre-indices.

## Next
- Improve depth_known_rate toward >=0.8; reprobe false-positive cap-band routes (`depth_reprobe_required`).
- Investigate cycle-level capacity vs per-route gte_180 (72 routes deep but 0 cycles at floor).
- Shadow only when `cycles_at_floor > 0`.

## Audit addendum: M8→M9 freshness and capacity

audit_verdict: report accepted with precision corrections
goal_status: BLOCKED
primary_blocker_of_session: NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR
docs_reread_confirmed: true

### Confirmed
- M8.2 handoff remains REACHED; it produces bridge-eligible topology, not economics.
- M8.3 strict remains REACHED; metadata is no longer the active blocker.
- M9 is blocked before shadow because `cycles_at_floor=0` across all configured profiles.
- Raw `gte_180` route count is not equivalent to cycle capacity; every leg must survive DEX-family usable-capacity fractions.

### Additional debts
- Fresh sniper tokens are not yet isolated from accumulated watchlist/radar tokens in the main production path.
- `m8_token_watchlist_latest.json` needs TTL/pruning or lane split to avoid repeated broad sweeps.
- M8.3 should add a TTL negative-cache for `NON_ERC20` / failed ERC20 rows so refreshes do not re-probe the same non-economics-grade addresses.

### Unblock criteria
- `depth_known_rate >= 0.8` on the production bridge.
- `false_positive_depth_cap_band` routes reprobed or explicitly classified.
- `cycles_at_floor > 0` for `diagnostic_near_econ` or `base_realistic` before any new M9 shadow.
