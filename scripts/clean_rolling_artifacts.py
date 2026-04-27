"""Clean stale entries from rolling M7 rollup artifacts.

Removes:
  * samples in `sim_failed_samples_recent` / `sim_output_samples_recent`
    that don't match current `session_id` (old session leftovers).
  * empty histogram dicts (`guard_reject_reason_histogram`, etc.) when
    they're empty — these only add noise to reviewer dumps.
  * `_roundtrip_profit_bps_all` truncated to last 200 entries.

Idempotent: safe to re-run. Writes back the same path on disk.

Usage:
    py -3.11 scripts/clean_rolling_artifacts.py
    py -3.11 scripts/clean_rolling_artifacts.py --dry-run
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROLL = Path("data/runs/_rolling")
PROFIT_BPS_KEEP = 200
SAMPLE_LISTS = ("sim_failed_samples_recent", "sim_output_samples_recent")
EMPTY_DROPPABLE = (
    "guard_reject_reason_histogram",
    "submit_blocker_histogram",
)


def clean_rollup(path: Path, dry_run: bool = False) -> dict:
    raw = path.read_text(encoding="utf-8")
    d = json.loads(raw)
    before = {
        "size_bytes": len(raw.encode("utf-8")),
        "sim_failed_samples": len(d.get("sim_failed_samples_recent") or []),
        "sim_output_samples": len(d.get("sim_output_samples_recent") or []),
        "profit_bps_all": len(d.get("_roundtrip_profit_bps_all") or []),
    }
    sid = d.get("session_id")
    # 1. drop samples not from current session
    for key in SAMPLE_LISTS:
        items = d.get(key)
        if isinstance(items, list) and sid:
            kept = [s for s in items if isinstance(s, dict) and s.get("session_id") == sid]
            d[key] = kept
    # 2. drop empty histogram dicts
    for key in EMPTY_DROPPABLE:
        v = d.get(key)
        if isinstance(v, dict) and not v:
            d.pop(key, None)
    # 3. truncate profit bps history
    pba = d.get("_roundtrip_profit_bps_all")
    if isinstance(pba, list) and len(pba) > PROFIT_BPS_KEEP:
        d["_roundtrip_profit_bps_all"] = pba[-PROFIT_BPS_KEEP:]
    new_raw = json.dumps(d, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    after = {
        "size_bytes": len(new_raw.encode("utf-8")),
        "sim_failed_samples": len(d.get("sim_failed_samples_recent") or []),
        "sim_output_samples": len(d.get("sim_output_samples_recent") or []),
        "profit_bps_all": len(d.get("_roundtrip_profit_bps_all") or []),
    }
    if not dry_run:
        path.write_text(new_raw, encoding="utf-8")
    return {"path": str(path), "session_id": sid, "before": before, "after": after}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    targets = list(ROLL.glob("m7_*rollup*.json"))
    if not targets:
        print("no rollup files found")
        return 0
    for p in targets:
        try:
            r = clean_rollup(p, dry_run=args.dry_run)
        except Exception as e:
            print(f"FAIL {p}: {e}")
            continue
        print(json.dumps(r, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
