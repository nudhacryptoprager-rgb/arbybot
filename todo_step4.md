# STEP 4: M7 Backrun — Path to Profit (2026-04-15)

## Strategic Context

Стратегічний аналіз (E1.17) порівняв три шляхи до профіту:
- **M7 Backrun (Base)**: gap ~2-10 bps, pipeline E2E proven, структурна перевага
- **Triangular (Base)**: код є, НІКОЛИ не тестувався, 3× gas, unknown gap
- **2-Leg DEX↔DEX**: gap 4.90 bps, FROZEN, жодного profitable roundtrip

**Рішення: M7 Backrun — однозначний переможець.**

### Production Funnel (5647 windows, Base)

| Stage | Count | Conversion |
|-------|-------|------------|
| events | 2539 | — |
| fast_scored | 876 | 34.5% |
| fast_positive | 59 | 6.7% |
| guard_passed | 51 | 86.4% |
| sim_attempted | 30 | 58.8% |
| sim_passed | 1 | 3.3% |
| submit_ready | 0 | — |

### Sim Error Histogram (30 attempts → 19 failures)

| Error | Count | Fix |
|-------|-------|-----|
| TOKEN_ADDRESS_UNKNOWN (token0_in/token1_in) | 12 | Phase 1.1: addr_to_symbol gap |
| DEX_CONFIG_MISSING (pool address as venue) | 6 | Phase 1.2: factory→dex lookup |
| STF revert (ve33 ABI mismatch) | 1 | Phase 2: ve33 calldata |
| SIGNING_NOT_READY | 1 | Phase 1.3: ARBY_PAPER_SIGNING=1 |

**60% sim errors = config gaps, not code bugs.**

---

## PHASE 1: Config Coverage + rpc_fork Switch (E1.17)
*Goal: Eliminate 18/30 config-caused sim failures + enable zero-infra simulation*

### [x] 1.1 Fix TOKEN_ADDRESS_UNKNOWN — addr_to_symbol населення
- **Проблема**: 12 sim failures — hot path бачить tokenі як `token0_in`/`token1_in` direction tags.
  `backrun_token_in_address` заповнений (адреса є!), але execution_gate fallback на
  `get_token_address(chain, "token0_in")` — і це природно фейлить.
- **Root cause**: `actual_pair` містить direction тоді коли `addr_to_symbol` не має символу.
  Але `backrun_token_in_address`/`backrun_token_out_address` вже populated!
- **Fix**: execution_gate.py — перевірити чи token_in_addr/token_out_addr вже є BEFORE symbol lookup
- **Impact**: TOKEN_ADDRESS_UNKNOWN 12 → 0

### [x] 1.2 Fix DEX_CONFIG_MISSING — pool→dex reverse lookup
- **Проблема**: 6 sim failures — `best_buy_venue` = pool address (0x765b..., 0xe4e9..., etc.)
  замість DEX name. Fallback iterates 4 configured DEXes but fails for unknown pools.
- **Root cause**: scoring path returns pool address when pool not in configured DEX set.
  execution_gate fallback already checks uniswap_v3/aerodrome/sushiswap/pancake but pool
  isn't in any of their factory registries.
- **Fix**: Add factory address matching via on-chain `factory()` call on pool contract,
  then map factory→dex_key using config/dexes.yaml factory addresses.
- **Impact**: DEX_CONFIG_MISSING 6 → ~0

### [x] 1.3 Switch sim backend: anvil → rpc_fork
- **Проблема**: production rollup shows `simulation_backend: "anvil"` — потребує Anvil process
  якого нема. rpc_fork backend (E1.16) працює на production RPC без зовнішньої інфри.
- **Fix**: Set `ARBY_SIM_BACKEND=rpc_fork` + `ARBY_PAPER_SIGNING=1` в env
- **Impact**: sim працює без Anvil; SIGNING_NOT_READY → submit_ready

### [x] 1.4 Validate — tests + quick scan
- `py -3.11 -m pytest tests/unit -q`
- Live scan 15 min з rpc_fork + paper signing
- **Target**: sim_attempted 30→51, sim_passed 1→~2+, submit_ready > 0

---

## PHASE 2: ve33 Calldata Encoder (E1.18)
*Goal: Unlock Aerodrome — dominant Base DEX (~40% volume)*

### [x] 2.1 Implement Velodrome/Aerodrome calldata builder
- **Проблема**: ve33 adapter uses `exactInputSingle` (Uniswap V3 ABI) → reverts on
  Velodrome Router (`0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43`)
- Velodrome Router API: `swapExactTokensForTokens(amountIn, amountOutMin, routes[], to, deadline)`
  де `routes` = `[(from, to, stable, factory)]`
- **File**: `m7/orderflow/execution_gate.py` — add `_encode_velodrome_swap()` alongside existing
  `_encode_exact_input_single()`
- **Impact**: Aerodrome pools перестануть STF-реvertити

### [x] 2.2 Add ve33 to rpc_fork_backend router dispatch
- **File**: `m7/orderflow/sim_backends/rpc_fork_backend.py` — currently only handles V3 calldata
- Add Velodrome router calldata path
- **Impact**: sim_attempted ↑ (all Aerodrome pools simulatable)

### [x] 2.3 Tests + validation
- Unit tests for velodrome calldata encoding
- Live scan with aerodrome pools included
- **Target**: STF errors → 0

---

## PHASE 3: Peak-Hours Production Soak (E1.19)
*Goal: First real submit_ready > 0 on production market*

### [ ] 3.1 Prepare env for peak soak
- `ARBY_SIM_BACKEND=rpc_fork`
- `ARBY_PAPER_SIGNING=1`
- `BASE_RPC=<drpc_url>` (premium, low latency)
- `BASE_WSS=<drpc_wss>` (premium WS)

### [ ] 3.2 Run 14:00-22:00 UTC soak (8 hours)
- Peak Base activity = more large swaps = better backrun margins
- Monitor rolling artifacts every 30 min
- **Target**: submit_ready ≥ 5, positive net_bps in at least 1 event

### [ ] 3.3 Analyze soak results
- Conversion rate at each funnel stage
- sim_passed/sim_attempted ratio with config fixes
- Identify remaining blockers (if any)

---

## PHASE 4: Flashblocks Integration (E1.20)
*Goal: Sub-block latency edge → cross gap-to-zero*

### [ ] 4.1 Flashblocks WS connection
- URL: `wss://mainnet-preconf.base.org` (app-level)
- Parse pre-confirmed block payloads for large swap events
- **Edge**: 200ms pre-confirmation → see swaps before other backrunners

### [ ] 4.2 Flashblocks → hot scoring pipeline
- Feed flashblock events into existing hot scoring path
- Same guard → sim → submit pipeline, just earlier data
- **Impact**: 1-2 bps latency advantage over non-flashblock competitors

### [ ] 4.3 Validate latency improvement
- Compare: standard WS vs flashblocks WS event-to-score latency
- **Target**: gap-to-zero crosses below 0 → net positive P&L

---

## PHASE 5: Triangular Exploration (E1.21, stretch)
*Goal: Diversification play — only AFTER Phases 1-4 proven*

### [ ] 5.1 Run triangular CLI on Base (diagnostic only)
- `m7/triangular/cli.py` already supports Base universe (8 tokens, 4 DEXes)
- Single diagnostic run to measure cycle economics
- **Gate**: proceed only if any cycle shows gap < 5 bps

### [ ] 5.2 Integrate triangular into hot pipeline (if viable)
- Wire `find_3hop_cycles()` + `score_cycle_measured()` into hot scoring
- 3× gas penalty makes this viable only for large dislocations

---

## SUCCESS METRICS

| Phase | Metric | Current | Target |
|-------|--------|---------|--------|
| 1 | sim errors from config gaps | 18/30 | 0/30 |
| 1 | sim_attempted | 30 | 51+ |
| 1 | submit_ready | 0 | ≥1 |
| 2 | STF reverts (ve33) | 1 | 0 |
| 2 | Aerodrome pools simulatable | 0 | all |
| 3 | submit_ready / 8h soak | 0 | ≥5 |
| 4 | event-to-score latency | ~2s | <200ms |
| 4 | net_bps (best) | negative | >0 |

---

## KEY INSIGHT

M7 Backrun має **структурну перевагу**: ми торгуємо ПІСЛЯ відомого price impact,
конкуруючи лише з іншими backrunners (не з усім MEV-пулом як у 2-leg/triangular).
60% поточних sim failures — це config gaps, а не market blockers.
Виправлення конфігу + rpc_fork + paper signing = перший submit_ready БЕЗ зміни коду pipeline.
