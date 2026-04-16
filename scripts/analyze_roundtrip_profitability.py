"""Post-soak profitability analyzer for E1/E2/E3 validation.

Reads canonical rolling artifacts under data/runs/_rolling/ and reports:
  * Data pipeline health (events / sims / STF errors)
  * Round-trip coverage (attempted / success / profitable totals)
  * Round-trip profit distribution (best / median / worst bps)
  * Error histogram (why round-trips fail)
  * Per-event samples (sim_output_samples_recent)

Verdict: PROFITABLE_CASE_FOUND iff roundtrip_profit_bps_best > 0
         AND roundtrip_profitable_total >= 1.
"""
from __future__ import annotations

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


def _num(x):
    return 0 if x is None else x


def main() -> int:
    print("=" * 70)
    print("E1/E2/E3 POST-SOAK ANALYSIS")
    print("=" * 70)

    rollup = _load("m7_hot_rollup_latest.json")
    summary = _load("run_summary_latest.json")
    latest = _load("_latest.json")

    if rollup is None:
        print("! m7_hot_rollup_latest.json missing — soak did not produce rollup")
        return 1

    print(f"\nlast_updated          : {rollup.get('last_updated')}")
    print(f"session_id            : {rollup.get('session_id', 'n/a')}")
    print(f"windows_seen          : {rollup.get('windows_seen', 0)}")
    print(f"events_total          : {_num(rollup.get('events_total'))}")

    print("\n--- Data pipeline ---")
    print(f"sim_attempted_total   : {_num(rollup.get('sim_attempted_total'))}")
    print(f"sim_success_total     : {_num(rollup.get('sim_success_total'))}")
    print(f"sim_revert_total      : {_num(rollup.get('sim_revert_total'))}")

    eh = rollup.get("sim_error_histogram") or {}
    if eh:
        print("  sim_error_histogram:")
        for k, v in sorted(eh.items(), key=lambda kv: -kv[1])[:10]:
            print(f"    {k}: {v}")

    print("\n--- E2: Round-trip results ---")
    rta = _num(rollup.get("roundtrip_attempted_total"))
    rts = _num(rollup.get("roundtrip_success_total"))
    rtp = _num(rollup.get("roundtrip_profitable_total"))
    best = rollup.get("roundtrip_profit_bps_best")
    worst = rollup.get("roundtrip_profit_bps_worst")
    med = rollup.get("roundtrip_profit_bps_median")
    print(f"roundtrip_attempted_total   : {rta}")
    print(f"roundtrip_success_total     : {rts}")
    print(f"roundtrip_profitable_total  : {rtp}")
    print(f"roundtrip_profit_bps_best   : {best}")
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
    if best is not None and best > 0 and rtp >= 1:
        print(f"  PROFITABLE_CASE_FOUND — best={best}bps, profitable_total={rtp}")
        return 0
    elif rta == 0:
        print("  NO_ROUNDTRIP_ATTEMPTED — likely ARBY_ROUNDTRIP_SIM=0 or zero valid events")
        return 2
    elif rts == 0:
        print("  ALL_ROUNDTRIPS_FAILED — sell leg reverts dominate; inspect histogram")
        return 3
    else:
        print(f"  NO_PROFITABLE_CASE — rts={rts} but best={best}; all losses")
        return 4


if __name__ == "__main__":
    sys.exit(main())
