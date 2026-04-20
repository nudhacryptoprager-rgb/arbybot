# STEP 4 (E1.34+): M7 Production-Readiness Roadmap — Post-E1.33

## Контекст

Попередні пункти Phase C (E1.27: sim_profit_bps / revert decode / PREWARM expansion)
**вичерпано**:
- C1 `sim_profit_bps/wei` — реалізовано і потім відкочено у E1.33 D1 через
  cross-decimals bogus bps (буй-легу WETH(18d)→USDC(6d) давав -9999 bps).
  Single-leg profit_bps семантично некоректний; замість нього введено
  `ROUNDTRIP_*` truth contract.
- C2 revert decode — реалізовано у `m7/orderflow/sim_backends/rpc_fork_backend.py::_decode_revert_reason` (Error(string) + Panic(uint256)).
- C3 PREWARM expansion — виконано через E1.30 intent-driven prewarm
  (`PREWARM_PAIRS_BASE` + `PREWARM_PAIRS_BASE_DISCOVERY` + dynamic loader).
- Phase S (3h soak) — виконано кілька раз; підтверджено пайплайн стабільний,
  але `roundtrip_profitable_count=0` за ~3.3k windows → ринок/latency-blocked,
  а не код-blocked.
- Phase A (execution wiring) — **заблоковано** GO-gate: `sim_profit_bps_best > 0`
  так і не досягнуто жодного разу. Виконання не вмикаємо, поки не усунено
  latency/economics bottleneck.

Поточна блокуюча реальність (Status_M7, rolling window 200):
- `sim_passed=29 / submit_ready=29 / roundtrip_profitable=0` (PROD)
- `simulation_error_histogram` дoмінує `PRE_SIM_SKIP:UNSUPPORTED_FEE_TIER:2655`
- DISC lane періодично 4× Tenderly HTTP 403
- `ws_lag` ~2s (через `newHeads`), flashblocks (200ms) не використовуються у hot loop

---

## Новий план: Path to Net-Positive Roundtrip

### P0 — Blocker Elimination (обов'язково, ROI миттєвий)

#### P0.1. DISC lane: усунути Tenderly 403 → rpc_fork/anvil за замовчуванням
- **Мета:** `ARBY_SIM_BACKEND` має бути profile-aware: дозволити DISC використовувати `rpc_fork/anvil` без зміни PROD-бекенда.
- **Файли:**
  - `m7/orderflow/simulation.py::get_simulation_backend(profile: Optional[str] = None)` — додати optional argument; читати `ARBY_SIM_BACKEND_DISC` коли `profile="discovery"` (fallback на `ARBY_SIM_BACKEND`).
  - `m7/orderflow/execution_gate.py::run_execution_gate(..., profile: str = "prod")` — прокинути профіль у селектор.
  - `tests/unit/test_sim_backend_profile.py` — 3 кейси (default, DISC override, unknown override fallback).
- **Критерій:** `run_summary_latest.json.m7_lane_config.discovery.sim_backend` збігається з `ARBY_SIM_BACKEND_DISC`, коли виставлено.
- **Ризики:** мінімальні (back-compat: без profile — стара поведінка).

#### P0.2. Flashblocks 200ms pre-confirmation як primary event source
- **Мета:** замінити `newHeads` (2s) на Base flashblocks (200ms) у hot loop → 10× зменшення `ws_lag`.
- **Джерело:** https://docs.base.org/base-chain/flashblocks/app-integration
- **Файли:**
  - `m7/orderflow/event_source.py` (або аналог): додати `FlashblocksSource` (WS до `wss://mainnet-preconf.base.org/ws`), feature-flag `ARBY_FLASHBLOCKS_PRIMARY=1`.
  - `m7/shared/constants.py`: `FLASHBLOCKS_ENDPOINT_BASE`.
  - Тести: фіктивний WS server → подає 10 flashblocks → `event_source.iter_events()` повертає 10 окремих `preconf_block_N` подій.
- **Критерій:** `ws_lag_ms_median < 500` замість `~2000` у наступному soak.
- **Залежить від:** `ARBY_FLASHBLOCKS_HTTP` уже є у env (Status_M7 line 115).

---

### P1 — Signal Quality (ROI високий, зусилля середнє)

#### P1.1. Fee-tier extension: Aerodrome Slipstream + Algebra Dynamic
- **Мета:** усунути `PRE_SIM_SKIP:UNSUPPORTED_FEE_TIER:2655` (60%+ events).
- **Файли:**
  - Новий `dex/adapters/aerodrome_slipstream.py` (CL pools з tickSpacing-driven fees: 150/445/600/2105/2655/3024).
  - `dex/registry.py`: зареєструвати `aerodrome_slipstream` adapter_type.
  - `execution/gas_estimate.py::build_exact_input_single_calldata` — підтримати fee-as-tickSpacing.
  - `tests/unit/test_aerodrome_slipstream.py` — базові кейси.
- **Критерій:** `UNSUPPORTED_FEE_TIER:AERODROME_CL:*` падає з 60% до <5% у rolling.
- **Ризики:** середні — router calldata може відрізнятись; треба verify по одному pool.

#### P1.2. Victim-filter tightening
- **Мета:** pre-filter у `scoring_parallel.py`: `notional_usd > ARBY_VICTIM_MIN_USD` (default $10k) AND `price_impact_bps > ARBY_VICTIM_MIN_IMPACT_BPS` (default 15).
- **Файли:**
  - `m7/orderflow/scoring_parallel.py`: додати pre-scoring фільтр `_victim_size_filter()`.
  - `m7/shared/constants.py`: `VICTIM_MIN_USD_DEFAULT = 10_000`, `VICTIM_MIN_IMPACT_BPS_DEFAULT = 15`.
  - Тести: малий swap ($1k) → rejected з `REJECT:VICTIM_TOO_SMALL`; великий → pass.
- **Критерій:** `scored_count` падає ~2-5×, але `positive_count / scored_count` зростає (signal-to-noise).

---

### P2 — Execution Atomicity (ROI високий, зусилля велике, BLOCKED на P0/P1)

#### P2.1. Atomic arb contract (flashloan-based)
- **Мета:** замінити 2 sequential swap tx на 1 atomic tx із Balancer/Aave 0-fee flashloan.
- **Референс:** https://github.com/flashbots/simple-arbitrage
- **Компоненти:**
  - Solidity contract `contracts/ArbyBackrun.sol` (Foundry project):
    - `executeBackrun(bytes calldata buyLeg, bytes calldata sellLeg, uint256 minProfit)` з flashloan callback.
    - Revert if `net < minProfit`.
  - `execution/atomic_bundler.py`: build calldata для `executeBackrun`.
  - Testnet deployment (Base Sepolia) + unit test via `forge test`.
- **Критерій:** 1 успішна testnet transaction з `gasUsed < 220_000` (замість ~400k для 2 tx).
- **Блокується на:** P0.1, P0.2, P1 (spending effort до того як ринок підтвердить edge — premature).

#### P2.2. Private tx pool integration
- **Мета:** `eth_sendPrivateTransaction` через Alchemy/bloXroute для Base → захист від front-run.
- **Файли:**
  - `execution/private_tx.py::submit_private(tx_signed: str, rpc: str)`.
  - Wire в `loop_runner.py` коли `ARBY_PRIVATE_TX=1`.
- **Критерій:** інтеграційний тест на testnet → tx з'являється в блоці без public mempool visibility.

---

### P3 — Strategy Pivot Fallback (якщо P0+P1 не дають net-positive)

#### P3.1. Mainnet MEV-Share searcher (окремий lane, M8 scope)
- **Умова активації:** 1000+ windows після P0+P1 і `roundtrip_profitable_total == 0`.
- **Суть:** пiдписка на `wss://mev-share.flashbots.net`, `mev_sendBundle` на mainnet.
- **Референс:** https://docs.flashbots.net/flashbots-mev-share/searchers/getting-started
- **Виключено з M7** — формально M8; документую як fallback, не робимо цієї ітерації.

---

## Послідовність виконання (наступні ітерації)

| Крок | Item | Зусилля | Статус |
|------|------|---------|--------|
| 1 | P0.1 profile-aware sim backend | XS | ✅ DONE (E1.34) |
| 2 | P0.2 Flashblocks WS source | M | ✅ PRE-EXISTED (m7/orderflow/mode_ws_live.py + chains/flashblocks.py — wired, з fallback) |
| 3 | P1.2 victim-filter (env overrides) | S | ✅ DONE (E1.34) |
| 4 | P1.1 Aerodrome Slipstream adapter | L | **NEXT** |
| 5 | P2.1 Atomic contract (gated на P0+P1 success) | XL | blocked |
| 6 | P3.1 MEV-Share pivot (gated на no-profit verdict) | XL | blocked |

---

## Success Metrics (оновлено)

| Metric | Baseline (E1.33) | P0 Target | P1 Target | P2 Target |
|--------|------------------|-----------|-----------|-----------|
| `ws_lag_ms_median` | ~2000 | <500 | <500 | <500 |
| `UNSUPPORTED_FEE_TIER` share | 60% | 60% | <5% | <5% |
| `sim_attempted / scored` | 99/4456 (2.2%) | 99/4456 | ~50/1000 | ~50/1000 |
| `roundtrip_profitable_total` | 0 | 0 (diagnostic) | >0 (target) | >0 (stable) |
| Tenderly HTTP 403 (DISC) | 4× / 200 runs | 0 | 0 | 0 |
| `sim_net_usdc_best` | negative | negative | >0 | ≥$1 |

---

## Guard-rails (не порушувати)

- `execution_enabled=false`, `kill_switch_active=true` зберігаються до P2 completion + Lead approval.
- `config/intent.txt` — не редагувати без `--allow-intent-edit` (AGENTS.md).
- Ніяких великих рефакторингів під час падіння тестів.
- Усі зміни — мінімальні, backward-compatible, з юніт-тестом.
- Docs: тільки overwrite `docs/DEV_REPORT_LATEST.md`, без версіонування.

---

## Зовнішні джерела (grounding для P0/P1/P2)

- Base Flashblocks: https://docs.base.org/base-chain/flashblocks/app-integration
- Flashbots RPC & bundles: https://docs.flashbots.net/flashbots-auction/searchers/advanced/rpc-endpoint
- Post-merge searching: https://writings.flashbots.net/searching-post-merge
- Reference atomic arb: https://github.com/flashbots/simple-arbitrage
- Self-hosted rbuilder/sim: https://github.com/flashbots/rbuilder

---

## KEY INSIGHT

E1.33 довело: код-шлях стабільний, truth-invariant консистентний, але
**net-positive не досягається через комбінацію latency (newHeads 2s) + fee-tier miss (60% events) + Tenderly credit limits**.
P0+P1 усувають усі три блокери одночасно. Якщо після цього roundtrip_profitable_total залишається 0 —
це **ринковий висновок** (Base hot lane FCFS + no privileged ordering), не код-проблема, і
легітимний trigger для P3 (mainnet MEV-Share pivot).

Ітерація E1.34 = **P0.1 (profile-aware sim backend)** — наступний коміт.
# STEP 4: Path to Proven Profitability + Execution (E1.27, 2026-04-16)

## Стратегічний контекст

**E1.26 досягнення** (pipeline breakthrough):
- DISC: sim_passed=2, submit_ready=2 (перший раз в історії проекту)
- DISC positive: 7/559 events (1.3% hit rate)
- PROD: positive=0 (всі знахідки лише в discovery)
- Sim revert rate: 71% (5/7 "execution reverted")
- Код зрілості: 85% infra, 90% safety, 90% sim — але 0% proven profit

**Ключове питання**: Чи 2 sim_passed дійсно прибуткові? Без відповіді wiring execution безглуздий.

### Поточний Production Funnel (E1.26 soak 30 min)

| Stage | PROD | DISC |
|-------|------|------|
| events | 557 | 559 |
| bridge_hits | 205 | 183 |
| registry_miss% | 41.0% | 25.1% |
| scored | 55 | 42 |
| positive | 0 | **7** |
| sim_attempted | 0 | **7** |
| sim_passed | 0 | **2** |
| submit_ready | 0 | **2** |
| sim_errors | — | 5 ("execution reverted") |

---

## PHASE C: Proven Profitability (E1.27)

### C1. Sim Profit Extraction — дізнатися P&L кожного sim_passed

**Проблема**: `sim_passed` = "swap не reverted" ≠ "прибуткова угода". `SimulationResult` повертає `output_amount_wei`, але ніхто не порівнює з `input_amount_wei`. Ми не знаємо, чи 2 sim_passed дали +3 bps або -5 bps.

**Файли**:
- [ ] `m7/orderflow/sim_backends/rpc_fork_backend.py` — додати `sim_profit_wei`, `sim_profit_bps` в `SimulationResult`
- [ ] `m7/orderflow/execution_gate.py` — після sim_passed: зберегти `sim_profit_bps` в `BackrunResult`
- [ ] `m7/orderflow/hot_runtime_artifacts.py` — додати в rollup: `sim_profit_bps_median`, `sim_profit_bps_best`, `sim_profitable_count`
- [ ] `tests/unit/test_rpc_fork_backend.py` — тест sim_profit_bps обчислення

**Формула**:
```python
sim_profit_wei = output_amount_wei - input_amount_wei
sim_profit_bps = (sim_profit_wei / input_amount_wei) * 10000
```

**Перевірка**: Soak 30 хв → rolling показує `sim_profit_bps` для кожного sim_passed
**Exit**: Знаємо точний P&L кожної симуляції

---

### C2. Revert Reason Diagnosis — 71% revert → <30%

**Проблема**: 5/7 sim_attempted дають generic "execution reverted". Не зрозуміло: SLIPPAGE (stale price) vs LIQUIDITY (pool empty) vs ABI mismatch vs інше.

**Файли**:
- [ ] `m7/orderflow/sim_backends/rpc_fork_backend.py` — decode revert data: `Error(string)` selector `0x08c379a0`, `Panic(uint256)` selector `0x4e487b71`
- [ ] `m7/orderflow/execution_gate.py` — передавати decoded reason замість raw "execution reverted"
- [ ] `m7/orderflow/hot_runtime_artifacts.py` — `simulation_error_histogram` з decoded reasons (не generic)

**Класифікація**:
| Revert | Причина | Дія |
|--------|---------|-----|
| "Too little received" / "Insufficient output" | SLIPPAGE — stale price між scoring і sim | Зменшити затримку або збільшити tolerance |
| "Too old" / "Transaction too old" | DEADLINE — calldata deadline expired | Збільшити deadline |
| "SPL" / Panic(0x11) | LIQUIDITY — overflow/underflow | Фільтрувати пули по TVL |
| Empty revert / unknown | ABI mismatch | Перевірити calldata encoding |

**Перевірка**: Histogram показує конкретні reasons замість generic "execution reverted"
**Exit**: Знаємо root cause 71% revert rate → конкретний action plan

---

### C3. DISC→PROD Pool Promotion — PROD positive > 0

**Проблема**: Discovery знаходить 7 positive, PROD знаходить 0. DISC сканує 7 пар, PROD — ті самі 7, але різний universe пулів через discovery lane. config/intent.txt має 42 пари, але M7 hot loop використовує хардкожений `PREWARM_PAIRS_BASE`.

**Файли**:
- [ ] `m7/shared/constants.py` — розширити `PREWARM_PAIRS_BASE` парами з intent.txt (7→20+)
- [ ] `m7/orderflow/loop_runner.py` — (якщо потрібно) dynamic pair loading з config/intent.txt
- [ ] `tests/unit/test_e1_9_discovery_lane.py` — оновити очікувану кількість пар

**Стратегія**: Не автоматичний promotion, а розширення PROD universe до рівня DISC. Якщо DISC бачить сигнали на парах X — додати X в PROD.

**Перевірка**: PROD pipeline з розширеними парами → PROD positive > 0
**Exit**: PROD і DISC мають однакове покриття → PROD positive > 0

---

## PHASE S: 3-годинний Production Soak (E1.27.S)

### S1. Підготовка
- [ ] Всі зміни C1-C3 merged + тести зелені
- [ ] ENV: `ARBY_SIM_BACKEND=rpc_fork`, `ARBY_PAPER_SIGNING=1`, `ARBY_HOT_STALE_BLOCKS=150`
- [ ] ENV: `ARBY_FLASHBLOCKS_SIM=1`, `ARBY_FLASHBLOCKS_HTTP=https://mainnet-preconf.base.org`
- [ ] ENV: `BASE_RPC=https://mainnet.base.org`, `BASE_WSS=wss://base-rpc.publicnode.com`

### S2. Запуск 3-годинного soak
- [ ] `py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 3 --with-discovery --no-m4`
- [ ] Моніторинг кожні 30 хв: rolling artifacts, dashboard

### S3. Аналіз після soak
- [ ] Перевірити `sim_profit_bps_best` — чи є ХОЧА Б ОДИН позитивний
- [ ] Перевірити revert histogram — які decoded reasons домінують
- [ ] Перевірити PROD positive — чи з'явились після promotion
- [ ] Порівняти з E1.26 baseline: sim_passed, submit_ready, positive counts
- [ ] **GO/NO-GO рішення**: якщо sim_profit_bps > 0 → переходити до A1 (execution wiring)

---

## PHASE A: Execution Wiring (E1.28, тільки якщо Phase S = GO)

### A1. Wire `sign_and_send` — підключити реальний підпис

**Передумова**: Phase S підтвердив sim_profit_bps > 0 хоча б для 1 транзакції.

**Файли**:
- [ ] Створити `execution/signer.py`:
  ```python
  async def make_signer(chain: str) -> Callable[[dict], str]:
      key = os.environ["ARBY_PRIVATE_KEY"]  # або keystore JSON
      account = Account.from_key(key)
      async def sign_and_send(tx_dict: dict) -> str:
          signed = account.sign_transaction(tx_dict)
          tx_hash = await provider.send_raw_transaction(signed.raw_transaction)
          return tx_hash.hex()
      return sign_and_send
  ```
- [ ] `execution/private_tx.py` — Base Flashbots Protect RPC submission:
  ```python
  # POST eth_sendRawTransaction до https://rpc.flashbots.net/base
  # Це 1 HTTP виклик — не потрібен bundle builder для Base
  ```
- [ ] Wire в `m7/orderflow/loop_runner.py`: submit_ready → execute_live()
- [ ] Тест на Base Sepolia testnet

**Перевірка**: Unit test з web3 Account.from_key → sign → verify
**Exit**: Перша реальна транзакція на testnet

---

## SUCCESS METRICS

| Phase | Metric | Baseline (E1.26) | Target |
|-------|--------|-------------------|--------|
| C1 | sim_profit_bps known | ❌ unknown | ✅ known for every sim_passed |
| C2 | revert reasons decoded | 0% | 100% (no generic "execution reverted") |
| C2 | revert rate | 71% (5/7) | <40% |
| C3 | PROD positive | 0 | ≥3 |
| C3 | PROD pairs | 7 | 20+ |
| S | sim_profitable_count | unknown | ≥1 (GO) or 0 (NO-GO) |
| S | sim_profit_bps_best | unknown | >0 (GO condition) |
| S | 3h stability | 30 min proven | 3h 0 restarts |
| A1 | sign_and_send wired | ❌ paper only | ✅ testnet proven |

---

## GO/NO-GO GATE (після Phase S)

| Condition | GO → Phase A | NO-GO → Pivot |
|-----------|-------------|---------------|
| sim_profit_bps_best > 0 | ✅ Wire execution | Diagnose: чому profitable scoring → unprofitable sim |
| revert_rate < 40% | ✅ Continue | Focus: fix dominant revert reason |
| PROD positive > 0 | ✅ Expand | Widen universe further |
| 3h soak stable | ✅ Production-ready infra | Fix crash/restart issues first |

**Якщо NO-GO**: Альтернативний шлях — Flashblocks timing edge (200ms preconf submission) або cross-chain arb (M8).

---

## KEY INSIGHT

Ми на порозі відповіді на головне питання проекту: **чи є реальний profit у M7 backrun?**
Phase C дасть конкретні числа (sim_profit_bps), Phase S дасть статистичну значимість (3 години),
Phase A дасть реальне виконання (перша tx на testnet).
Без C1 (profit extraction) все інше — гадання.

---

## 2026-04-20 AUDIT CYCLE UPDATE (team-lead, post-E1.36)

### Repo-gate resolution (10 critical issues from team-lead)

| # | Issue | Status | Action taken |
|---|---|---|---|
| 1 | `check_repo_safety.py` FAIL on INTENT_TIER_LIMIT 42>51 | ? RESOLVED | Baseline bumped 42>51 (E1.30/E1.31 productive+calibration approved expansion); test updated. |
| 2 | `pytest` red: 2 failures from `soak_*.log` in `_rolling` | ? RESOLVED | Removed stray `soak_e136_30min.log`; 4174 passed / 6 skipped. |
| 3 | Real-money execution not enabled | ? CORRECT (safety) | Keep `execution_enabled=false, kill_switch_active=true` until `roundtrip_profitable_total>0`. |
| 4 | M4 online profit not proven (`profit_realism_status=ROUNDTRIP_NOT_PROFITABLE`) | ?? KNOWN | Truth contract honest; offline `--strict` PASS (sim=2, net=0.5 USDC). Online profit requires a market window AND state-override validation (E1.36). |
| 5 | M4 rolling quality = `WARN_QUALITY` (`FRAGILE_P90_ELEVATED`) | ?? MONITOR | Not a blocker for truth contract; add P90 stability investigation later. |
| 6 | Long-scan `total_profitable_roundtrips=0` | ?? KNOWN | Same root cause as #4; expand revert decode + widen universe per Phase B below. |
| 7 | M7 fresh runtime: PROD `guard=0`, `sim_attempted=0` | ?? KNOWN | Quiet-market window (2026-04-20). Repeat soak on busier window / anvil backend. |
| 8 | M7 mixed backend by lane (PROD=tenderly, DISC=rpc_fork) | ?? DOCUMENT | Intentional (`ARBY_SIM_BACKEND_DISC`) � document as declared policy in Status_M7 before next soak. |
| 9 | M7 infra noise: 23/61 `session_http_fallback_windows` | ?? ACCEPT | dRPC intermittent fallback to publicnode; expected on paid-tier exhaustion. |
| 10 | `Status_M7.md` = 459 > 300 lines | ? RESOLVED | Archived verbose E1.24/E1.26/E1.27/E1.28/E1.29/E5/N1+N5 blocks to `archive/status/Status_M7_history.md`; Status_M7.md = 143 lines. |

### Green-gate re-run evidence (2026-04-20)

`
py -3.11 scripts/check_repo_safety.py          > PASS (0 warnings)
py -3.11 -m pytest tests/unit -q               > 4174 passed / 6 skipped
py -3.11 scripts/ci_full_pipeline.py --mode ci > ALL REQUIRED GATES PASSED
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict
                                               > PASS sim=2, net=0.5 USDC
`

### Remaining production blockers (ordered by ROI)

1. **Expand revert decoding** beyond 62 chars; cover `Error(string)`, `Panic(uint256)`, custom selector table. Blocks diagnosis of `REVERT:unknown` (1 observed on DISC lane 2026-04-20).
2. **Validate E1.36 state-override on PROD** � fresh 30-min Base soak with a busier market window, unified backend (anvil local fork or rpc_fork). Require at least 1 `sim_attempted` on PROD lane.
3. **Widen size-sweep upper bound** � 10 events rejected `fast_score_rejected_economics` and 5 `matched_then_gas_rejected` on a size that is too small vs. gas.
4. **Registry rehydrate for family_unresolved** (4/71 bridge-selected pools have `family_unresolved` > missed scoring opportunities).
5. **Bridge pool widening for BNKR/WETH-class "cold hot"** � `cold_net_bps=764` but `hot_events_seen=0` shows scoring identifies profit while event capture misses victims.
6. Only after items 1�5 yield `roundtrip_profitable_total>0` on PROD: canary `\�30` live tx on M8 (small WETH/USDC 500-tier).

### Hard rule (from `AGENTS.md` �4)

Do NOT claim production-ready while `profit_realism_status=ROUNDTRIP_NOT_PROFITABLE` or `profitable_roundtrips=0`. Offline gate PASS is infrastructure-level evidence only.

