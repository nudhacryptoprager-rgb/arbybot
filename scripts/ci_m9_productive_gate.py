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

    # GPT Step 9 (round-3) / GPT fix step 8: cost_model_applied check.
    # In strict mode this is a hard FAIL; otherwise a WARNING.
    # cost_model_applied=false means run was done without a config that includes a
    # [cost_model] section; estimated_cost_bps and cost_adjusted fields will all be null.
    _cost_model_applied = em.get("cost_model_applied", False)
    if not _cost_model_applied:
        if strict_bridge:
            issues.append(
                "economics_metrics.cost_model_applied=false — "
                "run with --config that includes a [cost_model] section "
                "(e.g. config/exotic_base_anchor.yaml) to populate "
                "estimated_cost_bps / cost_adjusted_net_bps fields."
            )
        else:
            print(
                "  WARNING: economics_metrics.cost_model_applied=false — "
                "run with --config that includes a [cost_model] section "
                "(e.g. config/exotic_base_anchor.yaml) to populate "
                "estimated_cost_bps / cost_adjusted_net_bps fields.",
                flush=True,
            )

    # Fix step 2: cycles_by_pricing_model taxonomy check.
    # Non-null indicates cost_model.build_cost_breakdown() ran successfully and
    # produced orthogonal pricing model coverage beyond cpmm_xyk / clmm_ticks.
    # Null → cost_model integration not complete or cost_model.py raised an exception.
    _cbpm = art.get("cycles_by_pricing_model")
    if _cbpm is None:
        print(
            "  INFO: cycles_by_pricing_model=null — cost_model taxonomy not populated. "
            "Expected after integration of m9/graph_arb/cost_model.py into artifacts.py. "
            "Check that build_cost_breakdown() does not raise during artifact build.",
            flush=True,
        )
    else:
        _model_keys = sorted(_cbpm.keys())
        _only_base = set(_model_keys) <= {"cpmm_xyk", "clmm_ticks"}
        if _only_base:
            print(
                f"  INFO: cycles_by_pricing_model only contains base models {_model_keys} — "
                "no Solidly/Curve/Balancer cycles observed yet "
                "(Phase B: add aerodrome_stable + curve_stable adapters for peg-arb coverage).",
                flush=True,
            )
        else:
            print(
                f"  INFO: cycles_by_pricing_model={_model_keys} — "
                "orthogonal pricing model taxonomy populated (RUNTIME_VALIDATED__ORTHOGONAL_PRICING_VISIBLE).",
                flush=True,
            )

    # GPT Fix step 4: strict-bridge mode — require live M8/M8.1 inputs
    if strict_bridge:
        bsm = art.get("bridge_source_metrics") or {}
        graph_ready_from_m8 = bsm.get("graph_ready_from_m8", 0)
        graph_edges_from_m8 = bsm.get("graph_edges_from_m8", None)
        m8_stale = bsm.get("m8_stale", True)
        m8_1_stale = bsm.get("m8_1_stale", True)
        unsupported_dex_count = bsm.get("unsupported_dex_count", 0)
        pending_adapter_count = bsm.get("pending_adapter_count", 0)
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
        # Step 10 (GPT): warn if any dex has truly unsupported adapter_type (not pending)
        if unsupported_dex_count > 0:
            issues.append(
                f"STRICT_BRIDGE: unsupported_dex_count={unsupported_dex_count} "
                "(dexes have no recognized adapter_type; check dex_coverage_matrix in bridge artifact "
                "and update bridge_builder._DEX_ID_TO_ADAPTER_TYPE)"
            )
        # Step 10 (GPT): info-only — pending adapters are explicitly tracked, not an error
        if pending_adapter_count > 0:
            print(
                f"  INFO: pending_adapter_count={pending_adapter_count} "
                f"(routes with recognised adapter but no M9 quote adapter yet; "
                f"tracked in m8_pending_routes for P3 delivery)",
                flush=True,
            )

        # GPT Step 8: dynamic sizing — distinguish operator intent vs zero-cycle runs
        it_strict = art.get("infra_telemetry") or {}
        _cycles_found = int(art.get("cycles_found") or 0)
        _dyn_intent = bool(it_strict.get("dynamic_size_intent", False))
        _dyn_enabled = bool(it_strict.get("dynamic_size_enabled", False))
        if not _dyn_enabled:
            if _cycles_found == 0 and _dyn_intent:
                print(
                    "  INFO: dynamic_size_enabled=False because cycles_found=0 "
                    "(dynamic_size_intent=True; no cycles reached the quoter — "
                    "fix topology/QSR first, not --dynamic-sizes flag)",
                    flush=True,
                )
            elif not _dyn_intent:
                issues.append(
                    "STRICT_BRIDGE: dynamic_size_intent=False "
                    "(productive lane requires --dynamic-sizes; "
                    "fix: orchestrator run_m9_scan must pass --dynamic-sizes flag)"
                )
            else:
                issues.append(
                    "STRICT_BRIDGE: dynamic_size_enabled=False with cycles_found>0 "
                    "(unexpected: cycles quoted but no dynamic size candidates recorded)"
                )
        if _cycles_found == 0:
            issues.append(
                "NO_CYCLES: cycles_found=0 — graph too small or topology gate blocked "
                "(check bridge graph_ready_total, productive-lane quarantine, multi-venue gate)"
            )

        # GPT Step 9: quote_backend must be raw_http and quote_workers must be 1
        qb = it_strict.get("quote_backend")
        if qb and qb != "raw_http":
            issues.append(
                f"STRICT_BRIDGE: quote_backend={qb!r} "
                "(productive lane requires raw_http; "
                "fix: orchestrator run_m9_scan must pass --quote-backend raw_http)"
            )
        qw = it_strict.get("quote_workers")
        if isinstance(qw, int) and qw > 1:
            issues.append(
                f"STRICT_BRIDGE: quote_workers={qw} "
                f"(productive lane requires quote_workers=1 to avoid RPC overload; "
                f"fix: orchestrator run_m9_scan must pass --quote-workers 1)"
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
        cycles_m8 = bsm_pass.get("cycles_with_m8_pool", "N/A")
        pos_cycles_m8 = bsm_pass.get("positive_cycles_with_m8_pool", "N/A")
        # Build per-DEX breakdown from dex_coverage_matrix
        dex_matrix = bsm_pass.get("dex_coverage_matrix") or {}
        dex_lines = []
        for dex_id, dex_info in sorted(dex_matrix.items()):
            adapter = dex_info.get("adapter_type", "?")
            ev_count = dex_info.get("event_count", 0)
            gr_count = dex_info.get("graph_ready_count", 0)
            pending = dex_info.get("adapter_pending", False)
            pend_tag = " [PENDING]" if pending else ""
            dex_lines.append(
                f"\n    {dex_id:<28} events={ev_count:<4} adapter={adapter:<22}{pend_tag}"
                f" graph_ready={gr_count}"
            )
        dex_block = "".join(dex_lines) if dex_lines else "\n    (none)"
        # cycles_with_m8_pool advisory warning
        cycles_advisory = ""
        if isinstance(cycles_m8, int) and cycles_m8 == 0:
            cycles_advisory = (
                "\n  ADVISORY: cycles_with_m8_pool=0 — M8 pools not yet in active cycles. "
                "Next target: cycles_with_m8_pool > 0."
            )
        elif isinstance(cycles_m8, int) and cycles_m8 > 0 and isinstance(pos_cycles_m8, int) and pos_cycles_m8 == 0:
            cycles_advisory = (
                "\n  STRATEGIC_WARNING: cycles_with_m8_pool>0 but positive_cycles_with_m8_pool=0. "
                "M8-sniped pools are in active cycles but none yield positive gross spread. "
                "Next target: positive_cycles_with_m8_pool > 0."
            )
        bridge_info = (
            f"\n  bridge: graph_ready_from_m8={bsm_pass.get('graph_ready_from_m8', 'N/A')}"
            f", graph_ready_total={bsm_pass.get('graph_ready_total', 'N/A')}"
            f", m8_stale={bsm_pass.get('m8_stale', 'N/A')}"
            f", m8_1_stale={bsm_pass.get('m8_1_stale', 'N/A')}"
            f", unsupported_dex_count={bsm_pass.get('unsupported_dex_count', 0)}"
            f", pending_adapter_count={bsm_pass.get('pending_adapter_count', 0)}"
            f"\n  DEX pipeline (M8 events → active routes):"
            f"\n    m8_new_pools_input:          {bsm_pass.get('m8_new_pools_input', 'N/A')}"
            f"\n    token_verified:              {bsm_pass.get('token_verified_count', 'N/A')}"
            f"\n    anchor_connected:            {bsm_pass.get('anchor_connected_count', 'N/A')}"
            f"\n    graph_ready_from_m8:         {bsm_pass.get('graph_ready_from_m8', 'N/A')}"
            f"\n    graph_ready_from_m8_new:     {bsm_pass.get('graph_ready_from_m8_new', 'N/A')}"
            f"\n    cycles_with_m8_pool:         {cycles_m8}  ← target: >0"
            f"\n    positive_cycles_with_m8_pool:{pos_cycles_m8}"
            f"\n  Per-DEX breakdown:{dex_block}"
            f"{cycles_advisory}"
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
