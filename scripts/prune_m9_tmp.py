#!/usr/bin/env python3
"""Prune M9 tmp diagnostics listed in m9_active_manifest.yaml tmp_stale_globs only."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / "config" / "m9_active_manifest.yaml"


def _rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(p)


def collect_prune_targets(manifest_path: Path) -> list[Path]:
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = yaml.safe_load(fh) or {}
    keep = set(manifest.get("tmp_keep", []) or [])
    targets: list[Path] = []
    seen: set[str] = set()
    for pattern in manifest.get("tmp_stale_globs", []) or []:
        for match in sorted(REPO_ROOT.glob(pattern)):
            rel = _rel(match)
            if rel in keep or rel in seen:
                continue
            seen.add(rel)
            targets.append(match)
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune M9 tmp stale files per manifest")
    parser.add_argument("--manifest", default="config/m9_active_manifest.yaml")
    parser.add_argument("--dry-run", action="store_true", help="List files only")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete files (required without --dry-run)",
    )
    args = parser.parse_args()

    manifest_path = REPO_ROOT / args.manifest
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    targets = collect_prune_targets(manifest_path)
    if not targets:
        print("Nothing to prune (no tmp_stale matches).")
        return 0

    if not args.dry_run and not args.yes:
        print("Refusing to delete without --yes (use --dry-run to preview).", file=sys.stderr)
        return 1

    deleted = 0
    for path in targets:
        rel = _rel(path)
        size = path.stat().st_size
        if args.dry_run:
            print(f"  would delete: {rel} ({size} bytes)")
        else:
            path.unlink(missing_ok=True)
            print(f"  deleted: {rel} ({size} bytes)")
            deleted += 1

    print(f"\n{'Would delete' if args.dry_run else 'Deleted'}: {len(targets)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
