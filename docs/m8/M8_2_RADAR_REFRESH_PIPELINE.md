# M8.2 Radar Refresh Pipeline

Цей документ фіксує operational-шлях гілки M8 -> M8.1 -> M8.2 -> M9 для
пошуку дзеркал нових токенів. Він описує звідки беруться дані, які джерела
вважаються truth, і коли вмикаються WS, async та multicall.

## Data Path

```text
M8 sniper
  -> new on-chain pool events
  -> m8_pending_pairs.json / token watchlist

M8.1 stable-anchor diagnostics
  -> anchor metadata and quote-probe context

M8.2 radar
  -> external hints only
  -> m8_radar_pool_candidates_latest.json

M8.2 verify / expansion
  -> on-chain verification
  -> m8_external_pool_hints_latest.json
  -> m8_cross_dex_expansion_latest.json

M9 graph shadow
  -> bridge inventory
  -> quote/depth/sizing/economics validation
```

The truth boundary is unchanged:

```text
External API row = hint
On-chain verified pool/route = canonical M8.2 input
M9 quote/depth/sanity = economics truth
```

No external provider may bypass on-chain verification.

## Source Roles

| Source | Default role | Why |
|--------|--------------|-----|
| M8 sniper | first-seen truth | on-chain pool creation source |
| DexScreener | primary wide radar | fast token-pairs sweep for M8 tokens |
| GeckoTerminal | secondary/audit | checks tokens DexScreener missed or marked weak |
| The Graph token API | structured secondary | index-backed token pool hints |
| CoinGecko Onchain | fallback/canary | budgeted reserve, not default full refresh |
| DeFiLlama | scan weights only | DEX priority signal, not admission |
| 0x / 1inch / Uniswap API | liveness benchmark only | external route signal, not canonical truth |

## Default Refresh Mode

The default M8.2 refresh is DexScreener-first and two-phase:

```text
Phase 1: radar_fast
  source: DexScreener
  verify: none
  output: m8_radar_pool_candidates_latest.json

Phase 2: verify_subset
  source: DexScreener candidates
  verify: specialized on-chain
  output: m8_external_pool_hints_latest.json

Phase 3: secondary
  sources: GeckoTerminal, The Graph token API
  input: tokens DexScreener missed or marked weak

Phase 4: fallback
  source: CoinGecko Onchain
  input: small canary or failed/stale subset only
```

Use:

```powershell
py -3.11 scripts/m8_radar_two_phase_refresh.py --max-tokens 753 --skip-coingecko
```

Then expansion must be refreshed before acceptance claims:

```powershell
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m8_cross_dex_expand.py --chain base --expansion-mode token_neighborhood --external-hints data/runs/_rolling/m8_external_pool_hints_latest.json --scan-mode candidate_summary --progress data/tmp/m8_cross_dex_expand_progress.json

py -3.11 scripts/m8_2_acceptance_report.py --strict
py -3.11 scripts/m8_2_scan_coverage_report.py --strict
```

## Fast Path Flags

These flags are allowed when they do not weaken truth:

| Flag | Layer | Meaning | Quality boundary |
|------|-------|---------|------------------|
| `--fetch-async` | M8.2 radar fetch | fetch configured sources for one token in parallel | does not change admission |
| `--ws-head` | M8.2 verify | pin verification context to current WS head | does not replace verify |
| `--use-multicall` | M8.2 verify | batch/pre-pass RPC checks before specialized verify | does not replace specialized verify |
| `--verify-async-workers N` | M8.2 verify | run on-chain verification workers in parallel | bounded by RPC health |
| `--skip-route-liveness` | radar run | skip 0x/1inch/Uniswap probes | required unless route-liveness keys are intentionally tested |
| `--skip-defillama-weights` | radar run | skip DEX priority fetch | safe for speed tests |

WS, async and multicall are accelerators, not trust gates. If any accelerator
fails, the run may fall back to slower verification, but it must not mark hints
canonical without on-chain evidence.

## When To Use Each Mode

| Situation | Command policy |
|-----------|----------------|
| normal operator cycle | `m8_radar_two_phase_refresh.py --skip-coingecko` |
| speed canary | DexScreener only, small `--max-tokens`, route-liveness skipped |
| provider A/B | run baseline first, then fallback provider sample |
| CoinGecko budget check | `coingecko_onchain` only on small or failed subset |
| full audit | multi-provider refresh, lower concurrency, explicit checkpoint |
| before M9 shadow | require fresh hints -> fresh expansion -> M8.2 acceptance |

## Required Metrics

Every M8.2 radar refresh must expose enough metrics to decide whether the
provider helped:

```text
radar_fast_tokens
radar_candidates
verify_subset_size
radar_to_verify_rate
verified_yield
per_source_verified_yield
provider_timing
fetch_async
use_multicall / bytecode_parallel_prepass
ws_head_block
```

Acceptance is based on verified handoff, not raw radar volume. `radar_seen` with
zero `onchain_verified` is noise.

## Freshness Rule

The order must be:

```text
M8/M8.1 fresh enough
-> M8.2 hint refresh
-> M8.2 expansion
-> M8.2 acceptance
-> M9 bridge/shadow
```

If hints are newer than expansion, `EXPANSION_FRESHNESS_ORDER_VIOLATION` is
expected and M9 must not be run from that mixed evidence.

## Concurrency Safety

Only one hint refresh may write a given checkpoint/output pair at a time.
Use the lock in `m8/discovery/hint_refresh_lock.py` for long runs. If duplicate
processes exist, stop the older run before trusting artifacts.

Do not commit runtime outputs under `data/runs/**`.

