#!/usr/bin/env python3
"""Audit M9 active config, runtime rolling, cache, and tmp against m9_active_manifest.yaml."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "config" / "m9_active_manifest.yaml"


def _load_manifest(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def _manifest_config_status(manifest: Dict[str, Any]) -> Dict[str, str]:
    """Map config path -> audit status from manifest lists."""
    classified: Dict[str, str] = {}
    for entry in manifest.get("active_configs", []) or []:
        if entry.get("path"):
            classified[entry["path"]] = "ACTIVE"
    for path in manifest.get("legacy_required_by_tests", []) or []:
        classified[path] = "LEGACY_REQUIRED_BY_TESTS"
    for path in manifest.get("manual_probe_only", []) or []:
        classified[path] = "MANUAL_PROBE_ONLY"
    for path in manifest.get("archive_candidates", []) or []:
        classified[path] = "ARCHIVE_CANDIDATE"
    for path in manifest.get("delete_candidates", []) or []:
        classified[path] = "DELETE_CANDIDATE"
    return classified


def _classify_configs(manifest: Dict[str, Any]) -> Dict[str, str]:
    classified = _manifest_config_status(manifest)
    if not CONFIG_DIR.exists():
        return classified
    for cfg in sorted(CONFIG_DIR.glob("*.yaml")):
        rel = f"config/{cfg.name}"
        if rel not in classified:
            classified[rel] = "UNCLASSIFIED_CONFIG"
    return classified


def _adapter_metadata_bootstrap_audit() -> Dict[str, Any]:
    """Count YAML seed pools; production must use rolling discovery only."""
    meta_path = REPO_ROOT / "config" / "adapter_metadata.yaml"
    if not meta_path.exists():
        return {"bootstrap_pool_count": 0, "status": "MISSING"}
    with open(meta_path, encoding="utf-8") as fh:
        meta = yaml.safe_load(fh) or {}
    pools = (meta.get("curve") or {}).get("base", {}).get("pools") or {}
    balancer = (meta.get("balancer") or {}).get("base", {}).get("pools") or {}
    count = len(pools) + len(balancer)
    return {
        "bootstrap_pool_count": count,
        "status": "BOOTSTRAP_ONLY" if count > 0 else "ANCHORS_ONLY",
        "curve_seed_pools": len(pools),
        "balancer_seed_pools": len(balancer),
    }


def _dex_alignment(manifest: Dict[str, Any], exotic_path: Path) -> List[Dict[str, Any]]:
    dex_reg = manifest.get("dex_registry") or {}
    m9_only = set(dex_reg.get("m9_only_in_exotic") or [])
    shared = set(dex_reg.get("shared_with_dexes_yaml") or [])
    rows: List[Dict[str, Any]] = []

    exotic_dexes: Set[str] = set()
    if exotic_path.exists():
        with open(exotic_path, encoding="utf-8") as fh:
            ex = yaml.safe_load(fh) or {}
        exotic_dexes = set((ex.get("dexes") or {}).keys())

    dexes_yaml: Set[str] = set()
    dexes_path = REPO_ROOT / "config" / "dexes.yaml"
    if dexes_path.exists():
        with open(dexes_path, encoding="utf-8") as fh:
            dy = yaml.safe_load(fh) or {}
        dexes_yaml = set((dy.get("base") or {}).keys())

    for dex_id in sorted(exotic_dexes):
        in_exotic = True
        in_dexes = dex_id in dexes_yaml
        if dex_id in m9_only:
            status = "M9_ONLY" if not in_dexes else "M9_ONLY_ALSO_IN_DEXES"
        elif dex_id in shared:
            status = "SHARED" if in_dexes else "SHARED_MISSING_IN_DEXES"
        elif in_dexes:
            status = "IN_DEXES_UNLISTED"
        else:
            status = "UNLISTED"
        rows.append({
            "dex_id": dex_id,
            "in_exotic": in_exotic,
            "in_dexes_yaml": in_dexes,
            "status": status,
        })
    return rows


def run_audit(
    manifest_path: Path,
    exotic_config: Path,
    json_out: Path | None,
) -> Dict[str, Any]:
    from core.cache_freshness import cache_freshness

    manifest = _load_manifest(manifest_path)
    now_ts = datetime.now(tz=timezone.utc).timestamp()

    config_rows: List[Dict[str, Any]] = []
    for rel, status in sorted(_classify_configs(manifest).items()):
        full = REPO_ROOT / rel
        config_rows.append({
            "path": rel,
            "status": status,
            "exists": full.exists(),
        })

    runtime_rows: List[Dict[str, Any]] = []
    runtime_key_labels = {
        "runtime_rolling_current": "RUNTIME_CURRENT",
        "runtime_rolling_optional": "RUNTIME_OPTIONAL",
        "runtime_global_rolling_optional": "RUNTIME_GLOBAL_OPTIONAL",
    }
    for key, label in runtime_key_labels.items():
        for rel in manifest.get(key, []) or []:
            full = REPO_ROOT / rel
            if not full.exists():
                st = f"{label}_MISSING"
            else:
                st = label
                if full.stat().st_size > 500_000:
                    st = f"{label}_LARGE"
            runtime_rows.append({
                "path": rel,
                "status": st,
                "exists": full.exists(),
                "bytes": full.stat().st_size if full.exists() else 0,
            })

    cache_rows: List[Dict[str, Any]] = []
    for entry in manifest.get("cache_artifacts", []) or []:
        rel = entry.get("path", "")
        full = REPO_ROOT / rel
        fresh, reason = cache_freshness(
            full,
            schema_id=entry.get("schema_id"),
            chain=manifest.get("chain"),
            max_age_seconds=float(entry.get("max_age_seconds", 0)) or None,
            now_ts=now_ts,
        )
        cache_rows.append({
            "path": rel,
            "status": "CACHE_FRESH" if fresh else "CACHE_STALE",
            "reason": reason,
            "exists": full.exists(),
            "bytes": full.stat().st_size if full.exists() else 0,
        })

    tmp_rows: List[Dict[str, Any]] = []
    keep = set(manifest.get("tmp_keep", []) or [])
    for pattern in manifest.get("tmp_stale_globs", []) or []:
        for match in REPO_ROOT.glob(pattern):
            rel = _rel(match)
            if rel in keep:
                continue
            tmp_rows.append({
                "path": rel,
                "status": "TMP_STALE",
                "exists": True,
                "bytes": match.stat().st_size,
            })

    # Rolling JSON not in manifest lists
    manifest_runtime = {
        *(manifest.get("runtime_rolling_current") or []),
        *(manifest.get("runtime_rolling_optional") or []),
        *(manifest.get("runtime_global_rolling_optional") or []),
    }
    rolling_dir = REPO_ROOT / "data" / "runs" / "_rolling"
    extra_runtime: List[Dict[str, Any]] = []
    if rolling_dir.exists():
        for jf in sorted(rolling_dir.glob("*.json")):
            rel = _rel(jf)
            if rel in manifest_runtime:
                continue
            extra_runtime.append({
                "path": rel,
                "status": "RUNTIME_STALE",
                "exists": True,
                "bytes": jf.stat().st_size,
            })

    dex_rows = _dex_alignment(manifest, exotic_config)
    bootstrap = _adapter_metadata_bootstrap_audit()
    policy = manifest.get("adapter_metadata_policy") or {}

    report: Dict[str, Any] = {
        "schema_version": "m9_config_audit.1",
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "manifest": _rel(manifest_path),
        "primary_config": manifest.get("primary_config"),
        "config": config_rows,
        "runtime": runtime_rows + extra_runtime,
        "cache": cache_rows,
        "tmp": tmp_rows,
        "dex_alignment": dex_rows,
        "adapter_metadata": {
            **bootstrap,
            "production_include_config_seed": policy.get("production_include_config_seed"),
        },
        "summary": {},
    }

    legacy_missing = sum(
        1
        for r in config_rows
        if r["status"] == "LEGACY_REQUIRED_BY_TESTS" and not r["exists"]
    )

    report["summary"] = {
        "active_missing": sum(1 for r in config_rows if r["status"] == "ACTIVE" and not r["exists"]),
        "legacy_required_missing": legacy_missing,
        "unclassified_configs": sum(1 for r in config_rows if r["status"] == "UNCLASSIFIED_CONFIG"),
        "runtime_current_missing": sum(
            1 for r in runtime_rows if r["status"] == "RUNTIME_CURRENT_MISSING"
        ),
        "cache_stale": sum(1 for r in cache_rows if r["status"] == "CACHE_STALE"),
        "cache_stale_actionable": sum(
            1
            for r in cache_rows
            if r["status"] == "CACHE_STALE"
            and not str(r.get("reason", "")).startswith("stale_age")
        ),
        "tmp_stale_count": len(tmp_rows),
        "runtime_stale_count": len(extra_runtime),
        "dex_shared_missing": sum(
            1 for r in dex_rows if r["status"] == "SHARED_MISSING_IN_DEXES"
        ),
        "bootstrap_pool_count": bootstrap.get("bootstrap_pool_count", 0),
    }
    return report


CONFIG_DIR = REPO_ROOT / "config"


def _print_report(report: Dict[str, Any]) -> None:
    s = report["summary"]
    print("=== M9 Active Config Audit ===")
    print(f"manifest: {report['manifest']}")
    print(f"primary:  {report['primary_config']}")
    print(
        f"summary: active_missing={s['active_missing']} unclassified={s['unclassified_configs']} "
        f"runtime_missing={s['runtime_current_missing']} cache_stale={s['cache_stale']} "
        f"tmp_stale={s['tmp_stale_count']} runtime_stale={s['runtime_stale_count']}"
    )
    print("\n-- Config --")
    for row in report["config"]:
        flag = "OK" if row["exists"] else "MISSING"
        print(f"  [{row['status']}] {flag} {row['path']}")
    am = report.get("adapter_metadata", {})
    print(
        f"\n-- adapter_metadata: {am.get('status')} "
        f"pools={am.get('bootstrap_pool_count')} "
        f"production_include_config_seed={am.get('production_include_config_seed')}"
    )
    print("\n-- Runtime (M9 current) --")
    for row in report["runtime"]:
        if row["status"].startswith("RUNTIME_CURRENT"):
            print(f"  [{row['status']}] {row['path']} ({row.get('bytes', 0)} bytes)")
    print("\n-- Cache --")
    for row in report["cache"]:
        print(f"  [{row['status']}] {row['path']} {row.get('reason', '')}")
    if report["tmp"]:
        print("\n-- Tmp stale (candidates for prune) --")
        for row in report["tmp"][:15]:
            print(f"  [{row['status']}] {row['path']} ({row['bytes']} bytes)")
        if len(report["tmp"]) > 15:
            print(f"  ... and {len(report['tmp']) - 15} more")
    print("\n-- DEX alignment --")
    for row in report["dex_alignment"]:
        print(f"  {row['dex_id']}: {row['status']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit M9 config/runtime against manifest")
    parser.add_argument("--branch", default="m9", help="Label only (manifest branch field)")
    parser.add_argument("--config", default="config/exotic_base_anchor.yaml")
    parser.add_argument("--manifest", default="config/m9_active_manifest.yaml")
    parser.add_argument("--json", dest="json_out", default=None, help="Write JSON report path")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on active/legacy missing, unclassified configs, cache_stale, dex gaps",
    )
    args = parser.parse_args()

    manifest_path = REPO_ROOT / args.manifest
    exotic_path = REPO_ROOT / args.config
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    report = run_audit(manifest_path, exotic_path, args.json_out)
    _print_report(report)

    if args.json_out:
        out = REPO_ROOT / args.json_out
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nWrote {out}")

    s = report["summary"]
    if args.strict and (
        s["active_missing"] > 0
        or s.get("legacy_required_missing", 0) > 0
        or s["unclassified_configs"] > 0
        or s.get("cache_stale_actionable", 0) > 0
        or s["dex_shared_missing"] > 0
        or s["runtime_current_missing"] > 0
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
