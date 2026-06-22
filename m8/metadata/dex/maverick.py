"""Maverick route metadata worker."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from m8.metadata.contracts import MetadataTask
from m8.metadata.dex.base import DexMetadataWorker, _require_fields
from m8.metadata.registry import is_valid_eth_address


@dataclass
class MaverickTokenPairResolution:
    token_a: Optional[str]
    token_b: Optional[str]
    source: str
    ambiguous: bool = False
    can_infer: bool = False
    has_probe_by_token_in: bool = False


def _norm_addr(addr: object) -> Optional[str]:
    if not is_valid_eth_address(addr):
        return None
    return str(addr).lower()


def _explicit_token_a(route: Dict[str, Any]) -> Optional[str]:
    for key in ("token_a_address", "token_a", "maverick_token_a"):
        val = _norm_addr(route.get(key))
        if val:
            return val
    return None


def _explicit_token_b(route: Dict[str, Any]) -> Optional[str]:
    for key in ("token_b_address", "token_b", "maverick_token_b"):
        val = _norm_addr(route.get(key))
        if val:
            return val
    return None


def _probe_token_a_in(probe_row: object) -> Optional[bool]:
    if isinstance(probe_row, bool):
        return probe_row
    if not isinstance(probe_row, dict):
        return None
    raw = probe_row.get("maverick_token_a_in_probe")
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    s = str(raw).strip().lower()
    if s in ("1", "true", "yes"):
        return True
    if s in ("0", "false", "no"):
        return False
    return None


def infer_maverick_token_pair_from_probe(route: Dict[str, Any]) -> MaverickTokenPairResolution:
    """Infer tokenA/tokenB from maverick_probe_by_token_in rows."""
    probe_by_tin = route.get("maverick_probe_by_token_in") or {}
    t0 = _norm_addr(route.get("token0_addr"))
    t1 = _norm_addr(route.get("token1_addr"))
    legs = {a for a in (t0, t1) if a}
    has_probe = isinstance(probe_by_tin, dict) and bool(probe_by_tin)

    if not has_probe or len(legs) < 2:
        return MaverickTokenPairResolution(
            None, None, "probe_inference", has_probe_by_token_in=has_probe
        )

    token_a_candidates: Set[str] = set()
    for token_in, probe_row in probe_by_tin.items():
        tin = _norm_addr(token_in)
        if not tin or tin not in legs:
            continue
        tai = _probe_token_a_in(probe_row)
        if tai is None:
            continue
        if tai:
            token_a_candidates.add(tin)
        else:
            others = legs - {tin}
            if len(others) == 1:
                token_a_candidates.add(next(iter(others)))

    if len(token_a_candidates) == 1:
        token_a = next(iter(token_a_candidates))
        token_b = next(iter(legs - {token_a}), None)
        return MaverickTokenPairResolution(
            token_a,
            token_b,
            "probe_inference",
            can_infer=True,
            has_probe_by_token_in=True,
        )
    if len(token_a_candidates) > 1:
        return MaverickTokenPairResolution(
            None, None, "probe_inference", ambiguous=True, has_probe_by_token_in=True
        )
    return MaverickTokenPairResolution(
        None, None, "probe_inference", has_probe_by_token_in=True
    )


def fetch_maverick_token_pair_onchain(w3: Any, pool_address: str) -> Tuple[Optional[str], Optional[str]]:
    """On-chain tokenA()/tokenB() for Maverick pool."""
    if w3 is None or not is_valid_eth_address(pool_address):
        return None, None
    try:
        from dex.adapters.maverick_v2 import _SELECTOR_TOKEN_A, _SELECTOR_TOKEN_B

        token_a = _eth_call_address(w3, pool_address, _SELECTOR_TOKEN_A)
        token_b = _eth_call_address(w3, pool_address, _SELECTOR_TOKEN_B)
        return token_a, token_b
    except Exception:
        return None, None


def _eth_call_address(w3: Any, pool_address: str, selector: bytes) -> Optional[str]:
    try:
        checksum = w3.to_checksum_address(pool_address)
        result = w3.eth.call({"to": checksum, "data": "0x" + selector.hex()}, "latest")
        if isinstance(result, bytes):
            raw = result.hex()
        else:
            raw = str(result)[2:] if str(result).startswith("0x") else str(result)
        if len(raw) < 64:
            return None
        addr = "0x" + raw[-40:]
        return addr.lower() if is_valid_eth_address(addr) else None
    except Exception:
        return None


def resolve_maverick_token_pair(
    route: Dict[str, Any], *, w3: Any = None
) -> MaverickTokenPairResolution:
    """Resolve Maverick tokenA/tokenB with explicit → probe → on-chain precedence."""
    t0 = _norm_addr(route.get("token0_addr"))
    t1 = _norm_addr(route.get("token1_addr"))
    legs = {a for a in (t0, t1) if a}

    token_a = _explicit_token_a(route)
    token_b = _explicit_token_b(route)
    if token_a and token_b:
        if _pair_matches_legs(token_a, token_b, legs):
            return MaverickTokenPairResolution(
                token_a,
                token_b,
                "explicit",
                can_infer=True,
                has_probe_by_token_in=bool(route.get("maverick_probe_by_token_in")),
            )
        return MaverickTokenPairResolution(
            None,
            None,
            "explicit",
            ambiguous=True,
            has_probe_by_token_in=bool(route.get("maverick_probe_by_token_in")),
        )

    if token_a and not token_b and len(legs) == 2:
        token_b = next(iter(legs - {token_a}), None)
        if token_b and _pair_matches_legs(token_a, token_b, legs):
            return MaverickTokenPairResolution(
                token_a,
                token_b,
                "explicit_partial",
                can_infer=True,
                has_probe_by_token_in=bool(route.get("maverick_probe_by_token_in")),
            )

    probe_res = infer_maverick_token_pair_from_probe(route)
    if probe_res.can_infer and probe_res.token_a and probe_res.token_b:
        if _pair_matches_legs(probe_res.token_a, probe_res.token_b, legs):
            return probe_res
        return MaverickTokenPairResolution(
            None,
            None,
            probe_res.source,
            ambiguous=True,
            has_probe_by_token_in=probe_res.has_probe_by_token_in,
        )
    if probe_res.ambiguous:
        return probe_res

    pool = route.get("pool_address")
    if w3 is not None and is_valid_eth_address(pool):
        on_a, on_b = fetch_maverick_token_pair_onchain(w3, str(pool))
        if on_a and on_b and _pair_matches_legs(on_a, on_b, legs):
            return MaverickTokenPairResolution(
                on_a,
                on_b,
                "onchain",
                can_infer=True,
                has_probe_by_token_in=probe_res.has_probe_by_token_in,
            )
        if on_a and on_b:
            return MaverickTokenPairResolution(
                None,
                None,
                "onchain",
                ambiguous=True,
                has_probe_by_token_in=probe_res.has_probe_by_token_in,
            )

    return MaverickTokenPairResolution(
        None,
        None,
        "unresolved",
        ambiguous=probe_res.ambiguous,
        has_probe_by_token_in=probe_res.has_probe_by_token_in,
    )


def _pair_matches_legs(token_a: str, token_b: str, legs: Set[str]) -> bool:
    if not legs or len(legs) < 2:
        return False
    pair = {token_a.lower(), token_b.lower()}
    return pair == legs and token_a.lower() != token_b.lower()


class MaverickDexWorker(DexMetadataWorker):
    worker_id = "maverick"
    dex_patterns = ("maverick_v2", "maverick")

    def process(self, task: MetadataTask, *, w3: Any = None):
        route = task.route or {}
        missing = _require_fields(route, ("pool_address", "token0_addr", "token1_addr"))
        resolution = resolve_maverick_token_pair(route, w3=w3)

        if not resolution.token_a:
            missing.append("token_a_address")
        if not resolution.token_b:
            missing.append("token_b_address")
        if resolution.ambiguous:
            missing.append("token_a_b_ambiguous")

        probe_by_tin = route.get("maverick_probe_by_token_in") or {}
        has_direction = bool(probe_by_tin) or route.get("maverick_min_quoteable_amount_raw") is not None
        meta = {
            "pool_address": route.get("pool_address"),
            "token_a": resolution.token_a,
            "token_b": resolution.token_b,
            "token_pair_source": resolution.source,
            "pool_state_metadata_source": resolution.source,
            "bin_kind": route.get("maverick_bin_kind") or route.get("bin_kind"),
            "static_params": route.get("maverick_static_params") or route.get("static_params"),
            "direction_capacity": {
                "probe_by_token_in": probe_by_tin,
                "min_quoteable_raw": route.get("maverick_min_quoteable_amount_raw"),
                "max_quoteable_raw": route.get("maverick_max_quoteable_amount_raw"),
                "pool_lane_probe_amount": route.get("maverick_pool_lane_probe_amount"),
            },
            "direction_support": "directional" if has_direction else "unknown",
            "has_probe_by_token_in": resolution.has_probe_by_token_in,
            "can_infer_token_a_b": resolution.can_infer and not resolution.ambiguous,
        }
        ready = not missing and resolution.can_infer and not resolution.ambiguous
        return self._result(
            task,
            ready=ready,
            metadata=meta,
            error_code=None if ready else "DEX_ROUTE_METADATA_PARTIAL",
            missing_fields=missing,
            quoteability_hint="maverick_direction" if ready and has_direction else None,
        )
