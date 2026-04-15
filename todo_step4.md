# STEP 4: Production-Ready Action Plan (2026-04-14)

## Context

4-hour production + discovery scans (2026-04-13) produced **0 submit_ready** opportunities.
Pipeline works end-to-end (1 sim_passed) but is blocked at 5 critical points.

### Scan Results Summary

| Metric | Production | Discovery |
|--------|-----------|-----------|
| Events total | 2534 | 1042 |
| Scored | 276 | 263 |
| Positive | 36 | 11 |
| Guard passed | 45 | 10 |
| Sim attempted | 30 | 10 |
| **Sim passed** | **1** | **0** |
| Submit ready | **0** | **0** |

---

## 5 ROOT BLOCKERS

### B1: Bridge Selection ↔ Activity Mismatch (CRITICAL)
- `families_with_exact_hits: 0` — 27 selected families, NONE received events
- 84 families have events at completely different pools
- Cold lane writes bridge every 5–30 min (stale); hot lane filters to old pools
- 89.5% windows = `no_events_in_window`
- **Without this fix, all other optimizations have ZERO effect**

### B2: Sim Calldata Build Failures (HIGH)
- TOKEN_ADDRESS_UNKNOWN: 12 (token not in core_tokens.yaml)
- DEX_CONFIG_MISSING: 6 (hot lane outputs pool address instead of DEX key)
- STF: 1 (Anvil balance seeding failed)
- 19/30 sim attempts fail on calldata (63%)

### B3: Gas Economics — L1 Data Cost Dominant (HIGH)
- 665/748 matched candidates rejected by gas (89%)
- L1 data = 80% of total gas cost (Base EIP-4844)
- Gas floor = 0.5 bps; most cross-DEX spreads < 0.5 bps
- Best candidates: VIRTUAL/WETH = -10 bps (deeply negative)

### B4: Bridge Registry Miss Rate (MEDIUM)
- 1294/1344 bridge pool hits don't resolve to registered pairs (96%)
- Pools on-chain not in PTT (Pool Token Transport)

### B5: No Token/Subgraph Discovery for Base (MEDIUM)
- "subgraph seed not supported for chain: base"
- addr_to_symbol grew only 19→20 in 4h
- No dynamic token discovery

---

## PHASE 1: "Make It Work" (today)
*Goal: First submit_ready candidates with existing architecture*

### [ ] 1.1 Enable ARBY_PAPER_SIGNING (5 min)
- Already implemented in execution_gate.py (E1.15)
- Just set env var: `ARBY_PAPER_SIGNING=1`
- Impact: 1 sim_passed → 1 submit_ready (instant unblock)

### [ ] 1.2 Expand core_tokens.yaml for Base (30 min)
- Add TOP-30 Base tokens by volume from Aerodrome/CoinGecko
- BRETT, DEGEN, TOSHI, MOG, HIGHER, cbETH, USDbC, WELL, etc.
- Impact: TOKEN_ADDRESS_UNKNOWN 12 → ~0 (40% of sim failures)
- File: `config/core_tokens.yaml`

### [ ] 1.3 Fix DEX_CONFIG_MISSING — venue name resolution (2h)
- Problem: scoring engine outputs pool address as `best_buy_venue`
- execution_gate.py expects DEX key (uniswap_v3, aerodrome, etc.)
- Fix: add reverse-lookup from pool address → DEX key using factory
- File: `m7/orderflow/execution_gate.py`
- Impact: DEX_CONFIG_MISSING 6 → ~0 (20% of sim failures)

### [ ] 1.4 Fix Anvil STF seeding (1h)
- Problem: keccak256 storage slot wrong for some tokens
- Fix: try multiple slot variants (0,1,2,3) + verify balanceOf
- File: `m7/orderflow/sim_backends/anvil_backend.py`
- Impact: STF errors → ~0

### [ ] 1.5 Run tests + 30-min validation scan
- `python -m pytest tests/unit -q`
- Scan with fixes: `ARBY_PAPER_SIGNING=1 python -m strategy.jobs.run_scan --mode real --config config/onboard_base_stage2.yaml`
- Expected: 3+ submit_ready in 30 min

---

## PHASE 2: "Make It Fast" (days 2-4)
*Goal: 10x candidate throughput via bridge selection fix*

### [ ] 2.1 100% Broad Mode — tactical quick fix (2h)
- Set `_BROAD_FALLBACK_INTERVAL = 1` in mode_ws_live.py
- All blocks use unfiltered eth_getLogs (no address restriction)
- Trade-off: more RPC calls, but coverage >> bandwidth now
- Impact: catch events at ALL active pools, not just 27 stale ones

### [ ] 2.2 Dynamic Token Discovery on-chain (1 day)
- Read token0/token1 from pool contract + symbol() on-chain
- Cache in memory + flush to `core_tokens_dynamic.json`
- Replace subgraph dependency for Base entirely
- Impact: TOKEN_ADDRESS_UNKNOWN → 0 for any pool

### [ ] 2.3 Pool → DEX Mapping Registry (4h)
- Build reverse index: pool_address → dex_key at discovery time
- Use factory address matching or factory logs
- Impact: DEX_CONFIG_MISSING → 0

### [ ] 2.4 Reactive Bridge Hot-Update (1 day)
- Hot lane feeds newly-seen active pools back into bridge in real-time
- Currently bridge is 5-30min stale (cold lane writes only)
- Impact: families_with_exact_hits 0 → 20+, window coverage 10% → 50%+

---

## PHASE 3: "Make It Profitable" (days 5-14)
*Goal: Strategic pivot for real profitability*

### [ ] 3.1 Backrun Large Swaps (main strategic pivot)
- Monitor flashblocks for large swap events (>$10K)
- Calculate post-trade price dislocation
- Build atomic backrun via different DEX
- Base FCFS sequencer = <100ms advantage window

### [ ] 3.2 Flashblocks Integration (3 days)
- `mainnet.flashblocks.base.org/ws` — 200ms pre-confirmations
- Parse pre-confirmed blocks for large swap signatures

### [ ] 3.3 Gas Optimization — smaller calldata (2 days)
- Multicall packed encoding: 228 → ~160 bytes
- L1 data cost reduction ~30%
- Custom minimal-calldata router

### [ ] 3.4 Multi-DEX Atomic Router (5 days)
- Deploy custom contract: buy DEX-A + sell DEX-B atomically
- One tx instead of two → 50% less gas
- Includes flash loan if needed

### [ ] 3.5 Expand Aerodrome CL Pools (2 days)
- Aerodrome = 60%+ Base DEX volume
- Add Slipstream (CL) adapter: factory + router

---

## SUCCESS METRICS

| Phase | Metric | Current | Target |
|-------|--------|---------|--------|
| 1 | submit_ready / 30min | 0 | 3+ |
| 1 | sim_pass_rate | 3% (1/30) | >50% |
| 2 | families_with_exact_hits | 0 | >20 |
| 2 | window event coverage | 10.5% | >50% |
| 3 | positive net_bps candidates | 0 | >5/hour |
| 3 | paper P&L / day | $0 | >$10 |

---

## KEY INSIGHT

Pure cross-DEX arbitrage on Base has marginal profitability (confirmed by R39x+5 research).
The real opportunity is **backrunning large swaps** via the FCFS centralized sequencer.
Phase 1+2 prove the pipeline works; Phase 3 pivots to where the money is.
