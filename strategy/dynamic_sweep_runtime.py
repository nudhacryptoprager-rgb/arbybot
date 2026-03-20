# PATH: strategy/dynamic_sweep_runtime.py
"""
Dynamic size sweep runtime — finds optimal notional per route via multi-size requoting.

Extracted from run_scan_real.py (R28.28) to separate sweep orchestration from
scan spine. Contains the requote factory builders, sweep loop, outlier filter,
and stats/evidence assembly.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("dynamic_sweep_runtime")

# Threshold for suspect roundtrip outliers (aligned with SUSPECT_SPREAD_BPS_HARD)
SUSPECT_ROUNDTRIP_OUTLIER_BPS = 500


def make_requote_factory(
    chain_key: str,
    rpc_url: str,
    current_block: int,
    read_quoter_v2_fn: Callable,
    get_dex_config_fn: Callable,
    get_token_address_fn: Callable,
    reverse: bool = False,
) -> Callable:
    """Create a requote callback factory for sweep legs.

    Args:
        reverse: If False, creates leg1 factory (token_in → token_out, same direction).
                 If True, creates leg2 factory (token_out → token_in, REVERSE).
    """
    def _factory(quote: Dict) -> Optional[Callable]:
        _dex_id = quote.get("dex_id", "")
        _dex_cfg = get_dex_config_fn(chain_key, _dex_id)
        _quoter = _dex_cfg.get_quoter_address() if _dex_cfg else None
        _fee = quote.get("fee", 3000)

        if reverse:
            _in_sym = quote.get("token_out", "")
            _out_sym = quote.get("token_in", "")
        else:
            _in_sym = quote.get("token_in", "")
            _out_sym = quote.get("token_out", "")

        _in_addr = get_token_address_fn(chain_key, _in_sym)
        _out_addr = get_token_address_fn(chain_key, _out_sym)
        if not _quoter or not _in_addr or not _out_addr:
            return None

        def _requote(amount_in_wei: int) -> Optional[Dict]:
            r = read_quoter_v2_fn(
                quoter_address=_quoter,
                token_in=_in_addr,
                token_out=_out_addr,
                amount_in=amount_in_wei,
                fee=_fee,
                rpc_url=rpc_url,
                block_num=current_block,
            )
            if r:
                result = {
                    "amount_out_wei": r["amount_out"],
                    "gas_estimate": r.get("gas_estimate", 150000),
                    "ticks_crossed": r.get("ticks_crossed", 0),
                }
                if "sqrt_price_after" in r:
                    result["sqrt_price_after"] = r["sqrt_price_after"]
                return result
            return None
        return _requote
    return _factory


def run_sweep(
    eligible_opps: List[Dict],
    quotes_by_key: Dict[str, Dict],
    config: Dict[str, Any],
    chain_key: str,
    rpc_url: str,
    current_block: int,
    live_gas_price_wei: int,
    l1_cost_wei: int,
    l1_cost_source: str,
    eth_usd: float,
    token_decimals: Dict[str, int],
) -> Dict[str, Any]:
    """Run dynamic size sweep on eligible opportunities and return stats dict.

    Returns dict ready to be placed at stats["roundtrip"]["dynamic_sweep"],
    plus top-level executable evidence fields.
    """
    from engine.roundtrip import sweep_roundtrip_sizes, CANONICAL_SWEEP_SIZES_USD
    from strategy.quotes import read_quoter_v2
    from config import get_token_address
    from dex.registry import get_dex_config

    dynamic_probe_cfg = config.get("dynamic_probe", {})
    sweep_sizes = dynamic_probe_cfg.get("sizes_usd", None) or list(CANONICAL_SWEEP_SIZES_USD)
    max_routes = dynamic_probe_cfg.get("top_routes", 15)

    make_leg1 = make_requote_factory(
        chain_key, rpc_url, current_block,
        read_quoter_v2, get_dex_config, get_token_address, reverse=False,
    )
    make_leg2 = make_requote_factory(
        chain_key, rpc_url, current_block,
        read_quoter_v2, get_dex_config, get_token_address, reverse=True,
    )

    sweep_results = []
    for opp in eligible_opps[:max_routes]:
        buy_key = f"{opp.get('buy_dex')}:{opp.get('diagnostics', {}).get('buy_pool')}:{opp.get('buy_fee')}"
        sell_key = f"{opp.get('sell_dex')}:{opp.get('diagnostics', {}).get('sell_pool')}:{opp.get('sell_fee')}"
        bq = quotes_by_key.get(buy_key)
        sq = quotes_by_key.get(sell_key)
        if not bq or not sq:
            continue

        leg1_rq = make_leg1(sq)    # leg1 on sell_dex
        leg2_rq = make_leg2(bq)    # leg2 on buy_dex
        if not leg1_rq or not leg2_rq:
            continue

        _ti = sq.get("token_in", "WETH")
        _ti_price = (config.get("tokens_usd_price") or {}).get(_ti)
        if not _ti_price:
            _ti_price = eth_usd if _ti in ("WETH", "ETH") else None
        if not _ti_price:
            continue

        _ti_dec = token_decimals.get(_ti, 18)

        sr = sweep_roundtrip_sizes(
            buy_quote_base=sq,
            sell_quote_base=bq,
            requote_leg1=leg1_rq,
            requote_leg2=leg2_rq,
            sizes_usd=sweep_sizes,
            token_in_usd_price=_ti_price,
            token_in_decimals=_ti_dec,
            gas_price_wei=live_gas_price_wei,
            l1_cost_wei=l1_cost_wei,
            l1_cost_source=l1_cost_source,
            eth_usd_price=eth_usd,
        )
        sweep_results.append(sr)
        logger.info(
            "Sweep %s: best=$%s, pnl=%.2f bps, frontier=%s",
            sr.pair, sr.best_size_usd, sr.best_net_pnl_bps or 0.0, sr.frontier_reason,
        )

    # Outlier filter
    sweep_stats, evidence = _build_sweep_stats(sweep_results)
    return {
        "dynamic_sweep": sweep_stats,
        "executable_evidence": evidence,
    }


def _build_sweep_stats(
    sweep_results: List[Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build dynamic_sweep stats dict and executable evidence fields from sweep results.

    Returns (sweep_stats_dict, executable_evidence_dict).
    """
    suspect_outlier_count = 0
    clean_results = []
    for sr in sweep_results:
        if sr.best_net_pnl_bps is not None and abs(sr.best_net_pnl_bps) > SUSPECT_ROUNDTRIP_OUTLIER_BPS:
            suspect_outlier_count += 1
            logger.warning(
                "SUSPECT_ROUNDTRIP_OUTLIER: %s pnl=%.1f bps outside ±%d threshold",
                sr.pair, sr.best_net_pnl_bps, SUSPECT_ROUNDTRIP_OUTLIER_BPS,
            )
        else:
            clean_results.append(sr)

    if clean_results:
        best_sweep = max(
            clean_results,
            key=lambda s: s.best_net_pnl_bps if s.best_net_pnl_bps is not None else -9999,
        )
        sweep_stats = {
            "enabled": True,
            "routes_swept": len(sweep_results),
            "routes_clean": len(clean_results),
            "suspect_outlier_count": suspect_outlier_count,
            "best_pair": best_sweep.pair,
            "best_size_usd": best_sweep.best_size_usd,
            "best_net_pnl_bps": best_sweep.best_net_pnl_bps,
            "best_frontier_reason": best_sweep.frontier_reason,
            "gap_to_zero_bps": best_sweep.gap_to_zero_bps,
            "best_gas_bps": best_sweep.best_gas_bps,
            "best_fee_bps": best_sweep.best_fee_bps,
            "best_slippage_bps": best_sweep.best_slippage_bps,
            "best_total_cost_bps": best_sweep.best_total_cost_bps,
            "results": [s.to_dict() for s in sweep_results],
        }
    elif sweep_results:
        sweep_stats = {
            "enabled": True,
            "routes_swept": len(sweep_results),
            "routes_clean": 0,
            "suspect_outlier_count": suspect_outlier_count,
            "best_frontier_reason": "ALL_SUSPECT_OUTLIER",
            "results": [s.to_dict() for s in sweep_results],
        }
    else:
        sweep_stats = {"enabled": True, "routes_swept": 0}

    # Executable evidence promotion
    ds = sweep_stats
    if ds.get("best_net_pnl_bps") is not None and ds["best_net_pnl_bps"] > 0:
        evidence = {
            "best_executable_size_usd": ds["best_size_usd"],
            "best_executable_pnl_bps": ds["best_net_pnl_bps"],
            "executable_evidence": "SWEEP_PROFITABLE",
        }
    elif ds.get("gap_to_zero_bps") is not None:
        evidence = {
            "best_executable_size_usd": ds.get("best_size_usd"),
            "best_executable_pnl_bps": ds.get("best_net_pnl_bps"),
            "executable_evidence": "SWEEP_GAP_TO_ZERO",
        }
    else:
        evidence = {
            "best_executable_size_usd": None,
            "best_executable_pnl_bps": None,
            "executable_evidence": "NO_SWEEP_DATA",
        }

    return sweep_stats, evidence
