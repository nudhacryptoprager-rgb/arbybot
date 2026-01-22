# Status_M2.1.md — Registry-Driven Pipeline

**Дата:** 2026-01-11  
**Milestone:** M2 → M3 Bridge (Registry Integration)  
**Статус:** ✅ **COMPLETE**

---

## 1. Ключова зміна: Smoke → Registry

| Режим | Опис | CLI Flag |
|-------|------|----------|
| SMOKE | WETH/USDC only (demo/test) | `--smoke` |
| REGISTRY | intent.txt → pool candidates | `--use-registry` (default) |

**Pipeline:**
```
intent.txt → IntentParser → IntentPairs
    → TokenResolver (core_tokens.yaml) → ResolvedPairs
    → PoolRegistry (dexes.yaml) → PoolCandidates
    → Scanner (quotes + gates + spreads)
```

---

## 2. Registry Statistics (real run)

```
Parsed 106 pairs from intent.txt
Resolved 35 pairs (core_tokens only)
Generated 88 pool candidates

Breakdown by chain:
- Arbitrum: 16 pools (2 pairs × 2 DEXes × 4 fees)
- Linea: 24 pools (6 pairs × 1 DEX × 4 fees)
- zkSync: 20 pools (5 pairs × 1 DEX × 4 fees)
- Base: 28 pools (7 pairs × 1 DEX × 4 fees)
```

---

## 3. Нові файли

### discovery/registry.py

```python
class IntentParser:
    """Parse intent.txt → list[IntentPair]"""

class TokenResolver:
    """Resolve symbols via core_tokens.yaml → Token"""

class PoolRegistry:
    """Generate pool candidates per DEX/fee tier"""
    
    def load_intent(intent_path) -> int
    def generate_pool_candidates() -> list[PoolCandidate]
    def get_candidates_for_chain(chain_key) -> list[PoolCandidate]
```

### tests/unit/test_registry.py

12 tests covering:
- IntentParser (parse, comments, pair_id)
- TokenResolver (resolve token/pair, unknown)
- PoolRegistry (load, generate, filter, summary, priority)

---

## 4. CLI Changes

```bash
# REGISTRY mode (default, production)
python -m strategy.jobs.run_scan --chain arbitrum_one --once --use-registry

# SMOKE mode (testing only)
python -m strategy.jobs.run_scan --chain arbitrum_one --once --smoke
```

---

## 5. Snapshot Changes

```json
{
  "mode": "REGISTRY",  // was "harness": "SMOKE_WETH_USDC"
  "cycle_summaries": [{
    "mode": "REGISTRY",
    "planned_pools": 16,  // From registry, not hardcoded
    ...
  }]
}
```

---

## 6. Тести

**152 passed ✅** (140 existing + 12 registry)

```bash
pytest tests/unit/ -v
```

---

## 7. Registry Snapshot

Saved to `data/registry/registry_{timestamp}.json`:

```json
{
  "timestamp": "2026-01-11T...",
  "summary": {
    "total_resolved_pairs": 35,
    "total_pool_candidates": 88,
    "chains": {
      "42161": {"pairs": ["WETH/USDC", "WETH/WBTC"], "dexes": ["uniswap_v3", "sushiswap_v3"], "pools": 16},
      "59144": {"pairs": [...], "pools": 24},
      ...
    }
  },
  "resolved_pairs": [...],
  "pool_candidates": [...]
}
```

---

## 8. Unresolved Pairs

71 pairs не резолвнуто бо токени відсутні в `core_tokens.yaml`:
- ARB, GMX, LINK, UNI, wstETH, rETH, RDNT, MAGIC, etc.

**Next step:** Динамічний discovery (DexScreener API або factory contracts).

---

## 9. Acceptance Criteria

| Критерій | Статус |
|----------|--------|
| Intent parser | ✅ |
| Token resolver | ✅ |
| Pool registry | ✅ |
| CLI --use-registry/--smoke | ✅ |
| Mode in snapshot | ✅ |
| Registry snapshot | ✅ |
| 12 registry tests | ✅ |

---

## 10. Прогрес по Roadmap

| Milestone | Status |
|-----------|--------|
| M0 Bootstrap | ✅ |
| M1 Truth Engine | ✅ |
| M2 Adapters (registry-driven) | ✅ |
| M3 Opportunity Engine | 🔜 Next |
| M4 Execution v1 | 🔜 After M3 |

---

## 11. Наступні кроки

1. **Token discovery** — DexScreener API для ARB, GMX, etc.
2. **Opportunity ranking** — confidence score на основі spreads
3. **Second executable DEX** — щоб WOULD_EXECUTE > 0
4. **Truth report** — top opportunities + health metrics

---

*Документ згенеровано: 2026-01-11*
