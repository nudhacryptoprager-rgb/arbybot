# DEV_REPORT_LATEST - E1.81 pool_family SOAK COMPLETE

## TL;DR (E1.81 — soak complete, wiring confirmed)

E1.81 SOAK COMPLETE (2026-05-10T18:13–20:06 local, ~113min effective, 24 snaps × 5min).
Pool_family wiring confirmed: `family_active_count` ranged 1–5 throughout (avg 2.2).
50 E1.81 tests, 5044 total suite. Repo safety: PASS (--allow-intent-edit).

**Process-isolation bug (found + fixed this session)**:
  Original code called `observe_pair_family_profitable` in `cold_immediate_sim.py` (HOT process)
  but `family_promotion_snapshot()` reads `_FAMILY_PROMOTIONS` in `bridge_runtime.py` (COLD process).
  Module-level state is process-local → no cross-process sharing → always active_count=0.
  Fix: moved all observe calls to `bridge_runtime.py` (COLD process).
  Also: use `payload.get("cold_executable") or candidates` to cover `ready_preserved` state.

```
=== E1.81 SOAK RESULTS (2026-05-10T18:13–20:06 local) ===
Duration:          ~113min (24 snaps × 5min)
Processes alive:   4/4 (0 crashes)
family_active:     range 1–5, avg 2.2/snap, non-zero in 21/24 snaps
family_active=0:   3 snaps only (snaps #1,#2 pre-restart + #24 data gap)
best_promo_bps:    1171.56 (FLAY/WETH, T+5min); 1155.83 (0x2da56acb/SPX, T+100min)
most_persistent:   KEYCAT/WETH 825.0039bps, profitable_count=15 (across many cycles)
TTL rotation:      ✅ working — pairs enter/exit over 60s TTL cycles
pair_pool_matrix:  31 pairs / 50 pools (USDC/WETH: 6 pools/$184M; CBBTC/USDC: 7 pools/$42M)
bridge_loaded:     +374 events in soak session (7204 → 7578)
bridge_pair_hit:   +463 hits in soak session (9449 → 9912)
broad_fallback:    +9641 events (HOT lane active)
cold_imm_profit:   24 (pre-restart carryover — new session counter not accumulating;
                   cold_sim_attempted static → cold immediate sim not triggered in new session)
production_sized:  0 (pre-existing market gap; depth ceiling issue from E1.80)
usd_basis_missing: 717 (pre-restart carryover; MfT/AZUSD lacks USD basis in registry)
bgen_status:       ready / ready_preserved alternating (COLD cycles ~5–6min)
check_repo_safety: PASS (--allow-intent-edit, 0 warnings)
pytest:            5044 passed / 6 skipped / 0 failures (50 E1.81 tests)
```

**E1.81 wiring confirmed at first cold cycle (T+6min post-restart, 18:19 local)**:
  - `family_active_count: 1` → `4` → `5` → stable 1–5 throughout
  - MOG/WETH 614.94bps → expired after TTL → replaced by FLAY/WETH, KEYCAT/WETH, etc.
  - Dashboard `/api/m7/family_table`: 32 rows, `family_active_count` = live value ✅

**Key remaining gap**: `cold_imm_profit` unchanged in new session — the cold immediate sim
  queue is not generating new profitable roundtrips. `broad_fallback +9641` shows HOT active,
  but `cold_sim_attempted` static → bridge candidates may not be reaching the cold_immediate sim.
  Root cause: separate from E1.81; likely pre-existing (production_sized=0, depth ceiling).

---

## E1.81 Infrastructure (session 1, same day)

5 files, 45 tests: PoolFamily dataclass, PoolRegistry.get_pool_family(),
PairFamilyPromotion, /api/m7/family_table dashboard route. All additive.

---

## E1.80 — SOAK COMPLETE (2026-05-10T14:08–15:08Z, 60min, 5/5 alive, 0 crash_restarts)

```
=== E1.80 KEY RESULTS ===
USD_BASIS_MISSING:     0     → FIXED (dominant in E1.79)
viable/cycle:          0–5   → improved (5 in final window, 1988.9bps WETH/toby)
prod_cand:             1     → first ever (snaps 08–09); production_sized=0 (depth ceiling)
hot_signals_detected:  2×950bps (0x6921b130/WETH; sim=None; hot_cold_gap = E1.81 priority-1)
hot_signals_executed:  0     → FAIL (cold not pre-verified; depth_math_invalid=549)
api_alive_at_t60min:   true  → PASS (E1.79 died at t=54min)
ws_429_rate:           1.47% (14/952) → PASS
pytest:                4995 passed / 6 skipped / 0 failures
check_repo_safety:     PASS (0 warnings)
```


9 prep fixes verified. 4966 tests.

---

## E1.78 Soak (archived summary)

Soak 2026-05-10T11:01:13Z. Gate: INFRASTRUCTURE_PASS / MARKET_GAP.
session_best_near_usd=50.0 / amount=37.99 FAIL / profit=22.44 PASS / submit_delta=3 PASS.
Infra: 5/5 alive, 0 crash_restarts, 13 cold cycles, WS=10/894, clean exit 0. 4955 tests.
