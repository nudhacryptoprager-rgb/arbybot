# STRATEGIC_PIVOT.md — Pivot from DEX-DEX Backrun to New-Pool Sniping

> **Status:** ACTIVE proposal — execution contract стає активним тільки через `Roadmap.md` + `docs/status/Status_M8.md`.
> **Origin:** Аналіз продукту після E1.83/E1.84 soaks (4 послідовних 30-хв–1-год прогонів
> із підтвердженим **FUNDAMENTAL_DISCOVERY_GAP** на bluechip парах Base).
> **Authority:** subordinate до `Roadmap.md`, `AGENTS.md`, `docs/DOCS_POLICY.md`.

---

## 1) Чому міняємо напрямок

### 1.1 Що показали soaks (E1.81 → E1.84)
- 6 factory-enriched пар на Base (USDC/WETH, CBBTC/WETH, AERO/WETH, CBBTC/USDC, VIRTUAL/WETH, AERO/USDC).
- Жоден з 4 soak-ів **не дав жодного scored deep-pair entry** з orderflow-event'ів на цих парах.
- Forced deep-pair sweep (E1.83) показав taxonomy: `no_event_triggered: 30/30` — це
  **не баг сканера**, а **відсутність публічного orderflow** на цих парах.

### 1.2 Структурні блокери поточної ніші (DEX-DEX backrun на bluechip)
| Блокер | Деталі |
|---|---|
| **Latency** | Public RPC (publicnode, mainnet.base.org) → 200–400 ms RTT. Топ MEV searchers — `bloXroute`/`Eden`/private relayers — <50 ms. |
| **Mempool blindness** | Бачимо лише підтверджені події. Searchers бачать pending tx через приватні mempool feeds (Flashbots Protect, Coinbase MEV-Share). |
| **Bundle access** | Base sequencer приймає bundles лише через whitelisted relayer-и. |
| **Capital efficiency** | $50–$1000 ордери vs USDC/WETH pool TVL ~$220M = 10⁻⁶ depth. Спред 0.5–2 bps, gas 1–3 bps → math не сходиться. |
| **MEV-effective pairs** | На factory-enriched парах prof. searchers ловлять window до того, як публічний RPC побачить tx. |

**Висновок:** на public infra + bluechip pairs у нас немає математичного шансу — це structural disadvantage, а не tuning problem.

---

## 2) Що зберігаємо (sunk cost — НЕ викидати)
- **Multi-chain factory enumeration** (`discovery/factory_enumeration.py`, `discovery/index_factories.py`).
- **`pool_family_truth.json`** — 78 пулів, 7 BASE-пар, 6 DEX-ів.
- **Cold/Hot lane architecture** + M7 supervisor (`scripts/start_nonstop_runtime.py`).
- **Discovery / quarantine / verify** pipeline.
- **Rolling artifacts** + dashboard + strict gates.
- **5136 passing unit tests**, contract enforcement.

**Reuse rate для нового напряму ≈ 70–75% коду.**

---

## 3) Цільові ніші — ranked matrix

| # | Ніша | Очікуваний P&L | Складність | Code reuse | Конкуренція | Пріоритет |
|---|---|---|---|---|---|---|
| 1 | **New-Pool Sniping (Aerodrome / Uniswap V3/V4 / Pancake on Base)** | $50–$300/день при $5–10k капіталу | Medium (1–2 тиж) | ~70% | Low–Medium | PRIMARY |
| 2 | **Liquidation MEV (Moonwell / Aave V3 / Seamless on Base)** | $100–$500/день | Medium-High (2–3 тиж) | ~50% | Medium | SECONDARY |
| 3 | **Stable-Stable peg arb (cbETH/WETH, USDC/USDbC, wstETH/ETH, eUSD/USDC)** | $20–$100/день baseline | Low (5–10 днів) | ~85% | Medium | ANCHOR |
| 4 | veAERO bribe/voting arb (Aerodrome ve(3,3)) | 5–20% APR на locked AERO | Medium (3–4 тиж) | ~30% | Very Low | EXOTIC |
| 5 | Uniswap V4 Hook MEV (custom hooks: LimitOrder, OracleHook, DynamicFee) | Unknown (alpha) | High (1–2 міс) | ~40% | Low (blue ocean) | EXOTIC |
| 6 | L2 Forced Inclusion / Sequencer arb (oracle update lag L1→L2) | $500–$5000/event, rare | Very High | ~25% | Low | EXOTIC |
| 7 | NFT floor arb Base ↔ Ethereum (Blur / Magic Eden) | $20–$200/event, 5–15/тиждень | Medium-High | ~10% | Low | EXOTIC |

---

## 4) Чому Primary = New-Pool Sniping

### 4.1 Edge mechanism
- Нова пара з'являється на Aerodrome (`PoolCreated` event) → є **5–30 хв window** до того, як arb-боти на Uniswap V3/V4 знайдуть її і вирівняють.
- Перші 100–1000 trades мають спред **50–500 bps** (vs 0.5 bps на bluechips).
- **Це не MEV-warfare** — це **first-mover discovery edge**.

### 4.2 Чому під наш код
- Ми **вже маємо** factory enumeration → треба перенаправити listener з swap events на pool-creation events.
- Multi-DEX scout + family truth → автоматично знаходять mirror pools.
- Quarantine pipeline → готовий для honeypot detection.

### 4.3 Очікувані P&L
| Період | Capital | Target net P&L | Confidence |
|---|---|---|---|
| Місяць 1 (paper + $200–500 live) | $500 | -$50 ... +$50 (learning) | High |
| Місяць 2 | $2,000 | $50–$200 / тиждень | Medium |
| Місяць 3 | $5,000 | $200–$500 / тиждень | Medium |
| Місяць 6 | $20,000 | $500–$2,000 / тиждень | Low (потребує iteration) |

Це planning hypothesis, не production claim. `goal_status: REACHED` дозволений тільки після fresh M8 runtime artifacts і capped-capital P&L evidence.

---

## 5) Roadmap — 6–8 тижнів

> **Детальний phase-by-phase guide** (проблеми, акценти, кроки, перевірки, критерії успіху): [`docs/step_pivot.md`](step_pivot.md)


### Phase 1 — Foundation (Тижні 1–2)
| # | Task | Owner | Status |
|---|---|---|---|
| 1.1 | `PoolCreated` / `PairCreated` event listener (Aerodrome PoolFactory, Uniswap V3/V4 Factory, Pancake) | dev | not-started |
| 1.2 | Honeypot detector (eth_call simulate: `transfer`, `balanceOf`, ownership, blacklist) | dev | not-started |
| 1.3 | Inventory module: USDC balance tracker + auto top-up | dev | not-started |
| 1.4 | Switch cold lane primary purpose: backrun-on-event → new-pool-watch | dev | not-started |
| 1.5 | New rolling artifact: `new_pool_sniper_latest.json` | dev | not-started |

### Phase 2 — Sniping Live (Тижні 3–4)
| # | Task | Owner | Status |
|---|---|---|---|
| 2.1 | Per-snipe exit strategy (TWAP, stop-loss, max-hold-blocks) | dev | not-started |
| 2.2 | Stable-stable pair list додано до scout (cbETH/WETH, USDC/USDbC, wstETH/ETH, eUSD/USDC) | dev | not-started |
| 2.3 | 24-hour paper soak: validate ≥1 successful snipe simulation + ≥2 stable-pair fills | qa | not-started |
| 2.4 | DEV_REPORT + Status оновлення | doc | not-started |

### Phase 3 — Production-Ready (Тижні 5–6)
| # | Task | Owner | Status |
|---|---|---|---|
| 3.1 | Real $200–$500 capital trial run | exec | not-started |
| 3.2 | Telemetry: per-snipe PnL, slippage realized vs predicted | dev | not-started |
| 3.3 | Backout policy: stop trading if 3 losses in row | dev | not-started |
| 3.4 | M8 execution gate (offline + online) | dev | not-started |

### Phase 4 — Scale (Тижні 7–8)
| # | Task | Owner | Status |
|---|---|---|---|
| 4.1 | Migrate to private RPC (Alchemy/QuickNode Growth tier) | infra | not-started |
| 4.2 | Add Flashbots Protect or Coinbase MEV-Share submission | exec | not-started |
| 4.3 | Scale capital: $500 → $2,000 → $10,000 gradually | exec | not-started |
| 4.4 | M8 close-out: 7 days continuous green | qa | not-started |

---

## 6) Що НЕ робимо (explicit non-goals)
- Не продовжувати backrun на USDC/WETH, CBBTC/WETH через public RPC — закрито як economics-blocked.
- Не лити $50k capital відразу — починаємо з $200–$500.
- Не заходити в public mempool MEV warfare на bluechip — структурний програш.
- Не реалізовувати >2 ніш одночасно — focus on Primary + Anchor.

---

## 7) Risk register

| Risk | Severity | Mitigation |
|---|---|---|
| New pools = 90% scam/honeypot | High | Honeypot detector + simulate `transfer` перед trade |
| Smart contract risk (нові pools з backdoor) | High | Source verification через explorer API як optional signal + bytecode similarity check; runtime gate має спиратись на on-chain calls |
| Capital lock у failed snipe | Medium | Hard `max_hold_blocks` + emergency-exit via TWAP |
| Mirror pool ніколи не з'являється | Medium | Exit-on-time стратегія (не чекати mirror, sell on liquidity peak) |
| Aerodrome bribe market не профітабельний | Low (Phase 4) | Phase 4 — не критичний path |

---

## 8) Success criteria (M8 close-out)
1. **Code:** new-pool listener в production, ≥3 DEX factory джерел.
2. **Tests:** ≥30 unit tests + ≥3 contract tests для honeypot detector.
3. **Paper soak:** 24h continuous, ≥5 simulated snipes, ≥1 з positive expected_profit_usd.
4. **Real trial:** ≥10 real snipes за 7 днів, net P&L ≥ $0.
5. **Stable anchor:** stable-stable trades згенерували ≥$20 net за 7 днів.
6. **Dashboard:** `/api/m8/sniper_current` endpoint з per-pool stats.

---

## 9) Decision log
- **E1.84 soak audit:** confirmed FUNDAMENTAL_DISCOVERY_GAP after 4 consecutive soaks; cold-lane event-reactive thesis economics-blocked on public infra → pivot recommended for M8 implementation.
- **Reference artifacts:** `data/runs/_rolling/m7_cold_hot_bridge.json`, `pool_family_truth.json`, останній E1.84 DEV_REPORT.
