#!/usr/bin/env python3
"""Audit forbidden cross-layer responsibility violations."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# (path_glob, forbidden_pattern, rule_id, message)
_RULES = [
    (
        "m9/graph_arb/bridge_builder.py",
        r"enrich_route_token_metadata\(",
        "M9_BRIDGE_LEGACY_DECIMALS_AUTHORITY",
        "bridge_builder must use M8.3 registry apply, not legacy enrich_route_token_metadata as authority",
    ),
    (
        "m8/discovery/cross_dex_expand.py",
        r"enrich_routes_decimals|enrich_route_decimals|fetch_on_chain_decimals",
        "M82_FORBIDDEN_DEPTH_DECIMALS",
        "M8.2 must not own depth/decimals enrichment",
    ),
    (
        "m8/metadata/registry.py",
        r"find_cycles|build_graph_from_inventory",
        "M83_FORBIDDEN_DISCOVERY",
        "M8.3 must not run graph discovery",
    ),
]

# Files allowed to call legacy enrich with constraints documented in matrix
_ALLOWLIST = frozenset(
    {
        "scripts/m9_enrich_bridge_decimals.py",
        "m9/graph_arb/inventory_truth.py",
        "m9/graph_arb/token_metadata.py",
        "m9/graph_arb/token_decimals.py",
        "tests/unit/test_token_metadata.py",
        "tests/unit/test_token_decimals_truth.py",
        "tests/unit/test_m9_token_decimals.py",
        "tests/unit/test_layer_responsibility.py",
    }
)


def _scan_file(path: Path, pattern: str) -> list[int]:
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rx = re.compile(pattern)
    return [i + 1 for i, line in enumerate(lines) if rx.search(line)]


def run_audit(*, strict: bool = True) -> dict:
    violations: list[dict] = []
    for rel, pattern, rule_id, message in _RULES:
        path = REPO / rel.replace("/", "\\") if "\\" in str(REPO) else REPO / rel
        hits = _scan_file(path, pattern)
        if not hits:
            continue
        # bridge_builder: allow if metadata_registry_path branch exists (post-fix)
        if rel == "m9/graph_arb/bridge_builder.py":
            text = path.read_text(encoding="utf-8")
            if "metadata_registry_path" in text and "apply_registry_to_routes" in text:
                continue
        violations.append(
            {
                "rule_id": rule_id,
                "path": rel,
                "lines": hits[:5],
                "message": message,
            }
        )

    # Scan M9 scripts for direct on-chain decimals without metadata-registry mention
    for path in (REPO / "scripts").glob("m9_*.py"):
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        if rel in _ALLOWLIST:
            continue
        if "enrich_routes_decimals" in path.read_text(encoding="utf-8"):
            violations.append(
                {
                    "rule_id": "M9_SCRIPT_LEGACY_DECIMALS",
                    "path": rel,
                    "lines": [],
                    "message": "M9 script calls legacy decimals enrich outside allowlist",
                }
            )

    # M8.3 dex workers: route metadata only — no quote/economics/depth admission
    _dex_forbidden = re.compile(
        r"economic_size_floor|pre_shadow_bridge_blockers|from m9\.graph_arb\.(runner|quoter|pool_depth_probe|cycle_capacity|bridge_builder)"
    )
    for path in (REPO / "m8" / "metadata" / "dex").glob("*.py"):
        if path.name in ("__init__.py", "base.py", "erc20.py"):
            continue
        rel = str(path.relative_to(REPO)).replace("\\", "/")
        text = path.read_text(encoding="utf-8")
        if _dex_forbidden.search(text):
            violations.append(
                {
                    "rule_id": "M83_DEX_WORKER_FORBIDDEN_QUOTE_ECON",
                    "path": rel,
                    "lines": [],
                    "message": "M8.3 dex worker must not import quote/economics/depth admission",
                }
            )
        if "save_registry(" in text:
            violations.append(
                {
                    "rule_id": "M83_DEX_WORKER_REGISTRY_WRITE",
                    "path": rel,
                    "lines": [],
                    "message": "M8.3 dex workers must not write canonical registry",
                }
            )

    ok = not violations
    return {"ok": ok, "violations": violations, "strict": strict}


def main() -> int:
    ap = argparse.ArgumentParser(description="Layer responsibility audit")
    ap.add_argument("--strict", action="store_true", default=True)
    args = ap.parse_args()
    result = run_audit(strict=args.strict)
    if result["violations"]:
        for v in result["violations"]:
            print(f"FAIL {v['rule_id']}: {v['path']} — {v['message']}")
            if v.get("lines"):
                print(f"  lines: {v['lines']}")
    else:
        print("Layer responsibility audit: PASS")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
