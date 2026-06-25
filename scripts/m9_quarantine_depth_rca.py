#!/usr/bin/env python3
"""RCA: quarantined routes — false-positive depth toxicity vs genuinely dead pools."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_BRIDGE = "data/tmp/m9_bridge_inventory_graph_handoff_latest.json"
_DEFAULT_OUTPUT = "data/tmp/m9_quarantine_depth_rca_latest.json"


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 quarantine / toxic depth RCA")
    ap.add_argument("--bridge", "--inventory", dest="bridge", default=_DEFAULT_BRIDGE)
    ap.add_argument("--output", default=_DEFAULT_OUTPUT)
    args = ap.parse_args()

    bridge_path = Path(args.bridge)
    if not bridge_path.exists():
        print(f"ERROR: bridge not found: {bridge_path}", file=sys.stderr)
        return 1

    inv = json.loads(bridge_path.read_text(encoding="utf-8"))
    from m9.graph_arb.quarantine_depth_rca import run_quarantine_depth_rca

    report = run_quarantine_depth_rca(
        active_routes=list(inv.get("active_routes") or []),
        quarantined_routes=list(inv.get("quarantined_routes") or []),
    )
    report["bridge_path"] = str(bridge_path).replace("\\", "/")
    report["generated_from"] = inv.get("generated_at_utc")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(
        {
            "active_quarantine_candidates": report["active_quarantine_candidates"],
            "by_rca_bucket": report["by_rca_bucket"],
            "primary_verdict": report["primary_verdict"],
            "operator_note": report["operator_note"],
        },
        indent=2,
    ))
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
