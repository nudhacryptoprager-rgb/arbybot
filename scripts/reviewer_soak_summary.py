"""Reviewer soak summary — print only fresh deltas.

Compares a pre-soak baseline snapshot against the current rolling rollups
and prints the delta for every counter the reviewer cares about (fast-path
scored, guard passed, sim attempted/passed, roundtrip attempted/profitable,
PRE_SIM_SKIP buckets, BlockOutOfRangeError, VENUE_MISSING, AMOUNT_ZERO).

Addresses reviewer feedback 2026-04-21:
  - Cumulative totals are historical and cannot be cited as fresh evidence.
  - ``scripts/analyze_roundtrip_profitability.py`` printed PROFITABLE_CASE
    from stale counters; this script emits ONLY session-delta numbers.

Usage:
    py -3.11 scripts/reviewer_soak_summary.py \\
        --baseline data/runs/_rolling/reviewer_soak_baseline_latest.json \\
        [--discovery]

Exit codes:
    0 — delta computed, acceptance passed
    1 — baseline missing / unreadable
    2 — delta computed, acceptance FAILED
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROLL = Path("data/runs/_rolling")

TRACKED_SCALARS = [
    "sim_attempted_total",
    "sim_passed_total",
    "sim_success_total",
    "sim_revert_total",
    "submit_ready_total",
    "roundtrip_attempted_total",
    "roundtrip_success_total",
    "roundtrip_profitable_total",
    "fast_path_scored_total",
    "profit_guard_passed_total",
    "events_seen_total",
    "windows_seen",
    "strict_provider_breaches_total",
]

HISTOGRAM_BUCKETS_OF_INTEREST = [
    "AMOUNT_ZERO",
    "VENUE_MISSING",
    "TOKEN_ADDRESS_UNKNOWN",
    "PRE_SIM_SKIP:BELOW_MIN_NET_BPS:1.0",
    "PRE_SIM_SKIP:NO_AMOUNT_NO_FEE_HINT",
    "PRE_SIM_SKIP:PAIR_UNRESOLVED",
    "PRE_SIM_SKIP:UNRESOLVED_PAIR",
    "PRE_SIM_SKIP:BELOW_MIN_AMOUNT_WEI",
    "PRE_SIM_SKIP:INSUFFICIENT_AMOUNT_WEI",
]


def _load(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! failed to parse {path}: {e}", file=sys.stderr)
        return None


def _num(x) -> int:
    return 0 if x is None else int(x)


def _delta_scalar(cur: dict, base: dict, key: str) -> int:
    return _num(cur.get(key)) - _num(base.get(key))


def _delta_histogram(cur: dict, base: dict, key: str = "simulation_error_histogram") -> dict:
    c = cur.get(key) or {}
    b = base.get(key) or {}
    out: dict = {}
    for k in sorted(set(c.keys()) | set(b.keys())):
        diff = _num(c.get(k)) - _num(b.get(k))
        if diff:
            out[k] = diff
    return out


def _find_bucket_delta(delta_hist: dict, needle: str) -> int:
    """Match histogram keys by exact, prefix, or substring. Returns summed delta.

    Rollup buckets often have stable prefixes such as
    ``eth_call: BlockOutOfRangeError`` or ``CALLDATA_BUILD_FAILED:AMOUNT_ZERO``.
    Substring matching keeps the reviewer summary aligned with those emitted
    buckets without forcing every caller to know the transport prefix.
    """
    total = 0
    for k, v in delta_hist.items():
        if k == needle or k.startswith(needle) or needle in k:
            total += int(v)
    return total


def _print_header(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def summarise_lane(lane_name: str, baseline: dict, current: dict) -> tuple:
    """Print the delta block for one lane. Returns (ok, reason)."""
    _print_header(f"LANE: {lane_name}")
    print(
        f"baseline.session_id={baseline.get('session_id')} "
        f"current.session_id={current.get('session_id')}"
    )
    print(
        f"baseline.last_updated={baseline.get('last_updated')} "
        f"current.last_updated={current.get('last_updated')}"
    )

    print("\n-- Scalar deltas (current - baseline) --")
    deltas: dict = {}
    for key in TRACKED_SCALARS:
        deltas[key] = _delta_scalar(current, baseline, key)
        print(f"  {key:<32s} : {deltas[key]:+d}")

    print("\n-- Histogram deltas (non-zero only) --")
    delta_hist = _delta_histogram(current, baseline)
    if not delta_hist:
        print("  (no changes)")
    else:
        for k, v in sorted(delta_hist.items(), key=lambda kv: -kv[1])[:20]:
            print(f"  {v:+6d}  {k[:90]}")

    print("\n-- Reviewer acceptance buckets --")
    for needle in HISTOGRAM_BUCKETS_OF_INTEREST:
        match = _find_bucket_delta(delta_hist, needle)
        print(f"  {needle:<48s} delta={match:+d}")

    block_oor = _find_bucket_delta(delta_hist, "BlockOutOfRangeError")
    print(f"  BlockOutOfRangeError                             delta={block_oor:+d}")

    pre_sim_hits = sum(
        _find_bucket_delta(delta_hist, n)
        for n in HISTOGRAM_BUCKETS_OF_INTEREST if n.startswith("PRE_SIM_SKIP")
    )

    # Reviewer acceptance:
    #   sim_passed_delta > 0
    #   roundtrip_attempted_delta > 0
    #   BlockOutOfRangeError_delta == 0
    #   strict_provider_breaches_delta == 0
    ok = (
        (deltas["sim_passed_total"] > 0)
        and (deltas["roundtrip_attempted_total"] > 0)
        and (block_oor == 0)
        and (deltas["strict_provider_breaches_total"] == 0)
    )
    reasons = []
    if deltas["sim_passed_total"] <= 0:
        reasons.append("NO_FRESH_SIM_PASSED")
    if deltas["roundtrip_attempted_total"] <= 0:
        reasons.append("NO_FRESH_ROUNDTRIP_ATTEMPTED")
    if block_oor > 0:
        reasons.append(f"BLOCK_OUT_OF_RANGE_ERRORS={block_oor}")
    if deltas["strict_provider_breaches_total"] > 0:
        reasons.append(
            f"STRICT_PROVIDER_BREACHES={deltas['strict_provider_breaches_total']}"
        )
    reasons.append(f"pre_sim_skip_total={pre_sim_hits}")
    return ok, ",".join(reasons)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--baseline", type=Path,
        default=ROLL / "reviewer_soak_baseline_latest.json",
        help="Pre-soak baseline snapshot.",
    )
    parser.add_argument(
        "--current", type=Path,
        default=ROLL / "m7_hot_rollup_latest.json",
        help="Current production-lane rollup.",
    )
    parser.add_argument(
        "--discovery", action="store_true",
        help="Also summarise m7_hot_rollup_latest_discovery.json.",
    )
    parser.add_argument(
        "--baseline-discovery", type=Path,
        default=ROLL / "reviewer_soak_baseline_latest_discovery.json",
        help="Discovery-lane baseline.",
    )
    args = parser.parse_args()

    base = _load(args.baseline)
    cur = _load(args.current)
    if base is None or cur is None:
        print(
            f"! missing baseline or current rollup "
            f"(baseline={args.baseline.exists()}, current={args.current.exists()})",
            file=sys.stderr,
        )
        return 1

    prod_ok, prod_reason = summarise_lane("production", base, cur)

    disc_ok = True
    disc_reason = "SKIPPED"
    if args.discovery:
        disc_base = _load(args.baseline_discovery)
        disc_cur = _load(ROLL / "m7_hot_rollup_latest_discovery.json")
        if disc_base is None or disc_cur is None:
            print("\n[discovery] baseline or current missing; skipping", file=sys.stderr)
        else:
            disc_ok, disc_reason = summarise_lane("discovery", disc_base, disc_cur)

    _print_header("REVIEWER VERDICT")
    print(f"  production_lane_ok = {prod_ok}  ({prod_reason})")
    if args.discovery:
        print(f"  discovery_lane_ok  = {disc_ok}  ({disc_reason})")

    overall = prod_ok and disc_ok
    print(f"\n  OVERALL_ACCEPTANCE : {'PASS' if overall else 'FAIL'}")
    if not overall:
        print(
            "  Reason: session delta does not meet acceptance "
            "(sim_passed>0 AND roundtrip_attempted>0 AND "
            "BlockOutOfRangeError_delta==0 AND strict_provider_breaches==0).",
        )
    return 0 if overall else 2


if __name__ == "__main__":
    sys.exit(main())
