"""Phase 2 gate acceptance checker.

Reads ``data/runs/_rolling/new_pool_sniper_latest.json`` and validates the
acceptance criteria for progressing through short-gate progression
(15 min → 30 min → 60 min).

Exit codes
----------
0 : PASS — all criteria satisfied.
1 : FAIL_CRITERIA — artifact exists but one or more criteria failed.
2 : FAIL_MISSING — artifact not found.

Usage
-----
    py -3.11 scripts/check_phase2_gate.py [--artifact PATH]

Acceptance criteria
-------------------
- ``parse_failed == 0``
- ``rpc_errors == 0``
- ``phase2_reject_histogram`` key is present in metrics
- Not ALL decisions are ``INSUFFICIENT_DATA``
  (i.e. at least one non-INSUFFICIENT_DATA or non-V4_LIQUIDITY_UNSUPPORTED decision exists,
  OR ``phase2_expected_pnl_non_null_count >= 1``)
- ``phase2_expected_pnl_non_null_count >= 0`` (key exists)

After PASS, the progression schedule is:
  15 min gate PASS → run 30 min gate → 60 min gate → authorize 24h paper soak.
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
    fails: list[str] = []

    # 1. parse_failed == 0
    parse_failed = int(metrics.get("parse_failed") or 0)
    if parse_failed != 0:
        fails.append(f"parse_failed={parse_failed} (expected 0)")

    # 2. rpc_errors == 0
    rpc_errors = int(metrics.get("rpc_errors") or 0)
    if rpc_errors != 0:
        fails.append(f"rpc_errors={rpc_errors} (expected 0)")

    # 3. phase2_reject_histogram key present
    if "phase2_reject_histogram" not in metrics:
        fails.append("phase2_reject_histogram key missing from metrics (no phase2 decisions reached artifact)")

    # 4. Not 100% INSUFFICIENT_DATA + phase2_expected_pnl_non_null_count >= 0 (exists)
    pnl_non_null = metrics.get("phase2_expected_pnl_non_null_count")
    if pnl_non_null is None:
        fails.append("phase2_expected_pnl_non_null_count key missing from metrics")
    else:
        hist: dict = metrics.get("phase2_reject_histogram") or {}
        total_decisions = sum(hist.values())
        bad_decisions = hist.get("INSUFFICIENT_DATA", 0) + hist.get("V4_LIQUIDITY_UNSUPPORTED", 0)
        real_input_decisions = total_decisions - bad_decisions
        pnl_non_null = int(pnl_non_null)
        if total_decisions > 0 and real_input_decisions == 0 and pnl_non_null == 0:
            fails.append(
                f"ALL decisions are INSUFFICIENT_DATA/V4_LIQUIDITY_UNSUPPORTED "
                f"({total_decisions} total, real_input=0, pnl_non_null=0) — "
                "no real-input proven"
            )

    # --- Report ---
    print("=" * 68)
    print(f"ARTIFACT : {artifact_path}")
    print(f"STATUS   : {art.get('status', 'UNKNOWN')}")
    print(f"GENERATED: {art.get('generated_at_utc', 'N/A')}")
    print(f"FRESHNESS: {art.get('freshness_s', '?')} s")
    print("-" * 68)
    print(f"parse_failed                    : {parse_failed}")
    print(f"rpc_errors                      : {rpc_errors}")
    print(f"phase2_reject_histogram         : {metrics.get('phase2_reject_histogram', 'MISSING')}")
    print(f"phase2_would_enter_count        : {metrics.get('phase2_would_enter_count', 'MISSING')}")
    print(f"phase2_expected_pnl_non_null_count: {metrics.get('phase2_expected_pnl_non_null_count', 'MISSING')}")
    print("-" * 68)

    if fails:
        print("GATE RESULT: FAIL")
        for f in fails:
            print(f"  [FAIL] {f}")
        print("=" * 68)
        return 1

    print("GATE RESULT: PASS")
    print()
    print("Next steps (progression):")
    print("  1. PASS 15m → run 30m gate:")
    print("     py -3.11 scripts/sniper_smoke_run.py --chain base --duration-minutes 30 \\")
    print("         --prefer-ws --poll-interval-s 30 --blocks-back 50")
    print("  2. PASS 30m → run 60m gate:")
    print("     py -3.11 scripts/sniper_smoke_run.py --chain base --duration-minutes 60 \\")
    print("         --prefer-ws --poll-interval-s 30 --blocks-back 50")
    print("  3. PASS 60m → authorize 24h paper soak.")
    print("     Update docs/status/Status_M8.md:")
    print("       phase2_24h_soak_blocked_until_real_inputs: false")
    print("=" * 68)
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
