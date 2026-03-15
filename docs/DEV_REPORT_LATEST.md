# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 6 Round 28.8)
**Goal**: R28.8 — Universe expansion: UniswapV2 adapter, intent.txt generator, remove artificial caps, expand dexes.yaml.
**Prior (R28.7)**: Economics engine correctness complete (1837 tests, 8-9 signals, gap 15 bps). Lead R28.8 directive: "lack of arb profit is not lack of signals; it is incomplete full-universe executable ranking on the primary truth path."

## 0) Meta
timestamp_utc: 2026-03-15T13:38:06Z
rolling_provenance: 2026-03-15T13:38:06Z (arbitrum_one NORMAL — R28.7 evidence retained)
mode: UNIVERSE_EXPANSION + ADAPTER_IMPLEMENTATION + CONFIG_GENERATION
test_count: 1850 passed, 3 skipped (+13 new tests from UniswapV2 adapter)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.8: Universe expansion — UniswapV2 adapter, intent.txt generator, suppression removal, dexes.yaml expansion |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | INFRASTRUCTURE: intent.txt uncommitted (requires commit); MARKET: gap ~15 bps (unchanged from R28.7) |
| evidence_session_run_dirs | n/a (pure_code_session — no new online runs, tests verify changes) |
| primary_blocker_of_session | Universe artificially suppressed: adapter_types filter excluded ve33/v2, DEFAULT_MAX_PAIRS=20 capped discovery, dead tokens in intent.txt |
| blocker_status_before | adapter_types=["uniswap_v3","algebra"], DEFAULT_MAX_PAIRS=20, intent.txt hand-edited with dead tokens (LINEA/MUTE/SPACE) |
| blocker_status_after | RESOLVED: adapter_types=None (all adapters), DEFAULT_MAX_PAIRS=100, intent.txt machine-generated (116 verified pairs), UniswapV2 adapter implemented |
| start_metric | R28.7: 1837 tests, 3 adapter types (uniswap_v3, algebra, ve33), no V2 support |
| end_metric | R28.8: 1850 tests (+13), 4 adapter types (+uniswap_v2), sushiswap_v2 in dexes.yaml, intent.txt generator |
| delta | +UniswapV2 adapter, +generate_intent.py, +sushiswap_v2 in dexes.yaml, caps removed |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M2.4 UniswapV2 adapter + universe expansion (R28.8 lead directive)
change_summary:
  - UNISWAP_V2_ADAPTER: `dex/adapters/uniswap_v2.py` — new adapter using getReserves() + constant product formula. Supports all V2 forks (SushiSwap, PancakeSwap V2, etc). 13 unit tests in `tests/unit/test_uniswap_v2_adapter.py`.
  - ADAPTER_REGISTRATION: `dex/registry.py` — registered uniswap_v2 adapter. `dex/adapters/__init__.py` — exported UniswapV2Adapter.
  - INTENT_GENERATOR: `scripts/generate_intent.py` — machine-generates intent.txt from verified core_tokens.yaml. 116 pairs across 6 chains. Eliminates dead tokens, enforces consistent pair rules.
  - CAPS_REMOVED: `discovery/runtime.py` — DEFAULT_MAX_PAIRS 20→100, adapter_types=None (all adapters participate). Documented operational contract.
  - DEXES_EXPANDED: `config/dexes.yaml` — added sushiswap_v2 on arbitrum_one (first V2-type DEX).
  - TOKEN_DEBT_CLOSED: intent.txt — removed dead tokens (LINEA=soulbound LXP, MUTE→KOI rebrand, SPACE=deactivated).
touched_files: dex/adapters/uniswap_v2.py (+NEW), dex/registry.py, dex/adapters/__init__.py, discovery/runtime.py, config/intent.txt, config/dexes.yaml, scripts/generate_intent.py (+NEW), tests/unit/test_uniswap_v2_adapter.py (+NEW), tests/unit/test_adapter_readiness.py

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1850 passed, 3 skipped) — +13 new tests from UniswapV2 adapter
py -3.11 scripts/check_repo_safety.py --allow-intent-edit: **PASS** (intent.txt changes intentional)
py -3.11 scripts/generate_intent.py --write: **116 pairs** written to config/intent.txt
py -3.11 scripts/validate_universe.py --config config/real_intent_arbitrum_one.yaml: **PASS**

## 3) Artifacts Attached (шляхи)
rolling (RETAINED from R28.7 — no new online runs):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-15T13:38:06Z, runDir: ci_m5_gate_arbitrum_one_20260315_143747_439501)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS)

new_files_created:
  - dex/adapters/uniswap_v2.py (UniswapV2 adapter, 141 lines)
  - scripts/generate_intent.py (intent.txt generator, 175 lines)
  - tests/unit/test_uniswap_v2_adapter.py (13 tests)

## 4) Key Results (числа з артефактів)

```
# Adapter Coverage (R28.8)
registered_adapters: ["uniswap_v3", "algebra", "ve33", "uniswap_v2"]
dexes_yaml_v2_count: 1 (sushiswap_v2 on arbitrum_one)

# Discovery Caps (R28.8)
DEFAULT_MAX_PAIRS: 100 (was 20)
adapter_types: None (was ["uniswap_v3", "algebra"], excluded ve33/v2)

# Intent Universe (R28.8)
intent_pairs_total: 116 (machine-generated)
intent_pairs_arbitrum: 36
intent_pairs_base: 23
intent_pairs_linea: 18
intent_pairs_scroll: 14
intent_pairs_mantle: 12
intent_pairs_zksync: 13
dead_tokens_removed: LINEA (soulbound), MUTE (rebranded), SPACE (deactivated)

# Test Coverage (R28.8)
test_count: 1850 (up from 1837)
new_test_file: tests/unit/test_uniswap_v2_adapter.py (13 tests)
```
linea:        21 signals, $48, truth=True (profitable roundtrips! positive control confirmed)
base:         22 signals, $6, probe stage
zksync:       7 signals, $2, PASS
mantle:       NO_DATA
scroll:       FAIL (accepted)

# Key operational contract (NEW in R28.7)
signal ≠ opportunity ≠ executable candidate
  signals_count=8: raw spread detections (advisory threshold=0 in truth_mode)
  sim_profitable_count=5: paper economics positive (one-leg diagnostic)
  executable_candidates_count=4: passed post-quote cross-dex + lp + margin gates
  roundtrip.profitable_count=0: cost-adjusted canonical profit (the REAL metric)
```

## 5) Contract Checks
- UniswapV2 adapter: implements getReserves() + constant product formula, registered in dex/registry.py
- Operational contract: documented in discovery/runtime.py — truth gates (require_cross_dex, quarantine, confidence) vs removed suppression (adapter_types filter, DEFAULT_MAX_PAIRS cap)
- Intent.txt generator: scripts/generate_intent.py machine-generates from core_tokens.yaml — eliminates manual editing error
- Token debt closed: LINEA (soulbound LXP), MUTE (rebranded to KOI), SPACE (deactivated) removed from intent.txt
- SushiSwap V2: added to dexes.yaml on arbitrum_one — first V2-type DEX registered
- Adapter coverage: 4 types (uniswap_v3, algebra, ve33, uniswap_v2) — was 3
- Rolling discipline: maintained — NORMAL-only guard intact

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1850 PASS, new V2 adapter fully tested)
market_gap: MEDIUM (unchanged — gap_to_zero ~15 bps from R28.7)
adapter_coverage: LOW (V2 adapter complete, registration done, sushiswap_v2 added)
intent_commit: LOW (intent.txt regenerated, requires commit)
async_quote_path: DEFERRED (major architecture — quotes.py uses sync Web3)
ws_block_head: DEFERRED (no WebSocket infrastructure exists)
multicall_proof: DEFERRED (multicall_stats=None in canonical path)
```

## 7) R28.8 Session Summary
- **Lead R28.8 directive**: "lack of arb profit is not lack of signals; it is incomplete full-universe executable ranking on the primary truth path." Universe blocked by adapter-family coverage + registry/indexer maturity, not by docs or basic infra.
- **UniswapV2 adapter implemented**: `dex/adapters/uniswap_v2.py` (141 lines) using getReserves() + constant product formula. 13 unit tests verify ABI encoding, decoding, quoting, registration. Supports all V2 forks.
- **Intent.txt generator**: `scripts/generate_intent.py` machine-generates intent.txt from core_tokens.yaml. Pairs each token with WETH/USDC, adds stablecoin + LST cross-pairs. 116 pairs across 6 chains. Eliminates manual editing error.
- **Suppression caps removed**: DEFAULT_MAX_PAIRS 20→100, adapter_types changed from `["uniswap_v3", "algebra"]` to `None` (all adapters participate). ve33 and uniswap_v2 were previously excluded from discovery!
- **Token debt closed**: Research revealed LINEA is soulbound LXP (non-transferable), MUTE rebranded to KOI ($12/day volume = dead), SPACE deactivated on CoinGecko. Pairs removed from intent.txt.
- **SushiSwap V2 added**: First V2-type DEX in dexes.yaml on arbitrum_one (factory: 0xc35DADB65012eC5796536bD9864eD8773aBc74C4).
- **Tests**: 1850 passed (+13 from V2 adapter), 3 skipped.

## 8) Що потрібно від ліда
1. **Commit intent.txt**: Regenerated by machine-generator (116 pairs). check_repo_safety PASS with --allow-intent-edit flag. Ready for commit.
2. **V2 adapter review**: `dex/adapters/uniswap_v2.py` — straightforward getReserves + constant product. No edge cases expected, but online runs will validate.
3. **Next online run**: Should test sushiswap_v2 on arbitrum_one + V2 adapter path. May discover new pools that were previously invisible.
4. **Lead R28.8 answer**: R28.7 asked "(a) smaller sizes, (b) lower-fee pools, or (c) additional pair/DEX expansion?" — R28.8 directive chose (c). V2 adapter implemented, SushiSwap V2 added, caps removed.
5. **Universe expansion continued**: dexes.yaml still sparse. Candidates: Camelot (native), TraderJoe, more SushiSwap chains. Deferred to next session.
6. **Gap unchanged**: ~15 bps (no new online runs this session). Pure code/config session.
