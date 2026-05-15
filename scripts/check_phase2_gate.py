"""Phase 2 gate acceptance checker.

Reads ``data/runs/_rolling/new_pool_sniper_latest.json`` and validates the
acceptance criteria for progressing through short-gate progression
(15 min → 30 min → 60 min).

Exit codes
----------
0 : PASS — discovery criteria satisfied (listener works).
1 : FAIL_CRITERIA — discovery criteria failed (listener broken or data missing).
2 : FAIL_MISSING — artifact not found.

The gate has TWO sections that are checked independently:

DISCOVERY GATE (required for any short-gate PASS):
  - ``parse_failed == 0``
  - ``rpc_errors``: structural (non-429) must be 0; up to 10 429 rate-limit
    errors are tolerated as startup HTTP-fallback noise
  - ``phase2_reject_histogram`` key is present in metrics

ARB GATE (required for 24h soak authorization):
  - ``arb_candidates_total >= 1`` — at least one event had a price reference
  - ``phase2_expected_pnl_non_null_count >= 1`` — at least one non-null PnL

Exit code 0 means DISCOVERY GATE passed.  The ARB GATE status is printed
separately as ARB_PASS or ARB_BLOCKED.  24h soak requires ARB_PASS.

Usage
-----
    py -3.11 scripts/check_phase2_gate.py [--artifact PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_DEFAULT_ARTIFACT = (
    Path(__file__).resolve().parent.parent
    / "data" / "runs" / "_rolling" / "new_pool_sniper_latest.json"
)


def _check(artifact_path: Path) -> int:
    if not artifact_path.exists():
        print(f"[FAIL_MISSING] Artifact not found: {artifact_path}")
        return 2

    try:
        with open(artifact_path, encoding="utf-8") as fh:
            art = json.load(fh)
    except Exception as exc:
        print(f"[FAIL_MISSING] Cannot parse artifact: {exc}")
        return 2

    metrics: dict = art.get("metrics") or {}
    discovery_fails: list[str] = []
    arb_warns: list[str] = []

    # ======================================================================
    # DISCOVERY GATE — listener health (required for any PASS)
    # ======================================================================
    # 1. parse_failed == 0
    parse_failed = int(metrics.get("parse_failed") or 0)
    if parse_failed != 0:
        discovery_fails.append(f"parse_failed={parse_failed} (expected 0)")

    # 2. rpc_errors — 429 rate-limit errors are transient HTTP-fallback startup
    #    noise and are expected; only structural errors (5xx, timeout, connection
    #    refused) should block the discovery gate.
    rpc_errors = int(metrics.get("rpc_errors") or 0)
    rpc_err_hist = metrics.get("rpc_error_histogram") or {}
    rate_limit_429 = int(rpc_err_hist.get("429_rate_limit") or 0)
    structural_errors = rpc_errors - rate_limit_429
    if structural_errors > 0:
        discovery_fails.append(
            f"rpc_errors={rpc_errors} (structural={structural_errors}, 429s={rate_limit_429}) — "
            "non-429 RPC errors indicate a connectivity or provider problem"
        )
    elif rpc_errors > 10:
        # Even all-429, an excessive rate means we're being throttled too hard.
        discovery_fails.append(
            f"rpc_errors={rpc_errors} (all 429_rate_limit) — excessive rate-limiting; "
            "check RPC tier or reduce poll frequency"
        )

    # 3. phase2_reject_histogram key present
    if "phase2_reject_histogram" not in metrics:
        discovery_fails.append(
            "phase2_reject_histogram key missing from metrics (no phase2 decisions reached artifact)"
        )

    # ======================================================================
    # ARB GATE — economics proven (required for 24h soak)
    # ======================================================================
    arb_candidates = int(metrics.get("arb_candidates_total") or 0)
    pnl_non_null = int(metrics.get("phase2_expected_pnl_non_null_count") or 0)
    discovery_total = int(metrics.get("discovery_candidates_total") or 0)

    top_arb = art.get("top_arb_candidates") or []

    # ARB_PASS requires at least one candidate with ALL 4 economics fields non-null:
    #   expected_pnl_usd, spread_bps, liquidity_usd, slippage_bps
    arb_fully_proven = any(
        c.get("expected_pnl_usd") is not None
        and c.get("spread_bps") is not None
        and c.get("liquidity_usd") is not None
        and c.get("slippage_bps") is not None
        for c in top_arb
    )
    arb_pass = arb_fully_proven

    if arb_candidates == 0:
        arb_warns.append(
            f"arb_candidates_total=0 (discovery_candidates_total={discovery_total}) — "
            "no event had a price reference (MIRROR_POOL / ANCHOR_RATIO / TRIANGULAR_ROUTE). "
            "Listener works but arb economics not proven. "
            "Root cause: new meme pools lack mirror DEX; add triangular anchor pairs."
        )
    if pnl_non_null == 0:
        arb_warns.append(
            "phase2_expected_pnl_non_null_count=0 — PnL not computed for any candidate. "
            "Requires arb_candidates_total >= 1 and successful spread computation."
        )
    if arb_candidates >= 1 and not arb_fully_proven:
        # Show per-candidate diagnostics when candidates exist but economics not fully proven
        for c in top_arb:
            missing_fields = [
                f for f in ("expected_pnl_usd", "spread_bps", "liquidity_usd", "slippage_bps")
                if c.get(f) is None
            ]
            if missing_fields:
                ref = c.get("reference_source", "?")
                edges = c.get("route_edges") or {}
                issues = edges.get("edge_issues") or []
                arb_warns.append(
                    f"  candidate ref={ref} missing_fields={missing_fields}"
                    + (f" edge_issues={issues}" if issues else "")
                )

    # --- Report ---
    hist: dict = metrics.get("phase2_reject_histogram") or {}
    print("=" * 72)
    print(f"ARTIFACT : {artifact_path}")
    print(f"STATUS   : {art.get('status', 'UNKNOWN')}")
    print(f"GENERATED: {art.get('generated_at_utc', 'N/A')}")
    print(f"FRESHNESS: {art.get('freshness_s', '?')} s")
    print("-" * 72)
    print("DISCOVERY GATE (listener health)")
    print(f"  parse_failed                      : {parse_failed}")
    print(f"  rpc_errors                        : {rpc_errors}")
    print(f"  phase2_reject_histogram           : {hist}")
    print(f"  phase2_would_enter_count          : {metrics.get('phase2_would_enter_count', 'MISSING')}")
    print("-" * 72)
    print("ARB GATE (economics — required for 24h soak)")
    print(f"  discovery_candidates_total        : {discovery_total}")
    print(f"  arb_candidates_total              : {arb_candidates}")
    print(f"  phase2_expected_pnl_non_null_count: {pnl_non_null}")
    print(f"  top_arb_candidates (in window)    : {len(top_arb)}")
    print(f"  arb_fully_proven (4-field check)  : {arb_fully_proven}")
    for c in top_arb:
        ref = c.get("reference_source", "?")
        spread = c.get("spread_bps")
        liq = c.get("liquidity_usd")
        slip = c.get("slippage_bps")
        pnl = c.get("expected_pnl_usd")
        edges = c.get("route_edges") or {}
        issues = edges.get("edge_issues") or []
        print(
            f"    ref={ref} spread_bps={spread} liq_usd={liq} "
            f"slippage_bps={slip} pnl={pnl}"
            + (f" edge_issues={issues}" if issues else "")
        )
    print("-" * 72)

    # ARB gate result
    if arb_pass:
        print("ARB GATE  : PASS")
    else:
        print("ARB GATE  : BLOCKED (24h soak NOT authorized)")
        for w in arb_warns:
            print(f"  [BLOCKED] {w}")

    # Discovery gate result
    if discovery_fails:
        print("DISC GATE : FAIL")
        for f in discovery_fails:
            print(f"  [FAIL] {f}")
        print("=" * 72)
        return 1

    print("DISC GATE : PASS")
    print()
    if arb_pass:
        print("GATE RESULT: FULL_PASS (discovery + arb economics proven)")
        print()
        print("Next steps (progression):")
        print("  Run 30m gate → 60m gate → authorize 24h paper soak.")
        print("  Update docs/status/Status_M8.md:")
        print("    phase2_24h_soak_allowed: true")
    else:
        print("GATE RESULT: DISCOVERY_PASS / ARB_BLOCKED")
        print()
        print("Discovery pipeline works.  To unblock ARB GATE:")
        print("  1. Find pools with mirror DEX (same pair on Aerodrome/Uniswap V3/V4).")
        print("  2. Find stable/anchor pairs (USDC/WETH, cbUST/USDC).")
        print("  3. Once arb_candidates_total>=1 and pnl_non_null>=1, re-run gate.")
        print("  4. Do NOT proceed to 24h soak until ARB_PASS.")
    print("=" * 72)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 gate acceptance checker")
    parser.add_argument(
        "--artifact",
        type=Path,
        default=_DEFAULT_ARTIFACT,
        help="Path to new_pool_sniper_latest.json (default: rolling artifact)",
    )
    args = parser.parse_args()
    sys.exit(_check(args.artifact))


if __name__ == "__main__":
    main()
