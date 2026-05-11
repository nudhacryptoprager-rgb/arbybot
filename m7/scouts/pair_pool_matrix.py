"""E1.76 — Pair-Pool Matrix.

Groups pools by canonical token pair (e.g. ``USDC/WETH``) so the cold
scanner and dashboard can reason about *correlated pool families*
instead of isolated pools.

A pair-family is the set of pools that share the same unordered pair of
underlying tokens.  The same pair can be present on multiple DEXes and
multiple fee-tiers (Uniswap-V3 0.05 %, 0.30 %, 1 %, Aerodrome stable /
volatile, etc.).

Pure functions only.  No network IO, no global state.  Designed to be
unit-tested in isolation; consumed by ``bridge_runtime`` and the
dashboard heatmap.

Output schema (``build_pair_pool_matrix``)::

    {
      "pairs": [
        {
          "pair": "USDC/WETH",            # canonical, alphabetical
          "tokens": ["USDC", "WETH"],
          "pool_count": 5,
          "dex_count": 2,
          "fee_tiers": [500, 3000, 10000],
          "tvl_total_usd": 12345678.0,
          "volume_24h_total_usd": 999.0,
          "best_pool": {                  # highest TVL pool in family
            "pool_address": "0x...",
            "project": "uniswap-v3",
            "fee_tier_bps": 5,
            "tvl_usd": 9876543.0,
          },
          "pools": [ <PoolTVLEntry-like dicts> ],
        },
        ...
      ],
      "summary": {
        "pair_count": 17,
        "pool_count": 42,
        "tvl_total_usd": 1.2e8,
      },
    }
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "canonical_pair",
    "split_symbol",
    "infer_fee_tier_bps",
    "build_pair_pool_matrix",
]


def split_symbol(symbol: str) -> Tuple[str, str]:
    """Split a DefiLlama symbol like ``WETH-USDC`` or ``USDC/WETH``.

    Returns ``(token_a, token_b)`` upper-cased; falls back to
    ``(symbol, "")`` when no separator is present.
    """
    if not symbol or not isinstance(symbol, str):
        return ("", "")
    s = symbol.strip().upper()
    for sep in ("-", "/", "_", " "):
        if sep in s:
            parts = [p.strip() for p in s.split(sep) if p.strip()]
            if len(parts) >= 2:
                return (parts[0], parts[1])
    return (s, "")


def canonical_pair(token_a: str, token_b: str) -> str:
    """Return ``A/B`` with tokens sorted alphabetically (stable family key)."""
    a = (token_a or "").strip().upper()
    b = (token_b or "").strip().upper()
    if not a and not b:
        return ""
    if not b:
        return a
    if not a:
        return b
    if a <= b:
        return f"{a}/{b}"
    return f"{b}/{a}"


def infer_fee_tier_bps(pool: Dict[str, Any]) -> Optional[int]:
    """Best-effort fee-tier inference from pool metadata.

    Looks at common keys: ``fee_tier_bps``, ``fee_tier``, ``fee``, and
    Uniswap-V3 conventional values (100 / 500 / 3000 / 10000 ppm).
    Returns basis-points (5, 30, 100, ...) or ``None``.
    """
    for k in ("fee_tier_bps", "feeTierBps"):
        v = pool.get(k)
        if isinstance(v, (int, float)) and v > 0:
            return int(v)
    for k in ("fee_tier", "feeTier", "fee_ppm"):
        v = pool.get(k)
        if isinstance(v, (int, float)) and v > 0:
            # Uniswap V3 convention: ppm (1e6 = 100%); 500 ppm = 0.05% = 5 bps
            return max(1, int(round(float(v) / 100.0)))
    fee = pool.get("fee")
    if isinstance(fee, (int, float)) and fee > 0:
        # heuristic: <1 -> fraction (0.0005), >=1 -> bps already
        return int(round(float(fee) * 10000)) if fee < 1 else int(fee)
    return None


def _pool_to_dict(pool: Any) -> Dict[str, Any]:
    if isinstance(pool, dict):
        return dict(pool)
    if hasattr(pool, "to_dict"):
        try:
            return dict(pool.to_dict())
        except Exception:
            pass
    if hasattr(pool, "__dict__"):
        return dict(pool.__dict__)
    return {}


def build_pair_pool_matrix(
    pools: Iterable[Any],
    *,
    min_tvl_usd: float = 0.0,
    factory_truth: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Group pools into pair-families.

    Args:
      pools: iterable of dicts or ``PoolTVLEntry``-like objects with at
             least ``symbol``, ``pool_address``, ``project``, ``tvl_usd``
             and optional ``volume_24h_usd``.
      min_tvl_usd: drop pools below this TVL before grouping.
      factory_truth: optional dict mapping canonical pair key → PoolFamilyTruth
             (or its ``to_dict()`` output).  When provided, populates
             ``factory_pool_count`` and ``factory_dex_count`` for each pair
             from on-chain factory enumeration data (E1.83).

    Returns: schema described in module docstring.  Always returns a
    dict; never raises.
    """
    families: Dict[str, Dict[str, Any]] = {}
    pool_count = 0
    tvl_total = 0.0
    for raw in pools or []:
        p = _pool_to_dict(raw)
        if not p:
            continue
        try:
            tvl_usd = float(p.get("tvl_usd") or 0.0)
        except (TypeError, ValueError):
            tvl_usd = 0.0
        if tvl_usd < min_tvl_usd:
            continue
        symbol = str(p.get("symbol") or "")
        ta, tb = split_symbol(symbol)
        key = canonical_pair(ta, tb)
        if not key:
            continue
        try:
            vol_usd = float(p.get("volume_24h_usd") or 0.0)
        except (TypeError, ValueError):
            vol_usd = 0.0
        fee_bps = infer_fee_tier_bps(p)
        project = str(p.get("project") or "unknown").lower()
        pool_addr = str(p.get("pool_address") or p.get("pool") or "").lower()

        fam = families.setdefault(
            key,
            {
                "pair": key,
                "tokens": sorted([ta.upper(), tb.upper()]),
                "pool_count": 0,
                "gecko_pool_count": 0,
                "dex_set": set(),
                "fee_tiers_set": set(),
                "tvl_total_usd": 0.0,
                "volume_24h_total_usd": 0.0,
                "best_pool": None,
                "_best_tvl": -1.0,
                "pools": [],
            },
        )
        fam["pool_count"] += 1
        if p.get("source") == "gecko":
            fam["gecko_pool_count"] += 1
        fam["dex_set"].add(project)
        if fee_bps is not None:
            fam["fee_tiers_set"].add(int(fee_bps))
        fam["tvl_total_usd"] += tvl_usd
        fam["volume_24h_total_usd"] += vol_usd
        if tvl_usd > fam["_best_tvl"]:
            fam["_best_tvl"] = tvl_usd
            fam["best_pool"] = {
                "pool_address": pool_addr,
                "project": project,
                "fee_tier_bps": fee_bps,
                "tvl_usd": tvl_usd,
            }
        fam["pools"].append(
            {
                "pool_address": pool_addr,
                "project": project,
                "fee_tier_bps": fee_bps,
                "tvl_usd": tvl_usd,
                "volume_24h_usd": vol_usd,
                "symbol": symbol,
            }
        )
        pool_count += 1
        tvl_total += tvl_usd

    pairs_out: List[Dict[str, Any]] = []
    for fam in families.values():
        pair_key = fam["pair"]
        # E1.83: resolve factory_pool_count from factory_truth when available.
        fac_truth = (factory_truth or {}).get(pair_key) or {}
        if isinstance(fac_truth, dict):
            fac_pool_count = int(fac_truth.get("pool_count") or 0)
            fac_dex_count = int(fac_truth.get("dex_count") or 0)
        elif hasattr(fac_truth, "pool_count"):
            # PoolFamilyTruth dataclass
            fac_pool_count = int(fac_truth.pool_count)
            fac_dex_count = int(fac_truth.dex_count)
        else:
            fac_pool_count = 0
            fac_dex_count = 0

        pairs_out.append(
            {
                "pair": pair_key,
                "tokens": fam["tokens"],
                # pool_count: backward-compat total (scout + gecko combined).
                "pool_count": fam["pool_count"],
                # E1.83: source-split pool counts.
                "scout_pool_count": fam["pool_count"] - fam["gecko_pool_count"],
                "gecko_pool_count": fam["gecko_pool_count"],
                # E1.83: on-chain factory enumeration counts (0 when not yet fetched).
                "factory_pool_count": fac_pool_count,
                "factory_dex_count": fac_dex_count,
                # reference_only: prefer factory_dex_count when available,
                # fall back to scout-based dex_set size.
                "reference_only": (
                    (fac_dex_count if fac_dex_count > 0 else len(fam["dex_set"])) <= 1
                ),
                "dex_count": len(fam["dex_set"]),
                "fee_tiers": sorted(fam["fee_tiers_set"]),
                "tvl_total_usd": round(fam["tvl_total_usd"], 6),
                "volume_24h_total_usd": round(fam["volume_24h_total_usd"], 6),
                "best_pool": fam["best_pool"],
                "pools": fam["pools"],
            }
        )
    # Stable, useful default ordering: largest TVL family first.
    pairs_out.sort(key=lambda x: x["tvl_total_usd"], reverse=True)

    return {
        "pairs": pairs_out,
        "summary": {
            "pair_count": len(pairs_out),
            "pool_count": pool_count,
            "tvl_total_usd": round(tvl_total, 6),
        },
    }
