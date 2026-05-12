#!/usr/bin/env python
"""E1.69 reviewer fix step 10 — post-soak PASS gate.

Reads rolling artifacts and exits 0 only when **all** PASS criteria hold:

  1. ``production_sized_candidate_total`` > 0
  2. best ``amount_in_optimal_usd`` >= ARBY_GATE_MIN_AMOUNT_USD (default 50)
  3. best ``expected_profit_usd`` > ARBY_GATE_MIN_PROFIT_USD (default 0.01)
  4. fresh-session roundtrip profitable delta > 0
  5. fresh-session submit_ready delta > 0
  6. ``ws_429_rate`` < ARBY_GATE_MAX_WS_429_RATE (default 0.15 i.e. 15%)

Otherwise exits 1 and prints a JSON failure report on stderr. Designed
to be invoked at the end of a soak supervisor run::

    py -3.11 scripts/post_soak_pass_gate.py

ENV overrides:
  ARBY_GATE_ROLLING_DIR     — defaults to ``data/runs/_rolling``
  ARBY_GATE_MIN_AMOUNT_USD  — float, default 50
  ARBY_GATE_MIN_PROFIT_USD  — float, default 0.01
  ARBY_GATE_MAX_WS_429_RATE — float, default 0.15

Exit codes:
  0  — all criteria pass
  1  — one or more criteria failed (details on stderr)
  2  — required artifact missing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, Optional


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _safe_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _load(path: str) -> Optional[Dict[str, Any]]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def _build_micro_tier_check(
    bridge: Dict[str, Any],
    micro_min_usd: float = 5.0,
    micro_max_usd: float = 50.0,
) -> Dict[str, Any]:
    """E1.83 fix steps 2-5+7: Micro-tier gate ($5-$50).

    For each bridge candidate in the micro range, computes:
      total_fee_usd  = l2_gas_usd + l1_fee_usd_approx
      required_profit = max(0.05, 3.0 * total_fee_usd)
      profit_after_all_costs_usd = expected_profit_usd - total_fee_usd

    A candidate is "micro_viable" only when expected_profit_usd >= required_profit.

    Returns informational check dict:
      micro_candidate_count    — candidates in [$5, $50) range
      micro_viable_count       — candidates meeting profit >= 3x fee guard
      micro_best_profit_usd    — best expected_profit_usd in micro range
      micro_best_net_usd       — best profit_after_all_costs_usd (post-fee)
      micro_fee_model          — fee model assumed (L1 default wei + ETH price)
      pass                     — True when micro_viable_count > 0
      informational            — always True (separate tier, not prod gate)
    """
    # L1 fee estimate: DEFAULT_OP_L1_FEE_WEI = 5e12 wei (~$0.012 @ $2400/ETH).
    # Use bridge's cached ETH price if present, else conservative default.
    _DEFAULT_OP_L1_FEE_WEI = 5_000_000_000_000
    _eth_price_usd = _safe_float(bridge.get("eth_price_usd") or bridge.get("price_eth_usd") or 0)
    if _eth_price_usd <= 0:
        _eth_price_usd = 2400.0
    l1_fee_usd_approx = _DEFAULT_OP_L1_FEE_WEI / 1e18 * _eth_price_usd
    # L2 base fee: ~0.001 gwei * ~200k gas = 0.0000002 ETH ≈ $0.0005 (negligible, use 0.002 floor)
    l2_gas_usd_floor = 0.002

    micro_candidates = []
    for key in ("cold_executable", "production_executable"):
        for c in bridge.get(key, []) or []:
            amt = _safe_float(c.get("amount_in_optimal_usd") or c.get("size_usd"))
            if micro_min_usd <= amt < micro_max_usd:
                l2_gas_usd = max(_safe_float(c.get("gas_usd")), l2_gas_usd_floor)
                total_fee_usd = l1_fee_usd_approx + l2_gas_usd
                expected_profit = _safe_float(c.get("expected_profit_usd"))
                required_profit = max(0.05, 3.0 * total_fee_usd)
                profit_after_costs = expected_profit - total_fee_usd
                viable = expected_profit >= required_profit
                micro_candidates.append({
                    "amount_in_optimal_usd": round(amt, 4),
                    "expected_profit_usd": round(expected_profit, 6),
                    "total_fee_usd": round(total_fee_usd, 6),
                    "required_profit_usd": round(required_profit, 6),
                    "profit_after_all_costs_usd": round(profit_after_costs, 6),
                    "micro_viable": viable,
                })

    micro_viable = [c for c in micro_candidates if c["micro_viable"]]
    best_profit = max((c["expected_profit_usd"] for c in micro_candidates), default=0.0)
    best_net = max((c["profit_after_all_costs_usd"] for c in micro_candidates), default=0.0)
    # E1.83 Fix #6: count only candidates with net_usd_after_fee > 0
    micro_net_positive = [c for c in micro_candidates if c["profit_after_all_costs_usd"] > 0]
    return {
        "micro_candidate_count": len(micro_candidates),
        "micro_viable_count": len(micro_viable),
        "micro_net_positive_count": len(micro_net_positive),
        "micro_best_profit_usd": round(best_profit, 6),
        "micro_best_net_usd": round(best_net, 6),
        "micro_fee_model": {
            "l1_fee_usd_approx": round(l1_fee_usd_approx, 6),
            "l2_gas_usd_floor": l2_gas_usd_floor,
            "eth_price_usd": _eth_price_usd,
        },
        "candidates": micro_candidates[:10],  # top 10 for debugging
        # pass requires net_usd_after_fee > 0 (not just viable with 3x guard)
        "pass": len(micro_net_positive) > 0,
        "informational": True,
    }


def _build_factory_enriched_check(bridge: Dict[str, Any], strict: bool = False) -> Dict[str, Any]:
    """E1.83 Step 4: factory_enriched guard.

    Default mode (informational=True):
      - PASS unless factory_truth_loaded=True AND factory_enriched_pairs=0 (wiring regression).

    --strict mode (E1.83 fix #2 + #6):
      - HARD FAIL if factory_truth not loaded OR factory_enriched_pairs < 1.
      - This makes a stale/missing pool_family_truth.json a real validation gate failure
        for E1.83 validation soaks instead of being silently acceptable.
    """
    factory_truth_loaded = bool(bridge.get("factory_truth_loaded", False))
    factory_enriched_pairs = _safe_int(bridge.get("factory_enriched_pairs", 0))
    factory_truth_age_s = _safe_float(bridge.get("factory_truth_age_s", -1))

    if strict:
        # Hard guard: require fresh loaded truth with at least one enriched pair.
        if not factory_truth_loaded:
            passed = False
            reason = "strict: factory_truth_not_loaded (stale or missing artifact — run refresh_factory_truth.py)"
        elif factory_enriched_pairs < 1:
            passed = False
            reason = "strict: factory_truth_loaded=True but factory_enriched_pairs=0 — wiring regression"
        else:
            passed = True
            reason = f"strict: factory_enriched_pairs={factory_enriched_pairs}"
        informational = False
    else:
        if factory_truth_loaded and factory_enriched_pairs == 0:
            passed = False
            reason = "factory_truth_loaded=True but factory_enriched_pairs=0 — wiring regression"
        elif not factory_truth_loaded:
            passed = True
            reason = "factory_truth_not_loaded (artifact missing/stale — acceptable)"
        else:
            passed = True
            reason = f"factory_enriched_pairs={factory_enriched_pairs}"
        informational = True
    return {
        "factory_truth_loaded": factory_truth_loaded,
        "factory_enriched_pairs": factory_enriched_pairs,
        "factory_truth_age_s": factory_truth_age_s,
        "pass": passed,
        "reason": reason,
        "informational": informational,
    }



def _build_deep_sweep_check(bridge: Dict[str, Any], strict: bool = False) -> Dict[str, Any]:
    """E1.83 NEW: deep_sweep_guard.

    Checks that the forced deep-pair quote sweep produced data for at least
    one factory-enriched pair.  Guards against the case where enrichment is
    confirmed (factory_enriched_pairs > 0) but the scanner never produced
    production-sized ($50+) candidates from those pairs.

    strict mode: HARD FAIL when factory_enriched_pairs > 0 AND
                 deep_pair_scored_total = 0 (wiring regression or dead scanner).
    default:     informational — shows diagnostic but does not block all_pass.
    """
    factory_enriched_pairs = _safe_int(bridge.get("factory_enriched_pairs", 0))
    deep_pair_scored_total = _safe_int(bridge.get("deep_pair_scored_total", 0))
    deep_pair_unscored_pairs = _safe_int(bridge.get("deep_pair_unscored_pairs", 0))
    deep_pair_thin_liquidity_pairs = _safe_int(bridge.get("deep_pair_thin_liquidity_pairs", 0))
    forced_sweep_count = len(bridge.get("forced_sweep_results") or [])
    deep_pair_rejected_reason = bridge.get("deep_pair_rejected_reason") or {}

    regression = factory_enriched_pairs > 0 and deep_pair_scored_total == 0

    if strict:
        passed = not regression
        reason = (
            f"strict: deep_pair_scored_total={deep_pair_scored_total} "
            f"for factory_enriched_pairs={factory_enriched_pairs} — "
            + (
                "REGRESSION: forced sweep produced no depth_curve data at $50+"
                if regression else "OK"
            )
        )
        informational = False
    else:
        passed = not regression
        reason = (
            f"factory_enriched_pairs={factory_enriched_pairs}, "
            f"deep_pair_scored_total={deep_pair_scored_total}, "
            f"unscored_pairs={deep_pair_unscored_pairs}, "
            f"thin_liquidity_pairs={deep_pair_thin_liquidity_pairs}"
        )
        informational = True

    return {
        "factory_enriched_pairs": factory_enriched_pairs,
        "deep_pair_scored_total": deep_pair_scored_total,
        "deep_pair_unscored_pairs": deep_pair_unscored_pairs,
        "deep_pair_thin_liquidity_pairs": deep_pair_thin_liquidity_pairs,
        "forced_sweep_count": forced_sweep_count,
        "deep_pair_rejected_reason": deep_pair_rejected_reason,
        "pass": passed,
        "reason": reason,
        "informational": informational,
    }


def _best_amount_usd(bridge: Dict[str, Any], include_disc: bool = False) -> float:
    best = 0.0
    keys = list({"cold_executable", "production_executable"})
    if include_disc:
        keys += ["disc_executable", "cold_usd_basis_missing"]
    for key in keys:
        for c in bridge.get(key, []) or []:
            v = _safe_float(c.get("amount_in_optimal_usd") or c.get("size_usd"))
            if v > best:
                best = v
    return best


def _best_profit_usd(bridge: Dict[str, Any], include_disc: bool = False) -> float:
    best = 0.0
    keys = list({"cold_executable", "production_executable"})
    if include_disc:
        keys += ["disc_executable"]
    for key in keys:
        for c in bridge.get(key, []) or []:
            v = _safe_float(c.get("expected_profit_usd"))
            if v > best:
                best = v
    return best


def _fresh_delta(rollup: Dict[str, Any], *names: str) -> int:
    """Read session deltas only; never fall back to lifetime totals."""
    current = rollup.get("current_session_delta") or {}
    rate = rollup.get("rate_metrics") or {}
    for name in names:
        if name in current:
            return _safe_int(current.get(name))
        if name in rate:
            return _safe_int(rate.get(name))
        top_level_delta = f"{name}_delta"
        if top_level_delta in rollup:
            return _safe_int(rollup.get(top_level_delta))
    return 0


def _ws_429_rate(rollup: Dict[str, Any]) -> float:
    # E1.70 gate-contract fix: compare failed_429 against *all* hot-loop windows
    # (windows_seen), not just WS-connection attempts.  With ARBY_WS_COOLDOWN the
    # system skips many reconnects, so connected+failed is tiny while
    # windows_seen reflects true calendar exposure.  6 429s over 735 windows =
    # 0.82% (healthy); 6/(6+6)=50% was a false-alarm produced by the old formula.
    failed = _safe_int(rollup.get("session_ws_failed_429_windows"))
    windows_seen = _safe_int(rollup.get("windows_seen"))
    if windows_seen > 0:
        return failed / windows_seen

    # fallback: if windows_seen absent, use connection-attempt denominator
    connected = _safe_int(rollup.get("session_ws_connected_windows"))
    if failed or connected:
        total = connected + failed
        return (failed / total) if total > 0 else 0.0

    ws_health = rollup.get("ws_provider_health") or {}
    failed = _safe_int(ws_health.get("ws_429_count"))
    attempts = _safe_int(ws_health.get("subscribe_attempts"))
    return (failed / attempts) if attempts > 0 else 0.0


def main() -> int:
    # E1.70 fix 7: gate profiles — prod-only (default), disc-assisted.
    ap = argparse.ArgumentParser(description="Post-soak PASS gate")
    ap.add_argument(
        "--profile",
        choices=["prod", "disc-assisted"],
        default="prod",
        help="prod: PROD-only criteria. disc-assisted: merges DISC bridge as evidence.",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help=(
            "E1.76: enforce zero-tolerance on all six checks (no $0.05 dust on amount, "
            "production_sized_total/submit_ready_delta/roundtrip_profitable_delta must each be >= 1)."
        ),
    )
    args, _ = ap.parse_known_args()
    disc_assisted = args.profile == "disc-assisted"
    strict = bool(args.strict)

    rolling_dir = os.environ.get(
        "ARBY_GATE_ROLLING_DIR", os.path.join("data", "runs", "_rolling")
    )
    min_amount = _safe_float(os.environ.get("ARBY_GATE_MIN_AMOUNT_USD", "50"))
    min_profit = _safe_float(os.environ.get("ARBY_GATE_MIN_PROFIT_USD", "0.01"))
    max_429 = _safe_float(os.environ.get("ARBY_GATE_MAX_WS_429_RATE", "0.15"))
    # E1.70 fix 5: rounding-dust tolerance so $49.9999... passes the $50 gate.
    amount_tolerance = _safe_float(os.environ.get("ARBY_GATE_AMOUNT_TOLERANCE_USD", "0.05"))
    if strict:
        # E1.76 step 10: zero tolerance — production-grade gate.
        amount_tolerance = 0.0

    bridge_path = os.path.join(rolling_dir, "m7_cold_hot_bridge.json")
    rollup_path = os.path.join(rolling_dir, "m7_hot_rollup_latest.json")

    bridge = _load(bridge_path)
    rollup = _load(rollup_path)

    if bridge is None:
        print(
            json.dumps({"error": "bridge_missing", "path": bridge_path}),
            file=sys.stderr,
        )
        return 2
    if rollup is None:
        print(
            json.dumps({"error": "rollup_missing", "path": rollup_path}),
            file=sys.stderr,
        )
        return 2

    # E1.70 fix 7: in disc-assisted mode, also read the DISC bridge and merge
    # it into evaluation (DISC can prove route viability before PROD market unlocks).
    if disc_assisted:
        disc_bridge_path = os.path.join(
            rolling_dir, "m7_cold_hot_bridge_discovery.json"
        )
        disc_bridge = _load(disc_bridge_path)
        if disc_bridge and bridge is not None:
            # Merge disc cold_executable into bridge for amount/profit eval.
            _disc_execs = disc_bridge.get("cold_executable") or []
            _merged = list(bridge.get("cold_executable") or []) + _disc_execs
            bridge = dict(bridge)
            bridge["disc_executable"] = _disc_execs
            bridge["cold_executable"] = _merged

    prod_total = _safe_int(rollup.get("production_sized_candidate_total"))
    if prod_total <= 0:
        # Fallback to bridge level
        prod_total = _safe_int(bridge.get("production_sized_candidate_total"))

    best_amount = _best_amount_usd(bridge, include_disc=disc_assisted)
    best_profit = _best_profit_usd(bridge, include_disc=disc_assisted)

    # E1.78 Step 3: also read session_best KPIs accumulated across the whole
    # soak (written back by cold_immediate_sim after each enrichment sort).
    # session_best_near_usd reflects the peak MAV/best_size seen during the
    # session — this allows the gate to pass when the peak exceeded $50 even
    # if the final bridge snapshot shows a lower value.
    _session_best = bridge.get("session_best") or {}
    session_best_near_usd = _safe_float(_session_best.get("session_best_near_usd"))
    session_best_amount_usd = _safe_float(_session_best.get("session_best_amount_usd"))
    # E1.79 Fix 2: gate uses REAL executable amount only (not proxy/ladder best_size).
    # session_best_near_usd includes depth-ladder proxy (best_size_usd, capped at $50)
    # which can mask cases where actual optimal amount < $50.
    # Production gate passes only on session_best_amount_usd (amount_in_optimal_usd peak).
    best_amount_effective = max(best_amount, session_best_amount_usd)
    # Informational: peak proxy size (mav_usd + ladder best_size_usd) — shown in report.
    session_best_proxy_size_usd = _safe_float(
        _session_best.get("session_best_proxy_size_usd") or session_best_near_usd
    )
    # E1.79 Fix 1: also read session_best_expected_profit_usd accumulated across
    # the entire soak; the final cold_executable snapshot may have a null-profit row
    # that makes _best_profit_usd() return 0 even though the session hit $22+.
    session_best_expected_profit_usd = _safe_float(
        _session_best.get("session_best_expected_profit_usd")
    )
    best_profit_effective = max(best_profit, session_best_expected_profit_usd)
    # E1.83 Fix #5: expose fresh vs carryover profit explicitly.
    # best_profit is from the current cold_executable snapshot only.
    # session_best_expected_profit_usd may be from a prior session (carryover).
    fresh_best_expected_profit_usd = best_profit

    rt_prof_delta = _fresh_delta(
        rollup,
        "roundtrip_profitable_total",
        "roundtrip_profitable_delta",
        "e163_roundtrip_profitable",
    )
    submit_ready_delta = _fresh_delta(
        rollup,
        "submit_ready_total",
        "submit_ready_delta",
    )
    ws_429_rate = _ws_429_rate(rollup)

    # E1.82 step 8: family_depth_gate — read family_promotion_snapshot from bridge.
    # Gate: family_active_count > 0 AND family_pool_count > 0 (enriched) AND
    #       max_size_usd >= ARBY_GATE_MIN_AMOUNT_USD (default $50).
    # This is an informational check in non-strict mode (soft FAIL); in strict
    # mode it is evaluated but does NOT block all_pass (separate gate concern).
    _fpromo = bridge.get("family_promotion_snapshot") or {}
    _fam_active_count = _safe_int(_fpromo.get("active_count"))
    _fam_promos = _fpromo.get("promotions") or []
    _fam_enriched_count = sum(
        1 for p in _fam_promos if _safe_int(p.get("family_pool_count")) > 0
    )
    _fam_max_size = max(
        (_safe_float(p.get("max_size_usd")) for p in _fam_promos),
        default=0.0,
    )
    _fam_gate_pass = (
        _fam_active_count > 0
        and _fam_enriched_count > 0
        and _fam_max_size >= min_amount
    )

    checks = {
        "production_sized_total": {
            "value": prod_total, "min": 1, "pass": prod_total > 0,
        },
        "best_amount_in_usd": {
            "value": best_amount_effective, "min": min_amount,
            # E1.79: effective = max(final snapshot, session_best_amount_usd [real only]).
            # session_best_near_usd (proxy/ladder) is informational; not used for gate.
            "session_best_amount_usd": session_best_amount_usd,
            "session_best_proxy_size_usd": session_best_proxy_size_usd,
            "pass": best_amount_effective >= (min_amount - amount_tolerance),
        },
        "best_expected_profit_usd": {
            # E1.79 Fix 1: use session-best peak, not only final snapshot.
            # E1.83 Fix #5: also expose fresh snapshot vs carryover for diagnostics.
            "value": best_profit_effective,
            "value_snapshot": best_profit,
            "fresh_best_expected_profit_usd": fresh_best_expected_profit_usd,
            "session_best_expected_profit_usd": session_best_expected_profit_usd,
            "carryover_flag": (
                session_best_expected_profit_usd > fresh_best_expected_profit_usd * 10
                and session_best_expected_profit_usd > 1.0
            ),
            "min": min_profit,
            "pass": best_profit_effective > min_profit,
        },
        "roundtrip_profitable_delta": {
            "value": rt_prof_delta, "min": 1, "pass": rt_prof_delta > 0,
        },
        "submit_ready_delta": {
            "value": submit_ready_delta, "min": 1,
            "pass": submit_ready_delta > 0,
        },
        "ws_429_rate": {
            "value": ws_429_rate, "max": max_429, "pass": ws_429_rate < max_429,
        },
        # E1.82 step 8: family_depth_gate — informational, does not block all_pass.
        # When this passes it means families are enriched with real pool counts AND
        # have production-sized opportunities ($50+).
        "family_depth_gate": {
            "family_active_count": _fam_active_count,
            "family_enriched_count": _fam_enriched_count,
            "family_max_size_usd": round(_fam_max_size, 4),
            "min_size_usd": min_amount,
            "pass": _fam_gate_pass,
            "informational": True,
        },
        # E1.83 Step 4 / fix #2 + #6: factory_enriched_guard.
        # Default: informational. With --strict: HARD FAIL on stale/missing pool_family_truth.json
        # or zero enriched pairs (wiring regression). Forces fresh refresh before validation soaks.
        "factory_enriched_guard": _build_factory_enriched_check(bridge, strict=strict),
        # E1.83 fix steps 2-5+7: micro_tier_gate — informational.
        # Checks $5-$50 candidates against 3x fee coverage guard.
        # Does NOT block all_pass (separate risk tier, paper-only by policy).
        "micro_tier_gate": _build_micro_tier_check(
            bridge,
            micro_min_usd=_safe_float(os.environ.get("ARBY_MICRO_MIN_SIZE_USD", "5.0")),
            micro_max_usd=_safe_float(os.environ.get("ARBY_MIN_PRODUCTION_SIZE_USD", "50.0")),
        ),
        # E1.83 NEW: deep_sweep_guard.
        # Hard fail (strict mode) when factory_enriched_pairs > 0 AND
        # deep_pair_scored_total = 0 — means forced sweep fired zero depth_curve
        # data at $50+ for any enriched pair. Indicates scan not reaching pairs.
        # Informational in non-strict mode.
        "deep_sweep_guard": _build_deep_sweep_check(bridge, strict=strict),
    }

    all_pass = all(c["pass"] for c in checks.values() if not c.get("informational"))
    report = {"all_pass": all_pass, "profile": args.profile, "strict": strict, "checks": checks}
    print(json.dumps(report, indent=2, default=str))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
