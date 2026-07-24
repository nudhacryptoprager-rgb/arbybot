#!/usr/bin/env python3
"""M8.2 cross-DEX expansion — find pools across all configured Base DEXes for M8 tokens."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

log = logging.getLogger("m8_cross_dex_expand")


def main() -> int:
    p = argparse.ArgumentParser(description="M8.2 cross-DEX pool expansion")
    p.add_argument("--chain", default="base")
    p.add_argument("--config", default="config/exotic_base_anchor.yaml")
    p.add_argument(
        "--input",
        default="data/runs/_rolling/m8_pending_pairs.json",
        help="M8.2 pending-pair registry JSON",
    )
    p.add_argument(
        "--anchor",
        default="data/runs/_rolling/m8_1_stable_anchor_latest.json",
        help="M8.1 stable anchor artifact (optional pairs)",
    )
    p.add_argument(
        "--output",
        default="data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    )
    p.add_argument("--dry-run", action="store_true", help="Registry venues only; no factory RPC")
    p.add_argument(
        "--expansion-mode",
        choices=("pair_anchor", "token_neighborhood"),
        default="token_neighborhood",
        help="pair_anchor=legacy; token_neighborhood=per-token subgraph (default)",
    )
    p.add_argument("--max-pairs", type=int, default=None, help="Cap tokens/pairs (debug)")
    p.add_argument(
        "--external-hints",
        default=None,
        help="Rolling M8.2 external pool hints JSON (hint-only; verified in expansion)",
    )
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--scan-mode",
        choices=("audit_full", "hot_path_incremental", "candidate_summary"),
        default="candidate_summary",
        help="audit_full=serial matrix; candidate_summary=batch+dedup (default); hot_path=single-venue factory scan",
    )
    p.add_argument(
        "--progress",
        default="data/tmp/m8_cross_dex_expand_progress.json",
        help="Progress artifact for long foreground runs",
    )
    p.add_argument(
        "--token-subset-file",
        default=None,
        help="JSON file with tokens[] — limit expansion to this hot-path subset",
    )
    p.add_argument(
        "--pipeline-hot",
        action="store_true",
        help="Hot-path mode telemetry (refuses public-only RPC when unset bootstrap)",
    )
    p.add_argument(
        "--benchmark",
        action="store_true",
        help="Compare audit_full and candidate_summary on a dry-run sample",
    )
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from pathlib import Path

    from m8.discovery.cross_dex_artifact import write_artifact
    from m8.discovery.cross_dex_expand import expand_cross_dex, load_yaml_config

    config_path = Path(args.config)
    config = load_yaml_config(config_path)

    registry = None
    if Path(args.input).exists():
        with open(args.input, encoding="utf-8") as fh:
            registry = json.load(fh)
    else:
        log.warning("Registry not found: %s", args.input)

    anchor_artifact = None
    if Path(args.anchor).exists():
        with open(args.anchor, encoding="utf-8") as fh:
            anchor_artifact = json.load(fh)

    external_hints = None
    if args.external_hints:
        hints_path = Path(args.external_hints)
        if hints_path.exists():
            with open(hints_path, encoding="utf-8") as fh:
                external_hints = json.load(fh)
            log.info("Loaded external hints: %s", args.external_hints)
        else:
            log.warning("External hints not found: %s", args.external_hints)

    if args.benchmark:
        import time
        from pathlib import Path as _Path

        sample = args.max_pairs or 50
        t0 = time.monotonic()
        audit_art = expand_cross_dex(
            chain=args.chain,
            config=config,
            registry=registry,
            anchor_artifact=anchor_artifact,
            dry_run=True,
            max_pairs=sample,
            expansion_mode=args.expansion_mode,
            external_hints_artifact=external_hints,
            scan_mode="audit_full",
        )
        audit_s = round(time.monotonic() - t0, 3)
        t1 = time.monotonic()
        batch_art = expand_cross_dex(
            chain=args.chain,
            config=config,
            registry=registry,
            anchor_artifact=anchor_artifact,
            dry_run=True,
            max_pairs=sample,
            expansion_mode=args.expansion_mode,
            external_hints_artifact=external_hints,
            scan_mode="candidate_summary",
        )
        batch_s = round(time.monotonic() - t1, 3)
        bench = {
            "schema_version": "m8_cross_dex_benchmark.1",
            "sample_tokens": sample,
            "audit_full_s": audit_s,
            "candidate_summary_s": batch_s,
            "audit_scan_attempts": (audit_art.get("scan_telemetry") or {}).get(
                "scan_actual_attempts"
            ),
            "batch_scan_attempts": (batch_art.get("scan_telemetry") or {}).get(
                "scan_actual_attempts"
            ),
        }
        bench_path = _Path("data/tmp/m8_cross_dex_benchmark_latest.json")
        bench_path.parent.mkdir(parents=True, exist_ok=True)
        bench_path.write_text(json.dumps(bench, indent=2), encoding="utf-8")
        log.info("benchmark written %s audit_s=%s batch_s=%s", bench_path, audit_s, batch_s)
        return 0

    artifact = expand_cross_dex(
        chain=args.chain,
        config=config,
        registry=registry,
        anchor_artifact=anchor_artifact,
        dry_run=args.dry_run,
        max_pairs=args.max_pairs,
        expansion_mode=args.expansion_mode,
        external_hints_artifact=external_hints,
        scan_mode=args.scan_mode,
        progress_path=args.progress,
        token_subset_file=args.token_subset_file,
    )
    artifact["config_path"] = str(config_path).replace("\\", "/")
    artifact["input_registry_path"] = args.input
    if args.external_hints:
        artifact["external_hints_path"] = args.external_hints
    if args.token_subset_file:
        artifact["token_subset_file"] = args.token_subset_file
    if args.pipeline_hot or args.scan_mode == "hot_path_incremental":
        artifact.setdefault("summary", {})["expansion_lane"] = "time_to_mirror_hot"

    if not args.dry_run:
        write_artifact(artifact, Path(args.output))
        log.info("Written: %s", args.output)
    else:
        log.info("Dry-run complete (artifact not written)")

    s = artifact["summary"]
    log.info(
        "mode=%s tokens_in=%d routes_admitted=%d subgraph_ready_tokens=%s dry_run=%s",
        s.get("expansion_mode", "?"),
        s.get("tokens_in", 0),
        s.get("routes_admitted_count", 0),
        s.get("subgraph_ready_tokens", s.get("multi_venue_tokens", "?")),
        s.get("dry_run"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
