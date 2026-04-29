#!/usr/bin/env python3
"""Offline replay for SCORER_SIM_DIVERGENCE samples.

Reviewer post-2h-soak step #2: each sample captured in
``m7_hot_rollup_latest.json.scorer_sim_divergence_samples_recent`` (or
``m7_hot_latest.json``) must be replayable WITHOUT live RPC so the
quote-model divergence between fast-path scorer and rpc_fork sim is
analyzable in isolation.

This tool:
  - reads samples from a rolling artifact (or stdin/JSON file),
  - prints a tabular summary of scored vs roundtrip bps and the gap,
  - extracts the canonical scorer/sim inputs for each sample,
  - flags missing/inconsistent fields,
  - emits a deterministic JSON replay manifest under a chosen out-dir
    (one file per sample) containing all fields needed to reproduce the
    scorer call AND describe what the rpc_fork sim observed.

NO network calls. NO rpc_fork. NO scoring_parallel imports — the goal is
a pure observability tool that surfaces the structural mismatch.

Usage:
  py -3.11 scripts/replay_divergence_samples.py \\
      --rollup data/runs/_rolling/m7_hot_rollup_latest.json \\
      --out-dir data/runs/_replays/divergence

Exit codes:
  0 success
  1 no samples found
  2 input artifact missing/corrupt
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


REPRODUCER_REQUIRED_FIELDS = (
    "event_id", "pair", "direction", "amount_in_wei",
    "scored_net_bps", "roundtrip_profit_bps", "blocker_tag",
    "token_in_decimals", "fee_tier",
)


def load_samples(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    samples = raw.get("scorer_sim_divergence_samples_recent")
    if not isinstance(samples, list):
        return []
    return [s for s in samples if isinstance(s, dict)]


def summarize(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not samples:
        return {"count": 0}
    gaps = []
    for s in samples:
        scored = s.get("scored_net_bps")
        sim = s.get("roundtrip_profit_bps")
        if isinstance(scored, (int, float)) and isinstance(sim, (int, float)):
            gaps.append(scored - sim)
    return {
        "count": len(samples),
        "with_numeric_gap": len(gaps),
        "gap_min_bps": min(gaps) if gaps else None,
        "gap_max_bps": max(gaps) if gaps else None,
        "gap_avg_bps": (sum(gaps) / len(gaps)) if gaps else None,
        "unique_pairs": sorted({str(s.get("pair")) for s in samples if s.get("pair")}),
        "unique_pools": sorted({str(s.get("pool_address")) for s in samples if s.get("pool_address")}),
        "directions": sorted({str(s.get("direction")) for s in samples if s.get("direction")}),
        "fee_tiers": sorted({s.get("fee_tier") for s in samples if s.get("fee_tier") is not None}),
    }


def field_audit(sample: Dict[str, Any]) -> List[str]:
    return [k for k in REPRODUCER_REQUIRED_FIELDS if sample.get(k) in (None, "", [])]


def build_manifest(sample: Dict[str, Any], idx: int) -> Dict[str, Any]:
    return {
        "replay_index": idx,
        "blocker_tag": sample.get("blocker_tag"),
        "scorer_inputs": {
            "pair": sample.get("pair"),
            "pool_address": sample.get("pool_address"),
            "venue": sample.get("venue"),
            "fee_tier": sample.get("fee_tier"),
            "adapter_type": sample.get("adapter_type"),
            "direction": sample.get("direction"),
            "token_in": sample.get("token_in"),
            "token_out": sample.get("token_out"),
            "token_in_decimals": sample.get("token_in_decimals"),
            "token_out_decimals": sample.get("token_out_decimals"),
            "amount_in_wei": sample.get("amount_in_wei"),
        },
        "scorer_observed_bps": sample.get("scored_net_bps"),
        "sim_observed": {
            "input_amount_wei": sample.get("sim_input_wei"),
            "output_amount_wei": sample.get("sim_output_wei"),
            "roundtrip_attempted": sample.get("roundtrip_attempted"),
            "roundtrip_success": sample.get("roundtrip_success"),
            "roundtrip_profit_bps": sample.get("roundtrip_profit_bps"),
        },
        "size_usd_estimate": sample.get("size_usd_estimate"),
        "missing_required_fields": field_audit(sample),
        "_session": {
            "session_id": sample.get("session_id"),
            "sample_updated_at": sample.get("sample_updated_at"),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--rollup",
        type=Path,
        default=Path("data/runs/_rolling/m7_hot_rollup_latest.json"),
        help="rolling artifact containing scorer_sim_divergence_samples_recent",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("data/runs/_replays/divergence"),
        help="directory to write replay manifests (created if missing)",
    )
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    try:
        samples = load_samples(args.rollup)
    except FileNotFoundError:
        print(f"FAIL: rollup not found: {args.rollup}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"FAIL: rollup JSON parse error: {exc}", file=sys.stderr)
        return 2

    summary = summarize(samples)
    if not samples:
        if not args.quiet:
            print(json.dumps({"status": "NO_SAMPLES", "summary": summary}, indent=2))
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for idx, s in enumerate(samples):
        manifest = build_manifest(s, idx)
        out_path = args.out_dir / f"divergence_replay_{idx:03d}.json"
        out_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        written.append(str(out_path))

    report = {
        "status": "OK",
        "rollup": str(args.rollup),
        "out_dir": str(args.out_dir),
        "summary": summary,
        "manifests_written": len(written),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
