"""M8.2 candidate DEX registry — coverage expansion beyond canonical 13 DEX."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_DEFAULT_REGISTRY = (
    Path(__file__).resolve().parents[2] / "config" / "m8_2_candidate_dex_registry.yaml"
)

_REGISTRY_STATUSES = frozenset({"configured", "hint_only", "unsupported", "verified"})


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_candidate_dex_registry(
    path: Optional[str | Path] = None,
) -> Dict[str, Any]:
    """Load YAML candidate registry (falls back to empty on missing file)."""
    reg_path = Path(path) if path else _DEFAULT_REGISTRY
    if not reg_path.exists():
        return {"schema_version": "m8_2_candidate_dex_registry.0", "candidates": {}}
    try:
        import yaml
    except ImportError:
        return {"schema_version": "m8_2_candidate_dex_registry.0", "candidates": {}}
    data = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    data.setdefault("candidates", {})
    return data


def candidate_entries(registry: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    return dict((registry or {}).get("candidates") or {})


def candidate_dex_rows_for_scan(
    registry: Dict[str, Any],
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """DEX rows for candidate coverage scan (configured + explicit unsupported lanes)."""
    dexes = config.get("dexes") or {}
    rows: List[Dict[str, Any]] = []
    for dex_id, meta in candidate_entries(registry).items():
        status = str(meta.get("registry_status") or "unsupported")
        if status not in _REGISTRY_STATUSES:
            status = "unsupported"
        cfg_id = str(meta.get("config_dex_id") or dex_id)
        cfg = dexes.get(cfg_id) or {}
        rows.append({
            "dex_id": dex_id,
            "config_dex_id": cfg_id,
            "registry_status": status,
            "adapter_type": meta.get("adapter_type")
            or cfg.get("adapter_type")
            or "",
            "factory": cfg.get("factory", ""),
            "priority": meta.get("priority", "P1"),
            "unsupported_reason": str(
                meta.get("unsupported_reason") or f"UNSUPPORTED_{status.upper()}"
            ),
        })
    return rows


def configured_candidate_dex_ids(registry: Dict[str, Any]) -> List[str]:
    return sorted(
        dex_id
        for dex_id, meta in candidate_entries(registry).items()
        if str(meta.get("registry_status")) in ("configured", "verified")
    )


def unsupported_candidate_dex_ids(registry: Dict[str, Any]) -> List[str]:
    return sorted(
        dex_id
        for dex_id, meta in candidate_entries(registry).items()
        if str(meta.get("registry_status")) in ("hint_only", "unsupported")
    )


def candidate_scan_reason(entry: Dict[str, Any]) -> str:
    status = str(entry.get("registry_status") or "unsupported")
    if status in ("hint_only", "unsupported"):
        return str(entry.get("unsupported_reason") or f"UNSUPPORTED_{status.upper()}")
    if status == "configured" and not entry.get("factory"):
        return "UNSUPPORTED_FACTORY_MISSING"
    return "OK"


def query_iziswap_pool(
    rpc_url: str,
    factory_address: str,
    token_x: str,
    token_y: str,
    fee: int,
) -> Optional[str]:
    """iZiSwap factory.pool(tokenX, tokenY, fee) — tokenX < tokenY."""
    import os

    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return None
    tx, ty = sorted([token_x.lower(), token_y.lower()])
    abi = [
        {
            "inputs": [
                {"internalType": "address", "name": "tokenX", "type": "address"},
                {"internalType": "address", "name": "tokenY", "type": "address"},
                {"internalType": "uint24", "name": "fee", "type": "uint24"},
            ],
            "name": "pool",
            "outputs": [{"internalType": "address", "name": "", "type": "address"}],
            "stateMutability": "view",
            "type": "function",
        }
    ]
    try:
        from web3 import Web3

        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
        factory = w3.eth.contract(
            address=Web3.to_checksum_address(factory_address),
            abi=abi,
        )
        pool = factory.functions.pool(
            Web3.to_checksum_address(tx),
            Web3.to_checksum_address(ty),
            fee,
        ).call()
        if str(pool).lower() == ("0x" + "0" * 40):
            return None
        return pool.lower()
    except Exception:
        return None


def build_registry_summary(
    registry: Dict[str, Any],
    *,
    candidate_telemetry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entries = candidate_entries(registry)
    by_status: Dict[str, int] = {}
    for meta in entries.values():
        st = str(meta.get("registry_status") or "unsupported")
        by_status[st] = int(by_status.get(st, 0)) + 1
    attempted = (candidate_telemetry or {}).get("candidate_scan_attempted_by_dex") or {}
    return {
        "candidate_dexes_seen": len(entries),
        "candidate_dexes_configured": len(configured_candidate_dex_ids(registry)),
        "unsupported_candidate_dexes": unsupported_candidate_dex_ids(registry),
        "candidate_dexes_by_status": by_status,
        "candidate_scan_attempted_by_dex": dict(attempted),
    }


_RADAR_STUB_PROVIDERS = (
    "coinmarketcap_dex",
    "dexpaprika",
    "moralis",
    "codex_defined",
)


def build_radar_metrics(
    hints: Optional[Dict[str, Any]],
    expansion: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Mirror-radar yield and truth metrics for M8.2 acceptance."""
    hm = (hints or {}).get("metrics") or {}
    exp_summary = (expansion or {}).get("summary") or {}

    mirror_yield = dict(hm.get("per_source_verified_yield") or {})
    for src, count in (hm.get("mirror_source_yield_by_provider") or {}).items():
        mirror_yield.setdefault(src, int(count or 0))
    for src, count in (hm.get("hint_source_pool_counts") or {}).items():
        mirror_yield.setdefault(f"{src}_pools", int(count or 0))

    status_counts = dict(hm.get("hint_status_counts") or exp_summary.get("hint_status_counts") or {})
    total_hints = int(hm.get("hint_pools_seen") or exp_summary.get("hint_artifact_pools") or 0)
    stale = int(status_counts.get("HINT_STALE", 0))
    verified = sum(
        int(status_counts.get(s, 0))
        for s in (
            "HINT_ONCHAIN_VERIFIED",
            "HINT_POOLID_VERIFIED",
            "HINT_FACTORY_VERIFIED",
            "QUOTE_SMOKE_OK",
            "BRIDGE_SHADOW_READY",
        )
    )
    hint_only = int(status_counts.get("HINT_ONLY", 0))

    pools_seen = max(total_hints, sum(int(v) for v in status_counts.values()), 1)
    stale_rate = round(stale / pools_seen, 4) if pools_seen else 0.0
    verify_rate = round(verified / pools_seen, 4) if pools_seen else 0.0

    freshness_s = hm.get("hint_freshness_s")
    if freshness_s is None and hints:
        freshness_s = hm.get("hint_source_latency_s")

    second_pool_source = dict(hm.get("second_venue_source") or {})
    if not second_pool_source and mirror_yield:
        second_pool_source = {
            k: v for k, v in mirror_yield.items() if not k.endswith("_pools")
        }

    truth = "ONCHAIN_VERIFIED" if verified > hint_only else "HINT_DOMINANT"
    if stale > verified:
        truth = "STALE_HINT_RISK"
    if verified == 0 and hint_only > 0:
        truth = "HINT_ONLY"

    provider_status = dict(hm.get("radar_provider_status") or {})
    sources = list((hints or {}).get("sources") or [])
    for provider in _RADAR_STUB_PROVIDERS:
        if provider not in provider_status:
            if provider in sources:
                provider_status[provider] = "NOT_CONFIGURED"
            else:
                provider_status[provider] = "NOT_REQUESTED"

    return {
        "mirror_source_yield_by_provider": mirror_yield,
        "api_hint_to_onchain_verified_rate": verify_rate,
        "stale_hint_rate": stale_rate,
        "second_pool_source": second_pool_source,
        "hint_freshness_s": freshness_s,
        "truth_status": truth,
        "hint_status_counts": status_counts,
        "radar_provider_status": provider_status,
    }


def _matrix_has_unsupported_reason(
    matrix: Dict[str, Any],
    dex_id: str,
) -> bool:
    for token_row in (matrix or {}).values():
        dex_row = (token_row or {}).get(dex_id) or {}
        for cell in dex_row.values():
            if str((cell or {}).get("reason") or "").startswith("UNSUPPORTED"):
                return True
    return False


def build_candidate_coverage_audit(
    expansion: Dict[str, Any],
    registry: Dict[str, Any],
    *,
    min_coverage_rate: float = 0.98,
) -> Dict[str, Any]:
    """Audit candidate_dex_attempt_matrix vs full registry (configured + unsupported)."""
    summary = expansion.get("summary") or {}
    telemetry = expansion.get("candidate_scan_telemetry") or {}
    matrix = expansion.get("candidate_dex_attempt_matrix") or telemetry.get(
        "candidate_dex_attempt_matrix"
    ) or {}
    all_candidates = sorted(candidate_entries(registry).keys())
    configured = configured_candidate_dex_ids(registry)
    unsupported = unsupported_candidate_dex_ids(registry)
    attempted = sorted((telemetry.get("candidate_scan_attempted_by_dex") or {}).keys())
    missing_configured = sorted(set(configured) - set(attempted))
    missing_all = sorted(set(all_candidates) - set(attempted))
    missing_unsupported_matrix: List[str] = []
    for dex_id in unsupported:
        if dex_id not in attempted:
            missing_unsupported_matrix.append(dex_id)
        elif not _matrix_has_unsupported_reason(matrix, dex_id):
            missing_unsupported_matrix.append(dex_id)

    blockers: List[str] = []
    if all_candidates and not matrix:
        blockers.append("CANDIDATE_DEX_COVERAGE_INCOMPLETE")
    if missing_configured or missing_all:
        blockers.append("CANDIDATE_DEX_COVERAGE_INCOMPLETE")
    if missing_unsupported_matrix:
        blockers.append("CANDIDATE_DEX_COVERAGE_INCOMPLETE")

    expected = int(telemetry.get("candidate_scan_expected_attempts") or 0)
    actual = int(telemetry.get("candidate_scan_actual_attempts") or 0)
    rate = round(actual / expected, 4) if expected > 0 else (1.0 if not all_candidates else 0.0)
    if expected > 0 and rate < min_coverage_rate:
        blockers.append("CANDIDATE_DEX_COVERAGE_INCOMPLETE")

    tokens_in = int(summary.get("tokens_in") or summary.get("m8_tokens_in") or 0)
    matrix_tokens = len(matrix)
    if tokens_in > 1 and matrix_tokens < int(tokens_in * min_coverage_rate):
        blockers.append("CANDIDATE_DEX_COVERAGE_INCOMPLETE")

    by_anchor = dict(telemetry.get("candidate_scan_attempted_by_anchor") or {})
    expected_by_anchor = {
        anchor: int(count)
        for anchor, count in by_anchor.items()
    }

    return {
        "schema_version": "m8_2_candidate_coverage.2",
        "candidate_dexes_configured": configured,
        "unsupported_candidate_dexes": unsupported,
        "candidate_scan_attempted_by_dex": dict(
            telemetry.get("candidate_scan_attempted_by_dex") or {}
        ),
        "candidate_scan_attempted_by_anchor": by_anchor,
        "candidate_scan_expected_by_anchor": expected_by_anchor,
        "candidate_scan_actual_by_anchor": dict(by_anchor),
        "missing_candidate_dexes": missing_configured,
        "missing_all_candidate_dexes": missing_all,
        "missing_unsupported_in_matrix": missing_unsupported_matrix,
        "candidate_scan_expected_attempts": expected,
        "candidate_scan_actual_attempts": actual,
        "candidate_scan_coverage_rate": rate,
        "min_coverage_rate": min_coverage_rate,
        "matrix_token_count": matrix_tokens,
        "tokens_in": tokens_in,
        "blockers": sorted(set(blockers)),
        "goal_status": "REACHED" if not blockers else "BLOCKED",
    }
