#!/usr/bin/env python3
"""Pipeline stage: materialize immutable effective execution inventory once per session."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_BRIDGE = "data/tmp/m9_bridge_inventory_production_latest.json"
_DEFAULT_CONFIG = "config/exotic_base_anchor.yaml"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Materialize session-bound effective execution inventory (single writer)"
    )
    ap.add_argument("--bridge", "--inventory", dest="bridge", default=_DEFAULT_BRIDGE)
    ap.add_argument("--config", default=_DEFAULT_CONFIG)
    ap.add_argument("--chain", default="base")
    ap.add_argument("--session-id", default=None)
    ap.add_argument(
        "--output",
        default=None,
        help="Effective inventory path (default: session-namespaced under data/tmp/)",
    )
    ap.add_argument("--force", action="store_true", help="Re-materialize even if manifest matches")
    args = ap.parse_args()

    from m9.graph_arb.effective_inventory import (
        build_execution_content_fingerprint,
        materialize_effective_inventory,
        resolve_effective_inventory_path,
    )
    from m9.graph_arb.universe_contract import bind_cli_session_to_env, resolve_session_id

    bind_cli_session_to_env(args.session_id)
    session_id = resolve_session_id(args.session_id)
    output_path = args.output or resolve_effective_inventory_path(session_id)

    try:
        out = materialize_effective_inventory(
            args.bridge,
            args.config,
            chain=args.chain,
            output_path=output_path,
            session_id=session_id,
            require_post_depth=True,
            force=bool(args.force),
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    doc = json.loads(Path(out).read_text(encoding="utf-8"))
    manifest = doc.get("effective_inventory_manifest") or {}
    summary = {
        "effective_inventory_path": out,
        "session_id": session_id,
        "source_bridge_path": args.bridge,
        "execution_content_fingerprint": manifest.get("execution_content_fingerprint")
        or build_execution_content_fingerprint(doc),
        "route_universe_hash": manifest.get("route_universe_hash"),
        "immutable": manifest.get("immutable"),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
