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
