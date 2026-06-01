# Status: M7 (Triangular Feasibility)

**Status**: NO_GRADUATE — FUNDAMENTAL_DISCOVERY_GAP confirmed. M7.B (atomic multi-hop
execution) remains closed. M7 serves as R&D evidence that the public-infrastructure
two-leg DEX-DEX backrun thesis has a structural disadvantage on Base.

`goal_status`: FUNDAMENTAL_DISCOVERY_GAP
`pipeline_ready`: true
`production_profit_ready`: false
`close_allowed`: false
`m7b_open`: false
`no_graduate_verdict`: true

## Final Verdict (E1.83 — 2026-05-10)

```
production_sized_total:     0   FAIL (min=1)
best_amount_in_usd:         37.99   (never reached $50 real depth)
best_expected_profit_usd:   22.44   PASS (min=0.01)
roundtrip_profitable_delta: 0   FAIL (min=1)
submit_ready_delta:         0   FAIL (min=1)
ws_429_rate:                0.64%   PASS (max=15%)
pytest:                     5098 passed / 6 skipped / 0 failures
```

Root cause: CE universe = dust meme tokens OR instantaneous-only spreads.
- VIRTUAL/WETH bps=6909 but `depth_verdict=dust_only` at all real sizes.
- Deep multi-DEX pairs (USDC/WETH 4dex/$184M) never appear as CE — MEV-efficient.
- Factory scout confirmed: even with 7-factory enumeration and 30-pair PPM,
  the CE candidates are exclusively dust tokens or short-lived spreads.

## Structural Blockers (Public Infrastructure)

| Blocker | Detail |
|---------|--------|
| **Latency** | Public RPC 200–400ms RTT; pro MEV searchers use private relayers <50ms |
| **Mempool blindness** | Only see confirmed events; professionals use Flashbots/MEV-Share |
| **Bundle access** | Base sequencer whitelist-only for bundles |
| **Capital efficiency** | $50–$1000 vs $184M TVL pool = 10⁻⁶ depth; spread 0.5–2 bps < gas 1–3 bps |

**Conclusion:** structural disadvantage on public infra, not a tuning problem. Next path: M8/M9.

## What Was Built (Reuse ≈ 70–75%)

- Multi-chain factory enumeration (`discovery/factory_enumeration.py`, `discovery/index_factories.py`).
- `pool_family_truth.json` — 78 pools, 7 BASE-pairs, 6 DEXes.
- Cold/Hot lane architecture + M7 supervisor (`scripts/start_nonstop_runtime.py`).
- Discovery / quarantine / verify pipeline.
- Rolling artifacts + dashboard + strict gates.
- 5098 passing unit tests (at M7 close), contract enforcement.

## Canonical Commands

```powershell
py -3.11 -m pytest tests/unit -q
py -3.11 scripts/check_repo_safety.py
py -3.11 scripts/ci_full_pipeline.py --mode ci
# M7 strict gate (offline, historical reference only):
py -3.11 scripts/post_soak_pass_gate.py --strict
```
