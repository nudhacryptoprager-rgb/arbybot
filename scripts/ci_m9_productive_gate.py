#!/usr/bin/env python3
"""ci_m9_productive_gate.py — M9 productive-state lock gate (Step 1 GPT fix).

Reads data/runs/_rolling/m9_graph_latest.json and verifies that all runtime
quality gates pass.  Until all gates pass, the M8/M8.1→M9 bridge remains
locked (M9_INFRA_STABILIZATION_BEFORE_M8_BRIDGE policy).

Exit codes:
  0 — PASS: all runtime_gates pass, duration_fulfilled=True
  1 — FAIL: one or more gates failed (details printed to stdout)
  2 — MISSING: artifact does not exist or is unreadable

Usage:
  py -3.11 scripts/ci_m9_productive_gate.py
  py -3.11 scripts/ci_m9_productive_gate.py --artifact path/to/m9_graph.json
  py -3.11 scripts/ci_m9_productive_gate.py --strict-bridge
    (also checks bridge_source_metrics.graph_ready_from_m8 > 0 and stale=False)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path

# Ensure stdout uses UTF-8 on Windows consoles (cp1251 raises UnicodeEncodeError
# when artifact field values contain non-ASCII characters).
if hasattr(sys.stdout, "buffer") and sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)

_DEFAULT_ARTIFACT = Path("data/runs/_rolling/m9_graph_latest.json")

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_MISSING = 2


def _load_artifact(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def run_gate(artifact_path: Path, strict_bridge: bool = False) -> int:
    art = _load_artifact(artifact_path)
    if art is None:
        print(f"MISSING: artifact not found or unreadable: {artifact_path}", flush=True)
        return EXIT_MISSING

    issues: list[str] = []

    # Check duration_fulfilled
    if not art.get("duration_fulfilled"):
        elapsed = art.get("elapsed_s", 0)
        dur_s = (art.get("requested_duration_minutes") or art.get("duration_minutes") or 0) * 60
        issues.append(
            f"duration_fulfilled=False (elapsed={elapsed:.0f}s / target={dur_s:.0f}s)"
        )

    # Check runtime_gates
    rg = art.get("runtime_gates") or {}
    if not rg:
        issues.append("runtime_gates block missing from artifact")
    else:
        if rg.get("all_pass") is not True:
            for key, val in rg.items():
                if isinstance(val, dict) and not val.get("pass"):
                    v = val.get("value")
                    t = val.get("threshold")
                    issues.append(f"runtime_gates.{key}: FAIL (value={v}, threshold={t})")

    # Fix 8: warn if unverified_active_routes is missing entirely (runner not using --require-factory-verified)
    it = art.get("infra_telemetry") or {}
    if "unverified_active_routes" not in it:
        issues.append(
            "WARN: infra_telemetry.unverified_active_routes missing — "
            "run with --require-factory-verified for inventory purity guarantee"
        )

    # GPT Step 8 invariant: if dynamic_size_enabled=True, dynamic_size_selected_count must be > 0
    it = art.get("infra_telemetry") or {}
    if it.get("dynamic_size_enabled"):
        dsc = it.get("dynamic_size_selected_count", 0)
        if dsc == 0:
            issues.append(
                "dynamic_size_enabled=True but dynamic_size_selected_count=0 "
                "(no successful dynamic-size quotes; all dynamic cycles may have failed)"
            )

    # Fix 7: sizes_usd_source invariant — when dynamic_size_enabled, source must be config.scan_params
    if it.get("dynamic_size_enabled"):
        sizes_src = it.get("sizes_usd_source")
        if sizes_src is not None and sizes_src != "config.scan_params":
            issues.append(
                f"INVARIANT: dynamic_size_enabled=True but sizes_usd_source={sizes_src!r} "
                "(expected 'config.scan_params' — set scan_params.sizes_usd in config YAML, "
                "not via CLI --sizes-usd)"
            )

    # GPT Step 6: toxic_route_rate gate (initial threshold 0.90, to be tightened to 0.50)
    _TOXIC_RATE_THRESHOLD = 0.90
    em = art.get("economics_metrics") or {}
    toxic_rate = em.get("toxic_route_rate")
    if toxic_rate is not None and toxic_rate >= _TOXIC_RATE_THRESHOLD:
        issues.append(
            f"toxic_route_rate={toxic_rate:.4f} >= {_TOXIC_RATE_THRESHOLD} "
            f"(run pool_depth_probe --update-quarantine to expand quarantine coverage; "
            f"target: <0.90 for smoke29, <0.50 long-term)"
        )

    # GPT Fix step 4: strict-bridge mode — require live M8/M8.1 inputs
    if strict_bridge:
        bsm = art.get("bridge_source_metrics") or {}
        graph_ready_from_m8 = bsm.get("graph_ready_from_m8", 0)
        graph_edges_from_m8 = bsm.get("graph_edges_from_m8", None)
        m8_stale = bsm.get("m8_stale", True)
        m8_1_stale = bsm.get("m8_1_stale", True)
        if graph_ready_from_m8 <= 0:
            issues.append(
                f"STRICT_BRIDGE: graph_ready_from_m8={graph_ready_from_m8} "
                "(must be >0 for live bridge acceptance; "
                "run fresh M8 sniper + m9_bridge_build.py to populate)"
            )
        if graph_edges_from_m8 is not None and graph_edges_from_m8 == 0:
            issues.append(
                f"STRICT_BRIDGE: graph_edges_from_m8=0 "
                "(M8 routes not entering graph — check pair_id format uses '_' separator; "
                "rebuild bridge + re-run runner)"
            )
        if m8_stale:
            issues.append(
                "STRICT_BRIDGE: m8_stale=True "
                "(run fresh M8 smoke: ARBY_SNIPER_ENABLE=1 py -3.11 -m m8.runtime.smoke_run --chain base)"
            )
        if m8_1_stale:
            issues.append(
                "STRICT_BRIDGE: m8_1_stale=True "
                "(run M8.1 refresh: py -3.11 scripts/m8_1_stable_anchor_run.py)"
            )

    if issues:
        print("FAIL — M9 productive-state gate:", flush=True)
        for issue in issues:
            print(f"  ! {issue}", flush=True)
        # Step 7 (GPT): always show dynamic_size operator info, even on FAIL
        it_fail = art.get("infra_telemetry") or {}
        _dyn_e = it_fail.get("dynamic_size_enabled", False)
        _dyn_c = it_fail.get("dynamic_size_selected_count", 0)
        _dyn_r = it_fail.get("dynamic_size_selection_rate")
        print(
            f"  dynamic_size_enabled={_dyn_e}, selected_count={_dyn_c}"
            + (f", selection_rate={_dyn_r}" if _dyn_r is not None else ""),
            flush=True,
        )
        print("", flush=True)
        print(
            "Policy: M8/M8.1→M9 bridge is locked until all runtime_gates pass.\n"
            "Run smoke soak to verify: py -3.11 -m m9.graph_arb.runner --chain base "
            "--config config/exotic_base_anchor.yaml --duration-minutes 15",
            flush=True,
        )
        return EXIT_FAIL

    # PASS
    mc_rate = (art.get("infra_telemetry") or {}).get("multicall_success_rate")
    qsr = art.get("qsr")
    sweeps = art.get("sweeps_completed", "?")
    dyn_enabled = it.get("dynamic_size_enabled", False)
    dyn_count = it.get("dynamic_size_selected_count", 0)
    dyn_rate = it.get("dynamic_size_selection_rate")
    em_pass = art.get("economics_metrics") or {}
    toxic_rate_val = em_pass.get("toxic_route_rate")
    dyn_info = (
        f"  dynamic_size_enabled={dyn_enabled}, selected_count={dyn_count}"
        + (f", selection_rate={dyn_rate}" if dyn_rate is not None else "")
    )
    toxic_info = (
        f"  toxic_route_rate={toxic_rate_val:.4f} (threshold <0.90)"
        if toxic_rate_val is not None
        else "  toxic_route_rate=N/A"
    )
    bridge_info = ""
    if strict_bridge:
        bsm_pass = art.get("bridge_source_metrics") or {}
        bridge_info = (
            f"\n  bridge: graph_ready_from_m8={bsm_pass.get('graph_ready_from_m8', 'N/A')}"
            f", graph_edges_from_m8={bsm_pass.get('graph_edges_from_m8', 'N/A')}"
            f", m8_stale={bsm_pass.get('m8_stale', 'N/A')}"
            f", m8_1_stale={bsm_pass.get('m8_1_stale', 'N/A')}"
            f", graph_ready_total={bsm_pass.get('graph_ready_total', 'N/A')}"
            f", cycles_with_m8_pool={bsm_pass.get('cycles_with_m8_pool', 'N/A')}"
            f", positive_cycles_with_m8_pool={bsm_pass.get('positive_cycles_with_m8_pool', 'N/A')}"
        )
    print(
        f"PASS — M9 productive-state gate\n"
        f"  multicall_success_rate={mc_rate}\n"
        f"  qsr={qsr}\n"
        f"  sweeps={sweeps}\n"
        f"  runtime_gates.all_pass=True\n"
        f"{dyn_info}\n"
        f"{toxic_info}"
        f"{bridge_info}",
        flush=True,
    )
    return EXIT_PASS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=_DEFAULT_ARTIFACT,
        help="Path to m9_graph_latest.json (default: data/runs/_rolling/m9_graph_latest.json)",
    )
    parser.add_argument(
        "--strict-bridge",
        action="store_true",
        default=False,
        help=(
            "Also require bridge_source_metrics.graph_ready_from_m8>0 "
            "and m8_stale=False, m8_1_stale=False. "
            "Use for full live bridge acceptance (not just canary smoke)."
        ),
    )
    args = parser.parse_args()
    sys.exit(run_gate(args.artifact, strict_bridge=args.strict_bridge))


if __name__ == "__main__":
    main()
