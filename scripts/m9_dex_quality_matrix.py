#!/usr/bin/env python3
"""Emit per-DEX quality matrix from bridge/expansion/shadow artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_BRIDGE = REPO_ROOT / "data/tmp/m9_bridge_inventory_shadow_latest.json"
_DEFAULT_EXPANSION = REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json"
_DEFAULT_SHADOW = REPO_ROOT / "data/tmp/m9_graph_bridge_shadow_latest.json"
_DEFAULT_CONFIG = REPO_ROOT / "config/exotic_base_anchor.yaml"
_DEFAULT_OUT = REPO_ROOT / "data/tmp/m9_dex_quality_matrix_latest.json"


def _load(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_yaml_config(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 per-DEX quality matrix")
    ap.add_argument("--bridge", default=str(_DEFAULT_BRIDGE))
    ap.add_argument("--expansion", default=str(_DEFAULT_EXPANSION))
    ap.add_argument("--shadow", default=str(_DEFAULT_SHADOW))
    ap.add_argument("--config", default=str(_DEFAULT_CONFIG))
    ap.add_argument("--output", default=str(_DEFAULT_OUT))
    args = ap.parse_args()

    from m9.graph_arb.dex_quality_matrix import build_dex_quality_matrix

    bridge_doc = _load(Path(args.bridge))
    report = build_dex_quality_matrix(
        config=_load_yaml_config(Path(args.config)),
        bridge=bridge_doc,
        expansion=_load(Path(args.expansion)),
        shadow=_load(Path(args.shadow)),
    )
    bsm = (bridge_doc or {}).get("bridge_source_metrics") or {}
    report["bridge_provenance"] = {
        k: bsm.get(k)
        for k in (
            "m8_provenance_enforced",
            "m8_tokens_in",
            "hint_tokens_matched",
            "specialized_index_tokens_matched",
            "routes_rejected_not_m8_derived",
            "canonical_routes_count",
        )
        if bsm.get(k) is not None
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    weak = [
        dex
        for dex, row in report["matrix"].items()
        if row["bridge_active_routes"] == 0
    ]
    print(f"configured={report['configured_dex_count']} visible_bridge={report['visible_in_bridge_count']}")
    print(f"blockers={report['blockers']}")
    print(f"absent_from_bridge={weak[:8]}")
    print("written:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
