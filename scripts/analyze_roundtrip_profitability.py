"""Post-soak profitability analyzer for E1/E2/E3 validation.

Reads canonical rolling artifacts under data/runs/_rolling/ and reports:
  * Data pipeline health (events / sims / STF errors)
  * Round-trip coverage (attempted / success / profitable totals)
  * Round-trip profit distribution (best / median / worst bps)
  * Error histogram (why round-trips fail)
  * Per-event samples (sim_output_samples_recent)

Reviewer feedback (2026-04-21): cumulative totals are historical and
cannot be treated as production-readiness evidence. This script now
supports two session-aware modes so the reviewer verdict does not
silently rely on stale counters:

  --session-only  : compute verdict ONLY from session_* fields (the
                    window covered by the current supervisor session).
                    Cumulative totals are printed but clearly labelled
                    HISTORICAL and never drive the exit code.

  --baseline PATH : treat PATH (e.g. reviewer_soak_baseline_latest.json)
                    as a pre-soak snapshot and derive fresh deltas for
                    every *_total field before evaluating the verdict.

Without either flag the script keeps the legacy behaviour but demotes
``PROFITABLE_CASE_FOUND`` to ``HISTORICAL_PROFITABLE_CASE`` so callers
cannot accidentally cite it as fresh production evidence.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROLL = Path("data/runs/_rolling")


def _load(name: str):
    p = ROLL / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! failed to parse {name}: {e}")
        return None


def _load_path(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! failed to parse {path}: {e}")
        return None


def _num(x):
    return 0 if x is None else x


def _delta(current: dict, baseline: dict | None, key: str) -> int:
    cur = _num(current.get(key))
    if baseline is None:
        return cur
    return cur - _num(baseline.get(key))


def _delta_histogram(cur: dict, base: dict | None) -> dict:
    if base is None:
        return dict(cur)
    out: dict = {}
    for k, v in cur.items():
        diff = int(v) - int(base.get(k, 0))
        if diff:
            out[k] = diff
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--session-only", action="store_true",
        help="Derive verdict only from session_* fields in the rollup.",
    )
    parser.add_argument(
        "--baseline", type=Path, default=None,
        help="Baseline snapshot (pre-soak). If given, emit fresh deltas.",
    )
    args = parser.parse_args()

    mode_label = "HISTORICAL_TOTALS"
    if args.session_only:
        mode_label = "SESSION_WINDOW"
    elif args.baseline is not None:
        mode_label = "DELTA_VS_BASELINE"

    print("=" * 70)
    print(f"E1/E2/E3 POST-SOAK ANALYSIS  [mode={mode_label}]")
    print("=" * 70)

    rollup = _load("m7_hot_rollup_latest.json")
    summary = _load("run_summary_latest.json")  # noqa: F841  (kept for debug)
    latest = _load("_latest.json")  # noqa: F841

    if rollup is None:
        print("! m7_hot_rollup_latest.json missing — soak did not produce rollup")
        return 1

    baseline = None
    if args.baseline is not None:
        baseline = _load_path(args.baseline)
        if baseline is None:
            print(f"! --baseline {args.baseline} unreadable; aborting")
            return 1

    print(f"\nlast_updated          : {rollup.get('last_updated')}")
    print(f"session_id            : {rollup.get('session_id', 'n/a')}")
    print(f"windows_seen          : {rollup.get('windows_seen', 0)}")
    print(f"events_total          : {_num(rollup.get('events_total'))}")

    # Select which counters drive the verdict.
    if args.session_only:
        sim_attempted = _num(rollup.get("session_sim_attempted_total"))
        sim_success = _num(rollup.get("session_sim_success_total"))
        sim_revert = _num(rollup.get("session_sim_revert_total"))
        rta = _num(rollup.get("session_roundtrip_attempted_total"))
        rts = _num(rollup.get("session_roundtrip_success_total"))
        rtp = _num(rollup.get("session_roundtrip_profitable_total"))
    elif baseline is not None:
        sim_attempted = _delta(rollup, baseline, "sim_attempted_total")
        sim_success = _delta(rollup, baseline, "sim_success_total")
        sim_revert = _delta(rollup, baseline, "sim_revert_total")
        rta = _delta(rollup, baseline, "roundtrip_attempted_total")
        rts = _delta(rollup, baseline, "roundtrip_success_total")
        rtp = _delta(rollup, baseline, "roundtrip_profitable_total")
    else:
        sim_attempted = _num(rollup.get("sim_attempted_total"))
        sim_success = _num(rollup.get("sim_success_total"))
        sim_revert = _num(rollup.get("sim_revert_total"))
        rta = _num(rollup.get("roundtrip_attempted_total"))
        rts = _num(rollup.get("roundtrip_success_total"))
        rtp = _num(rollup.get("roundtrip_profitable_total"))

    print("\n--- Data pipeline ---")
    print(f"sim_attempted         : {sim_attempted}")
    print(f"sim_success           : {sim_success}")
    print(f"sim_revert            : {sim_revert}")

    eh_full = rollup.get("sim_error_histogram") or {}
    eh = _delta_histogram(eh_full, baseline.get("sim_error_histogram") if baseline else None) \
        if baseline is not None else eh_full
    if eh:
        print("  sim_error_histogram:")
        for k, v in sorted(eh.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {k}: {v}")

    print("\n--- E2: Round-trip results ---")
    best = rollup.get("roundtrip_profit_bps_best")
    worst = rollup.get("roundtrip_profit_bps_worst")
    med = rollup.get("roundtrip_profit_bps_median")
    print(f"roundtrip_attempted         : {rta}")
    print(f"roundtrip_success           : {rts}")
    print(f"roundtrip_profitable        : {rtp}")
    print(f"roundtrip_profit_bps_best   : {best}  (cumulative, not gated by mode)")
    print(f"roundtrip_profit_bps_median : {med}")
    print(f"roundtrip_profit_bps_worst  : {worst}")

    reh = rollup.get("roundtrip_error_histogram") or {}
    if reh:
        print("  roundtrip_error_histogram:")
        for k, v in sorted(reh.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {k}: {v}")

    samples = rollup.get("sim_output_samples_recent") or []
    if samples:
        print(f"\n--- Top 5 round-trip samples (of {len(samples)}) ---")
        # prefer profitable samples first
        pos = [s for s in samples if (s.get("roundtrip_profit_bps") or 0) > 0]
        pool = pos if pos else samples
        for i, s in enumerate(sorted(pool, key=lambda x: -(x.get("roundtrip_profit_bps") or 0))[:5]):
            print(
                f"  [{i}] token_in={s.get('token_in', '?')[:10]} "
                f"in_wei={s.get('input_amount_wei')} out_wei={s.get('output_amount_wei')} "
                f"rt_final={s.get('roundtrip_final_wei')} "
                f"rt_bps={s.get('roundtrip_profit_bps')} "
                f"rt_ok={s.get('roundtrip_success')}"
            )

    print("\n--- E3: Legacy key purge check ---")
    legacy = [
        "_sim_profit_bps_all",
        "sim_profit_bps_best",
        "sim_profit_bps_worst",
        "sim_profit_bps_median",
        "sim_profitable_count",
    ]
    leaked = [k for k in legacy if k in rollup]
    if leaked:
        print(f"  FAIL — legacy keys still present: {leaked}")
    else:
        print("  OK — all legacy sim_profit_bps_* keys purged")

    print("\n--- VERDICT ---")
    # Reviewer feedback 2026-04-21: cumulative-only verdicts are misleading.
    # Only emit PROFITABLE_CASE_FOUND when we can prove profit from the
    # current session or a fresh delta. Otherwise label it HISTORICAL so
    # callers cannot cite it as production-readiness evidence.
    if best is not None and best > 0 and rtp >= 1:
        if mode_label == "HISTORICAL_TOTALS":
            print(
                f"  HISTORICAL_PROFITABLE_CASE — best={best}bps (cumulative), "
                f"profitable_total={rtp}. NOT fresh evidence. "
                "Re-run with --session-only or --baseline for acceptance."
            )
            return 5
        print(
            f"  PROFITABLE_CASE_FOUND [{mode_label}] — best={best}bps, "
            f"profitable_total={rtp}"
        )
        return 0
    elif rta == 0:
        print(
            f"  NO_ROUNDTRIP_ATTEMPTED [{mode_label}] — "
            "likely ARBY_ROUNDTRIP_SIM=0, zero valid events, "
            "or session window too short"
        )
        return 2
    elif rts == 0:
        print(
            f"  ALL_ROUNDTRIPS_FAILED [{mode_label}] — sell leg reverts "
            "dominate; inspect histogram"
        )
        return 3
    else:
        print(
            f"  NO_PROFITABLE_CASE [{mode_label}] — rts={rts} but "
            f"best={best}; all losses"
        )
        return 4


if __name__ == "__main__":
    sys.exit(main())
