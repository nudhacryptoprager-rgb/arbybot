"""Productive lane inventory admission — effective inventory + capacity contract."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

__all__ = ["ProductiveInventoryAdmissionResult", "admit_productive_inventory"]


@dataclass
class ProductiveInventoryAdmissionResult:
    inventory_path: str
    runner_universe_contract: Optional[Dict[str, Any]]
    truth_prices: Optional[Dict[str, float]]
    exit_code: Optional[int] = None


def admit_productive_inventory(
    *,
    args: Any,
    log: Any,
    inventory_path: str,
    cap_path_str: Optional[str],
    cap_doc: Optional[Dict[str, Any]],
    capacity_scope: Dict[str, Any],
    cycle_lengths: tuple[int, ...],
    active_profile: str,
    run_timestamp: str,
    started_at: float,
    process_id: int,
    duration_minutes: float,
) -> ProductiveInventoryAdmissionResult:
    from m9.graph_arb.effective_inventory import (
        ensure_effective_inventory,
        load_frozen_token_prices,
        resolve_effective_inventory_path,
    )
    from m9.graph_arb.route_quarantine import merge_paused_pools_from_lane_rca
    from m9.graph_arb.runner_terminal import (
        EXIT_EFFECTIVE_INVENTORY_PREP_FAILED,
        validate_capacity_universe_or_exit,
        write_effective_inventory_prep_failed_artifact,
    )
    from m9.graph_arb.universe_contract import resolve_session_id

    truth_prices: Optional[Dict[str, float]] = None
    runner_contract: Optional[Dict[str, Any]] = None

    try:
        _rq_merge = merge_paused_pools_from_lane_rca()
        if _rq_merge.get("added"):
            log.info(
                "Hard quarantine: added %d paused Balancer pools from lane RCA",
                _rq_merge["added"],
            )
    except Exception as _rq_exc:
        log.debug("Paused-pool quarantine merge skipped: %s", _rq_exc)

    runner_sid = resolve_session_id(getattr(args, "session_id", None))
    effective_out = (
        str(getattr(args, "effective_inventory_path", "") or "").strip()
        or resolve_effective_inventory_path(runner_sid)
    )
    try:
        inventory_path = ensure_effective_inventory(
            inventory_path,
            args.config,
            session_id=runner_sid,
            effective_path=effective_out,
        )
        truth_prices = load_frozen_token_prices(inventory_path)
        log.info(
            "Effective execution inventory (read-only): path=%s prices_frozen=%s",
            inventory_path,
            truth_prices is not None,
        )
    except Exception as _prep_exc:
        write_effective_inventory_prep_failed_artifact(
            args=args,
            log=log,
            run_timestamp=run_timestamp,
            started_at=started_at,
            inventory_path=inventory_path,
            failure_reason=str(_prep_exc),
            process_id=process_id,
            duration_minutes=duration_minutes,
        )
        return ProductiveInventoryAdmissionResult(
            inventory_path=inventory_path,
            runner_universe_contract=None,
            truth_prices=None,
            exit_code=EXIT_EFFECTIVE_INVENTORY_PREP_FAILED,
        )

    if cap_path_str and cap_doc is not None:
        runner_contract, universe_exit = validate_capacity_universe_or_exit(
            args=args,
            log=log,
            cap_path_str=cap_path_str,
            cap_doc=cap_doc,
            capacity_scope=capacity_scope,
            inventory_path=inventory_path,
            cycle_lengths=cycle_lengths,
            active_profile=active_profile,
            run_timestamp=run_timestamp,
            started_at=started_at,
            process_id=process_id,
            duration_minutes=duration_minutes,
        )
        if universe_exit is not None:
            return ProductiveInventoryAdmissionResult(
                inventory_path=inventory_path,
                runner_universe_contract=runner_contract,
                truth_prices=truth_prices,
                exit_code=universe_exit,
            )

    return ProductiveInventoryAdmissionResult(
        inventory_path=inventory_path,
        runner_universe_contract=runner_contract,
        truth_prices=truth_prices,
        exit_code=None,
    )
