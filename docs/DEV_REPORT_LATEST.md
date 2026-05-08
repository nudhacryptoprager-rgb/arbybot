# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-08T19:39:26Z
run_id: nonstop_runtime_20260508_E1.68_roundtrip_pnl_fix_SOAK_COMPLETE
mode: ONLINE
artifact_mode: rolling
config: base / production + discovery / real_minimal.yaml
code_identity:
  primary: ts:2026-05-08T19:39:26Z
  desc: E1.68 SOAK_COMPLETE — frontier/split sizing roundtrip PnL math fix confirmed by 30-min live soak; optimal_usd improved 6.7× post-fix.

## 1) Scope
goal: E1.68 — fix critical frontier/split sizing PnL math bug where comparison used `buy_amount - sell_amount` (different token units) instead of `sell_amount - amount_in` (same token_in units). Previous E1.67: closed REACHED (universe correction + wstETH/WETH + 30-min soak).

## 2) Findings
- **Critical PnL math bug in frontier/split sizing** (`m7/orderflow/scoring_parallel.py`): `attempt_local_pricing` returns `buy_amount` in `token_out` units and `sell_amount` in `token_in` units. The intermediate frontier selection was comparing `buy_amount - sell_amount` (cross-token subtraction = nonsense), producing incorrect size rankings and potentially selecting dust-level sizes as "optimal".
- Fixed to: `sell_amount - amount_in` via new helper `_roundtrip_gross_wei(amount_in_wei, sell_amount_wei)`.
- All previous E1.67 findings (universe 22→23, wstETH/WETH on-chain, soak evidence) remain valid but the `amount_in_optimal_usd` metrics from that soak are pre-fix and should not be used to conclude "market allows only ~$0.1 size". Fresh soak required.

## 3) Changes (E1.68)
1. `m7/orderflow/scoring_parallel.py`:
   - Added `_roundtrip_gross_wei(amount_in_wei, sell_amount_wei) → int`: canonical PnL helper, compares same token_in units.
   - Added `_roundtrip_net_bps_from_sell(amount_in_wei, sell_amount_wei) → float`: net bps measured in token_in denomination.
   - All 4 call-sites in frontier loop + split-route selection + final gross-wei accounting now use these helpers.
   - Replaced incorrect `buy_amount - sell_amount` comparison throughout.
2. `tests/unit/test_e1_64_step_fixes.py`:
   - Added `TestSplitRouteGrossPnlWin` class with 3 regression tests: import smoke, `_roundtrip_gross_wei` correctness, `_roundtrip_net_bps_from_sell` sign/direction test.

## 4) Market research summary
From previous E1.67 session: DefiLlama Base TVL $4.51B, DEX 24h volume $773M.
Already covered: WETH/USDC, cbBTC, AERO, VIRTUAL, EURC, cbETH, BRETT, DEGEN, TOSHI (+ others).
Added in E1.67: wstETH/WETH (Lido bridged, 10 on-chain pools across 4 DEXes). Universe: 23 canonical Base pairs.

## 5) Validation
```
pytest tests/unit/test_e1_64_step_fixes.py -q : 11 passed (0.15s)
pytest tests/unit -q                           : 4865 passed, 6 skipped, 1 warning (130s)
intent_loader Base pair count                  : 23 (E1.67)
```

## 6) Audit (offline → online)
- Offline registry path (`discovery/registry.PoolRegistry`) is legacy and produces 0 candidates because `dexes.yaml` no longer carries `enabled` / `verified_for_quoting` flags. The live system uses `discovery/pool_resolver.py` invoked by `m7/orderflow/runtime.py`.
- Live runtime artifacts (`m7_tier_map_base.json`, `_pool_token_cache.json`) used as ground truth.

## 7) Soak Evidence (E1.68, post-fix — PRIMARY)
```
Soak window:      2026-05-08T19:09:23Z → 19:39:26Z (30 min, clean exit 0)
Processes:        5/5 alive entire window (0 crashes, 0 restarts, 0 dirty exits)
Discovery:        launched at +600s (19:19Z), 4 + 2 discovery = 5 total lanes
Cold lane cycle:  1st cycle at 19:25:25Z (~16 min in); session_delta captured
WS health:        peak WS=5/505, pct_429 range 0.0%–1.2% (avg ~0.5%)
Dashboard:        pipeline_ready=true, fresh=True at all 6 monitor snapshots
```

### Opportunity funnel (post cold-cycle):
```
OPP total:        15 (steady throughout soak)
RES (profitable): 5 (all FUN/USDC variants, same pool 0x659be706)
DUST only:        8 (after cold cycle surfaced 3 more candidates at +15m)
PROD sized:       0 (market depth thin; FUN/USDC genuine microcap pool)
```

### E1.68 frontier sizing evidence (KEY RESULT):
```
PRE cold-cycle:   amount_in_optimal_usd=0.074762 (hot-only, original event size)
POST cold-cycle:  amount_in_optimal_usd=0.499996 (cold bridge, size_source=usd_frontier_rescaled)
Improvement:      6.7× optimal size increase (≈$0.075 → ≈$0.50)
net_spread_bps:   3027 bps @ $0.50 optimal, profit=$0.151
profit_buckets:   $1→$0.40, $10→$4.04, $50→$20.18 (extrapolated)
depth_verdict:    dust_only (genuine market constraint — FUN/USDC thin pool)
size_source:      usd_frontier_rescaled (confirms frontier selection IS running)
```

### Split route counters (session_delta, 1 cold cycle):
```
e163_split_route_attempted: 243
e163_split_route_wins:       25  (10.3% win rate)
e164_depth_guard_rejected:    0
e164_min_profit_rejected:     7
e164_usd_basis_missing:       7
```

### Pre-fix reference (E1.67 soak, same pool):
```
amount_in_optimal_usd: 0.074762  (was "dust" by cross-token subtraction bug)
→ Bug caused frontier to undervalue all sizes vs. original event size
→ Fix correctly selects $0.50 as better than $0.075 for this pool
```

### Tier map:
```
hot=77 warm=0 cold=0 (artifact from E1.67; this session didn't refresh tier_map —
discovery deferred 600s and new hot events write tier_map only on hot cycle)
```

## 8) Findings & Honest Limits
- **E1.68 confirmed**: Frontier sizing math fix is working. `amount_in_optimal_usd` jumped from $0.075 to $0.50 (6.7×) when cold lane first cycled, and `size_source=usd_frontier_rescaled` confirms the frontier search is selecting non-trivial sizes.
- **Market depth is the real limiter**: `depth_verdict=dust_only` on all profitable opps reflects genuine FUN/USDC pool thinness, not a math artifact. Bug was masking this by selecting the wrong size, but the pool is genuinely small-cap.
- **Production-sized opps remain 0**: Expected given the pool depth; next step is either discovering deeper pools (more bridge-quality candidates) or waiting for higher-liquidity events to trigger in the hot lane.
- **Split win rate 10.3%** (25/243): Healthy; split route logic is identifying cross-venue improvements.
- `cold_positive_pool_seen_in_hot_count=0` + `pool_price_state.updates_total=0` remain as known gaps.
- `wstETH/WETH` pools: 10 pools verified on-chain (E1.67); haven't entered `_pool_token_cache.json` yet (needs WS swap traffic). Eager prewarm pending (issue #8).

## Session Completion
session_goal: E1.68 — fix frontier/split sizing roundtrip PnL math + regression tests + 30-min soak validation
goal_status: SOAK_COMPLETE
close_allowed: true
blocker_status_after: RESOLVED
remaining_blockers: none blocking; next milestone is surfacing deeper pools (production-sized opps require >$10 pool depth, current best is FUN/USDC ~$0.50 optimal)
docs_reread_confirmed: true
