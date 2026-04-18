# SESSION: P1.1 — Aerodrome Slipstream Adapter (E1.35)

**Опенінг сесії.** Попередня сесія (E1.34) додала P0.1 (profile-aware sim backend API) + P1.2 (victim-filter env overrides). 30-хв Base soak пройшов штатно (29/29 PROD, 30/30 DISC, 0 crashes, 4094 unit tests PASS). Домінуючий blocker у DISC histogram: `PRE_SIM_SKIP:UNSUPPORTED_FEE_TIER:2655 = 66 (≈89%)`. Це адреси Aerodrome CL (Slipstream) пулів з tickSpacing-driven fees.

---

## Мета сесії

Додати adapter `aerodrome_slipstream`, який розуміє **Aerodrome Slipstream (CL) пули** на Base та генерує валідний swap calldata, щоб пули з tickSpacing-driven fees (150, 445, 600, 1000, 2105, 2655, 3024, 5000, 20000) перестали давати `UNSUPPORTED_FEE_TIER:AERODROME_CL:*` і потрапляли у sim/submit-ready pipeline.

**Очікуваний ефект:**
- `UNSUPPORTED_FEE_TIER:AERODROME_CL` падає з 60-89% на <5%
- `sim_attempted / scored` зростає 2-5×
- Створює умови для появи першого `roundtrip_profitable > 0` (якщо ринок дозволяє)

---

## Точки входу (файли)

### Нове
- `dex/adapters/aerodrome_slipstream.py`  
  AdapterType="aerodrome_slipstream"; protocol mixin — clone з `uniswap_v3.py`, замінити:
  - Factory: `0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A` (Base Slipstream CL factory)
  - PositionManager / SwapRouter adresses — перевірити у `docs/DEV_REPORT_LATEST.md` requests або офіційних доках Aerodrome: https://aerodrome.finance/docs/protocol/concentrated-liquidity
  - Pool ABI: `tickSpacing()` замість `fee()`
  - Calldata: `exactInputSingle(...)` але з `tickSpacing` у path замість `fee` (bytes3 → adjusted)

- `tests/unit/test_aerodrome_slipstream_adapter.py`  
  - pool decode з tickSpacing=2655
  - calldata build для WETH→USDC через Slipstream
  - registry lookup повертає `adapter_type="aerodrome_slipstream"` для Slipstream пула

### Правки
- `config/dexes.yaml` — нова секція:
  ```yaml
  base:
    aerodrome_slipstream:
      factory: "0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A"
      router:  "0xBE6D8f0d05cC4be24d5167a3eF062215bE6D18a5"   # verify!
      adapter_type: aerodrome_slipstream
      fee_tiers:  [100, 500, 3000, 10000]   # не використовується, але поле required
  ```

- `dex/registry.py` — додати enum/mapping `aerodrome_slipstream` → adapter class.

- `m7/orderflow/execution_gate.py`, ~lines 275-305:
  Блок `_AERODROME_CL_KNOWN` вже визначає знайомі tickSpacing. Коли `dex_cfg` для `aerodrome_slipstream` знайдено, НЕ повертати `UNSUPPORTED_FEE_TIER:AERODROME_CL:*`, а побудувати calldata через новий adapter.

- `execution/gas_estimate.py::build_exact_input_single_calldata` — додати варіант для Slipstream (path encoding з tickSpacing).

---

## Перевірки перед стартом

1. Прочитати офіційну документацію Aerodrome CL (Slipstream):
   - https://aerodrome.finance/docs/protocol/concentrated-liquidity
   - https://github.com/velodrome-finance/slipstream (fork of Uniswap V3)
2. Отримати канонічні адреси Router/Factory для Base mainnet.
3. Прочитати, як відрізняється path encoding від стандартного UniV3.
4. Підтвердити через `cast call <pool_addr> "tickSpacing()(int24)"`, що `2655` реально виникає для живих Slipstream пулів (може бути не tickSpacing, а pool-specific fee — треба розібратися).

---

## Додатково (pre-P1.1 subprocess-wiring fix, 15-хв)

Перед стартом P1.1 зробити коротку правку, щоб runtime дійсно використовував `ARBY_SIM_BACKEND_DISC`:

- `scripts/start_nonstop_runtime.py` — DISC subprocess `env["ARBY_SIM_BACKEND"] = os.environ.get("ARBY_SIM_BACKEND_DISC", os.environ.get("ARBY_SIM_BACKEND"))`  
- Альтернатива: у `m7/orderflow/cli.py` додати `--profile {production,discovery}` і виставляти `ARBY_SIM_BACKEND` зі specific override перед запуском gate.
- +2 unit tests.

Це усуне `HTTP 403` histogram entries під час наступного soak і виконає P0.1 до кінця.

---

## Exit-критерії сесії E1.35

- [ ] `aerodrome_slipstream` adapter створено + зареєстровано
- [ ] `config/dexes.yaml` оновлено, адреси перевірено онлайн
- [ ] Не менше 5 нових unit tests, всі PASS
- [ ] Повний pytest ≥ 4094 passed, 0 failed
- [ ] 30-хв soak (Base prod + discovery) з `ARBY_SIM_BACKEND_DISC=rpc_fork`:
  - `UNSUPPORTED_FEE_TIER:AERODROME_CL:*` сумарно падає з ~70 до ≤5 у histogram
  - `simulation_backend` у DISC rollup = `rpc_fork`, 0× HTTP 403
  - `sim_attempted_total` ≥ 200 у DISC (раніше 74)
- [ ] DEV_REPORT_LATEST.md оновлено (canonical template)
- [ ] Status_M7.md отримує E1.35 header (superseding E1.33)

---

## Out-of-scope (не чіпати у E1.35)

- P2.1 Atomic arb contract (потребує ендо-to-end market verification після P1.1)
- P3.1 MEV-Share pivot (тільки якщо після P0+P1 completion `roundtrip_profitable_total` досі == 0)
- Рефактор scoring_parallel.py (не чіпати без явної потреби)
- `config/intent.txt` (не редагувати без `--allow-intent-edit`)

---

## Джерела

- Aerodrome CL docs: https://aerodrome.finance/docs/protocol/concentrated-liquidity
- Slipstream repo: https://github.com/velodrome-finance/slipstream
- Base fee-tier evidence: E1.34 soak histogram (data/runs/_rolling/m7_hot_rollup_latest_discovery.json)
