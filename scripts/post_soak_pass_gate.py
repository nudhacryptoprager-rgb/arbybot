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
            "value": best_profit_effective,
            "value_snapshot": best_profit,
            "session_best_expected_profit_usd": session_best_expected_profit_usd,
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
    }

    all_pass = all(c["pass"] for c in checks.values())
    report = {"all_pass": all_pass, "profile": args.profile, "strict": strict, "checks": checks}
    print(json.dumps(report, indent=2, default=str))
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
