# Current Strategy Alignment

Цей документ фіксує поточне стратегічне вирівнювання без зміни `Roadmap.md`.

`Roadmap.md` залишається верхньорівневим source of truth. Цей файл лише пояснює, як поточні гілки `M8`, `M8_1` і `M9` складаються в одну операційну логіку.

## Активний Напрямок

Поточний головний напрямок:

`M9_GRAPH_LONG_TAIL_SHADOW`

Причини:
- stable-stable lanes надто ефективні для standalone edge;
- LST lanes не дали позитивного gross у доступних вікнах;
- single-pair gates є діагностикою, а не proof lane;
- graph search може комбінувати exotic і long-tail routes через кілька пар і venue;
- topology вже розблокована, але economics ще не доведена.

## Ролі Шарів

`M8`:
- new-pool listener і discovery layer;
- дає fresh pool hints і route candidates;
- не є standalone profit claim.

`M8_1`:
- config-driven inventory і diagnostics layer;
- дає active routes, quote health, coverage ranking, size frontier і pool quarantine;
- більше не є головною proof lane.

`M9`:
- graph-arb shadow layer;
- поточний головний кандидат для long-tail / exotic cycle discovery;
- topology працює, але economics заблокована через відсутність positive-gross cycles.

## Карта Evidence

Operational artifacts:
- `data/runs/_rolling/new_pool_sniper_latest.json`
- `data/runs/_rolling/m8_1_stable_anchor_latest.json`
- `data/runs/_rolling/m9_graph_latest.json`

Inventory artifacts:
- `data/tmp/m8_1_exotic_inventory_latest.json`
- `data/tmp/m9_shadow_inventory_with_gap_edges.json`

Status files:
- `docs/status/Status_M8.md`
- `docs/status/Status_M8_1.md`
- `docs/status/Status_M9.md`

## Поточне Читання Gates

`M8` listener gate:
- discovery infrastructure usable;
- profitable entries не доведені.

`M8_1` lane gates:
- inventory infrastructure usable;
- stable, LST і pair-level exotic lanes недостатні як standalone strategy proof.

`M9` graph gate:
- topology unlocked;
- quote quality достатня для shadow work лише умовно;
- economics gate не пройдений, доки немає positive-gross cycles.

## Production Policy

Real execution залишається вимкненим.

Перед будь-якою production discussion потрібні:
- positive-gross cycles у fresh multi-pair `M9` graph gate;
- router simulation для top positive cycles;
- gas, fee, slippage і token-basis breakdown;
- honeypot, transfer-tax, transfer-restriction і liquidity safety gates для long-tail tokens;
- repeated short gates зі стабільною positive economics;
- explicit human approval перед вимкненням kill switch.

## Deprecated Або Supporting Paths

Не вважати active profit proof:
- stable-stable two-leg arbitrage на Base;
- LST two-leg arbitrage на Base;
- single-pair gates як proof gates;
- old `M7` public-infrastructure backrun economics;
- standalone `M8` new-pool sniping без graph/risk/simulation confirmation.

## Наступне Операційне Правило

Discovery має бути спочатку широким, потім ranked, потім focused.

Правильний flow:
1. Розширити verified long-tail і exotic inventory.
2. Побудувати або оновити graph inventory.
3. Запускати короткі multi-pair graph sweeps.
4. Ранжувати cycles за gross, QSR, liquidity і cost sensitivity.
5. Симулювати лише cycles з positive gross або credible near-breakeven economics.
6. Тримати real execution disabled, доки production policy gates не пройдені.
