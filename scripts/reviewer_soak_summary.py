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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROLL = Path("data/runs/_rolling")


def fresh_failed_samples(rollup: dict, session_id: str | None) -> list[dict]:
    """M7.E1.34f fix #7: only samples tagged with current session_id.

    Drops stale `sim_failed_samples_recent` entries from prior sessions so
    reviewer STF diagnosis never cites pre-fix evidence. If session_id is
    falsy, returns an empty list rather than falling back to the raw list.
    """
    if not session_id:
        return []
    samples = rollup.get("sim_failed_samples_recent") or []
    if not isinstance(samples, list):
        return []
    out: list[dict] = []
    for s in samples:
        if isinstance(s, dict) and s.get("session_id") == session_id:
            out.append(s)
    return out


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
    #   fast_path_scored_delta >= ARBY_REVIEWER_MIN_FAST_PATH_SCORED (default 20)
    #     unless ARBY_REVIEWER_QUIET_OK=1 (operator-classified MARKET_QUIET_BLOCKED)
    _quiet_ok = os.environ.get("ARBY_REVIEWER_QUIET_OK", "0").strip() == "1"
    _min_fps = int(os.environ.get("ARBY_REVIEWER_MIN_FAST_PATH_SCORED", "20") or 20)
    _fps_delta = deltas.get("fast_path_scored_total", 0)
    _fps_ok = _quiet_ok or (_fps_delta >= _min_fps)
    ok = (
        (deltas["sim_passed_total"] > 0)
        and (deltas["roundtrip_attempted_total"] > 0)
        and (block_oor == 0)
        and (deltas["strict_provider_breaches_total"] == 0)
        and _fps_ok
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
    if not _fps_ok:
        reasons.append(
            f"FAST_PATH_SCORED_TOO_LOW={_fps_delta}<{_min_fps}"
            " (set ARBY_REVIEWER_QUIET_OK=1 to classify as MARKET_QUIET_BLOCKED)"
        )
    # Reviewer post-20m-control fix #2: SCORING_BLACKHOLE detector.
    # When the feed produced events but NONE of them reached fast-path
    # scoring, the issue is in the bridge/admission funnel — distinct from
    # quiet market. Surfaced as an explicit reason so operators do not
    # confuse a scoring-funnel regression with low liquidity.
    _events_delta = deltas.get("events_seen_total", 0)
    # E1.45 reviewer guard #3: active-hot-write acceptance check.
    # If events_seen_delta == 0 the hot lane never observed a single
    # event during the soak — almost always drpc/WS provider trouble
    # (bare WS subscribe rejected, supervisor reaped child early). The
    # reviewer must surface this distinctly from market_quiet so the
    # operator does not confuse infra silence with quiet liquidity.
    # Suppressed when no fresh window-clock at all (handled elsewhere).
    if _events_delta == 0 and not _quiet_ok:
        reasons.append(
            "NO_HOT_WRITE_DURING_SOAK events_seen_delta=0 "
            "(check WS subscribe / drpc 429 / hot lane child crashes; "
            "set ARBY_REVIEWER_QUIET_OK=1 if intentionally market_quiet)"
        )
    # E1.46 reviewer fix #3: NO_HOT_CYCLE_COMPLETED_DURING_SOAK.
    # Hot writes happened (events_seen_delta>0) but no child finished
    # its scan cycle cleanly across the soak (clean_child_exits_delta
    # stayed at 0). Distinguishes "hot lane is alive but every child
    # crashed before flush_rollup_shutdown" from a healthy soak whose
    # children completed cycles. ``clean_child_exits_total`` is the
    # rollup-side mirror added in E1.46 (see hot_runtime_artifacts).
    _cce_delta = max(
        0,
        int(current.get("clean_child_exits_total", 0) or 0)
        - int(baseline.get("clean_child_exits_total", 0) or 0),
    )
    if _events_delta > 0 and _cce_delta == 0 and not _quiet_ok:
        reasons.append(
            "NO_HOT_CYCLE_COMPLETED_DURING_SOAK "
            f"events_seen_delta={_events_delta} clean_child_exits_delta=0 "
            "(hot lane wrote but no child exited cleanly; "
            "supervisor cycles_completed likely 0)"
        )
        ok = False
    if _events_delta > 0 and _fps_delta == 0:
        # E1.45: enriched SCORING_BLACKHOLE breakdown using the existing
        # admission-funnel counters. NO_BRIDGE_HIT and BRIDGE_HIT_NOT_SCORED
        # come straight from rolling artifacts; PAIR_FILTERED / TIER_COLD
        # are pulled from the bridge_hit_but_not_fast_scored.reason_histogram.
        no_bridge_hit_delta = max(
            0,
            int(current.get("windows_events_without_bridge_hit_total", 0) or 0)
            - int(baseline.get("windows_events_without_bridge_hit_total", 0) or 0),
        )
        cur_bhns = (current.get("bridge_hit_but_not_fast_scored") or {})
        base_bhns = (baseline.get("bridge_hit_but_not_fast_scored") or {})
        bridge_hit_not_scored_delta = max(
            0,
            int(cur_bhns.get("windows", 0) or 0)
            - int(base_bhns.get("windows", 0) or 0),
        )
        cur_rh = cur_bhns.get("reason_histogram") or {}
        base_rh = base_bhns.get("reason_histogram") or {}

        def _rh_delta(name: str) -> int:
            return max(
                0,
                int(cur_rh.get(name, 0) or 0) - int(base_rh.get(name, 0) or 0),
            )

        pair_filtered_delta = (
            _rh_delta("PAIR_FILTERED") + _rh_delta("UNKNOWN_PAIR")
        )
        tier_cold_delta = _rh_delta("TIER_COLD")
        reasons.append(
            "SCORING_BLACKHOLE "
            f"events_seen_delta={_events_delta} fast_path_scored_delta=0 "
            f"[NO_BRIDGE_HIT={no_bridge_hit_delta} "
            f"BRIDGE_HIT_NOT_SCORED={bridge_hit_not_scored_delta} "
            f"PAIR_FILTERED={pair_filtered_delta} "
            f"TIER_COLD={tier_cold_delta}]"
        )
    # E1.45 reviewer guard #1: rate_metrics schema contract.
    # The rate_metrics block must use the E1.43+ session-delta schema:
    # `rate_basis == "current_worker_session_delta"` plus the *_delta keys.
    # A missing rate_basis indicates the rollup was last written by code
    # older than E1.43 (or the lane never refreshed at supervisor exit).
    rm = current.get("rate_metrics") or {}
    if rm:
        rb = rm.get("rate_basis")
        if rb != "current_worker_session_delta":
            reasons.append(
                f"RATE_METRICS_SCHEMA_STALE rate_basis={rb!r} "
                f"(expected 'current_worker_session_delta'; rollup not refreshed by E1.43+)"
            )
            ok = False
        for required_key in (
            "roundtrip_attempted_delta",
            "roundtrip_profitable_delta",
            "scoring_blackhole_windows_delta",
        ):
            if required_key not in rm:
                reasons.append(
                    f"RATE_METRICS_MISSING_KEY={required_key} "
                    f"(rollup pre-E1.43 schema or partial refresh)"
                )
                ok = False
                break
    # E1.45 reviewer guard #2: impossible per-hour rates.
    # An absurd value (> ABS_RATE_THRESHOLD per hour) is the canonical
    # symptom of dividing lifetime cumulative counters by short worker
    # elapsed time (the E1.42 bug class). Catch any future regression
    # at acceptance time.
    _abs_rate_threshold = float(
        os.environ.get("ARBY_REVIEWER_ABS_RATE_THRESHOLD_PER_HOUR", "1000") or 1000
    )
    for rate_key in (
        "roundtrip_attempt_rate_per_hour",
        "profitable_event_rate_per_hour",
    ):
        rate_val = rm.get(rate_key)
        if isinstance(rate_val, (int, float)) and rate_val > _abs_rate_threshold:
            reasons.append(
                f"RATE_METRICS_ABSURD {rate_key}={rate_val:.2f}>"
                f"{_abs_rate_threshold:.0f}/h "
                f"(symptom of lifetime/elapsed bug — verify rate_baseline seeding)"
            )
            ok = False
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
    parser.add_argument(
        "--max-rollup-staleness-s", type=int, default=120,
        help=(
            "Fail acceptance if current rollup last_updated is older than "
            "now - this many seconds. Default 120s. Set 0 to disable."
        ),
    )
    parser.add_argument(
        "--staleness-anchor-utc", type=str, default=None,
        help=(
            "M7.E1.34f fix #2: anchor staleness check to this UTC "
            "timestamp (supervisor end time from the soak log) instead "
            "of wall-clock now. Accepts ISO-8601 (e.g. "
            "2026-04-21T18:28:21Z). When omitted, falls back to now."
        ),
    )
    parser.add_argument(
        "--summary-url", type=str, default=None,
        help=(
            "soak18 step 8: optional dashboard URL "
            "(e.g. http://127.0.0.1:8109/api/summary). When provided, "
            "the script ALSO fetches the live /api/summary current_scan "
            "block and cross-validates that the dashboard's freshness "
            "verdict matches the file-based reviewer verdict. Catches "
            "drift between API contract and reviewer logic."
        ),
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

    # M7.E1.34e fix #4: stale-rollup gate. If the supervisor terminated
    # cleanly but the hot rollup wasn't refreshed in the final stretch,
    # the funnel was effectively dead and the soak does not count.
    stale_reasons: list[str] = []
    if args.max_rollup_staleness_s > 0:
        # M7.E1.34f fix #2: staleness is measured against supervisor end
        # (if supplied) rather than wall-clock now, so later reviewer
        # analysis doesn't retro-fail a soak that kept the rollup fresh
        # all the way to the deadline.
        _now = None
        if isinstance(args.staleness_anchor_utc, str) and args.staleness_anchor_utc.strip():
            try:
                _now = datetime.fromisoformat(
                    args.staleness_anchor_utc.strip().replace("Z", "+00:00")
                )
                if _now.tzinfo is None:
                    _now = _now.replace(tzinfo=timezone.utc)
            except Exception:
                _now = None
        if _now is None:
            _now = datetime.now(timezone.utc)
        for label, art in (("production", cur),):
            _lu = art.get("last_updated") if isinstance(art, dict) else None
            if isinstance(_lu, str):
                try:
                    _lu_dt = datetime.fromisoformat(_lu.replace("Z", "+00:00"))
                    if _lu_dt.tzinfo is None:
                        _lu_dt = _lu_dt.replace(tzinfo=timezone.utc)
                    _age = (_now - _lu_dt).total_seconds()
                    if _age > args.max_rollup_staleness_s:
                        stale_reasons.append(
                            f"STALE_ROLLUP[{label}] age={int(_age)}s"
                            f">{args.max_rollup_staleness_s}s"
                        )
                except Exception:
                    pass

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

    # M7.E1.34f post-soak19 reviewer fix #3: explicitly emit which
    # simulation_backend produced this evidence so closure claims cannot
    # silently rely on Tenderly while reviewer thresholds were tuned for
    # rpc_fork. If both lanes agree, print one line; otherwise print both.
    _prod_backend = cur.get("simulation_backend") if isinstance(cur, dict) else None
    _disc_backend = None
    if args.discovery:
        try:
            _disc_cur_obj = _load(ROLL / "m7_hot_rollup_latest_discovery.json") or {}
            _disc_backend = _disc_cur_obj.get("simulation_backend")
        except Exception:
            pass
    _ext_total = (cur.get("external_provider_blocker_total") or 0) if isinstance(cur, dict) else 0
    _ext_hist = (cur.get("external_provider_blocker_histogram") or {}) if isinstance(cur, dict) else {}
    if args.discovery and _disc_backend and _disc_backend != _prod_backend:
        print(f"  simulation_backend = PROD:{_prod_backend} / DISC:{_disc_backend}")
    else:
        print(f"  simulation_backend = {_prod_backend or 'UNKNOWN'}")
    print(
        f"  external_provider_blocker_total = {_ext_total}"
        + (f"  hist={dict(list(_ext_hist.items())[:3])}" if _ext_hist else "")
    )

    # M7.E1.34f fix #7: only cite sim_failed_samples whose session_id
    # matches the current session. Everything else is historical noise.
    _sess = (cur.get("session") or {}) if isinstance(cur, dict) else {}
    _cur_sid = _sess.get("session_id") if isinstance(_sess, dict) else None
    _fresh = fresh_failed_samples(cur, _cur_sid)
    print(
        f"  fresh_sim_failed_samples = {len(_fresh)} "
        f"(session_id={_cur_sid or 'UNKNOWN'})"
    )

    overall = prod_ok and disc_ok and not stale_reasons
    print(f"\n  OVERALL_ACCEPTANCE : {'PASS' if overall else 'FAIL'}")
    if stale_reasons:
        print("  Stale rollup(s): " + "; ".join(stale_reasons))

    # soak18 step 8: live cross-check vs dashboard /api/summary. Reads
    # the same primary verdict the operator sees in the UI. If the API
    # says is_fresh while the file-based reviewer says STALE_ROLLUP
    # (or vice versa) we surface DASHBOARD_DRIFT — that means the API
    # contract drifted from the reviewer logic and must be fixed.
    if isinstance(args.summary_url, str) and args.summary_url.strip():
        _print_header("DASHBOARD CROSS-CHECK")
        try:
            import urllib.request
            import json as _json
            with urllib.request.urlopen(
                args.summary_url.strip(), timeout=5
            ) as resp:
                api_payload = _json.loads(resp.read().decode("utf-8"))
            cs = api_payload.get("current_scan") or {}
            api_fresh = bool(cs.get("is_fresh"))
            api_age = cs.get("age_seconds")
            api_session = cs.get("session_id")
            api_match = bool(cs.get("session_id_match_baseline"))
            api_reason = cs.get("staleness_reason")
            api_schema = api_payload.get("schema_version")
            api_chain = api_payload.get("chain")
            api_profile = api_payload.get("profile")
            print(f"  api.schema_version                  = {api_schema}")
            print(f"  api.chain                           = {api_chain}")
            print(f"  api.profile                         = {api_profile}")
            print(f"  api.current_scan.is_fresh           = {api_fresh}")
            print(f"  api.current_scan.age_seconds        = {api_age}")
            print(f"  api.current_scan.session_id         = {api_session}")
            print(f"  api.session_id_match_baseline       = {api_match}")
            print(f"  api.current_scan.staleness_reason   = {api_reason}")
            # soak18 step 3: hard-fail if API contract drifted (wrong
            # schema/chain/profile means we are reading a foreign API or
            # a build that no longer matches the reviewer logic).
            contract_mismatch: list[str] = []
            if api_schema != "summary_v2":
                contract_mismatch.append(
                    f"schema_version={api_schema!r} (expected 'summary_v2')"
                )
            if api_chain not in (None, "base"):
                contract_mismatch.append(
                    f"chain={api_chain!r} (expected 'base')"
                )
            if api_profile not in (None, "production"):
                contract_mismatch.append(
                    f"profile={api_profile!r} (expected 'production')"
                )
            if contract_mismatch:
                print(
                    "  ! DASHBOARD_DRIFT: API contract mismatch -> "
                    + "; ".join(contract_mismatch)
                )
                overall = False
            file_stale = bool(stale_reasons)
            api_stale = not api_fresh
            if file_stale != api_stale:
                print(
                    "  ! DASHBOARD_DRIFT: file verdict and API verdict disagree "
                    f"(file_stale={file_stale} vs api_stale={api_stale}). "
                    "Reconcile build_summary_payload with reviewer thresholds."
                )
                # Drift counts as soft FAIL even if individual blocks pass.
                overall = False
        except Exception as e:  # noqa: BLE001 - cross-check is best-effort
            print(f"  ! could not fetch {args.summary_url}: {e}")

    if not overall:
        print(
            "  Reason: session delta does not meet acceptance "
            "(sim_passed>0 AND roundtrip_attempted>0 AND "
            "BlockOutOfRangeError_delta==0 AND strict_provider_breaches==0 "
            "AND fast_path_scored_delta>=ARBY_REVIEWER_MIN_FAST_PATH_SCORED "
            "AND rollup not stale).",
        )
    return 0 if overall else 2


if __name__ == "__main__":
    sys.exit(main())
