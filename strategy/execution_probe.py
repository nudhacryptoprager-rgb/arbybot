# PATH: strategy/execution_probe.py
"""
Live execution probe — wires simulate_rpc + execute_live into scanner.

Extracted from run_scan_real.py (R28.28) to separate execution path from
scan orchestration.

This block is DORMANT unless config explicitly sets execution_enabled=true
and kill_switch_active=false. All current configs keep this off.
Flow: best candidate -> simulate_rpc -> execute_live -> receipt -> realized_pnl
"""

import asyncio
import logging
import time as _time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("execution_probe")


def probe_live_execution(
    config: Dict[str, Any],
    provider_http: Optional[str],
    opps_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Probe live execution for the best candidate opportunity.

    Returns a dict suitable for stats["live_execution"].
    Only activates when all safety gates pass:
    - execution_enabled=true, kill_switch_active=false, simulate_only=false
    - provider_http available, opps_list non-empty
    """
    # Gate checks
    if not (
        config.get("execution_enabled", False) is True
        and config.get("kill_switch_active", True) is False
        and config.get("simulate_only", True) is False
        and provider_http is not None
        and opps_list
        and len(opps_list) > 0
    ):
        return {"enabled": False}

    try:
        from execution.simulator import PreTradeSimulator, SimulatorConfig
        from execution.dex_dex_executor import DexDexExecutor, ExecutorConfig

        # Pick best candidate (first opportunity by PnL ranking)
        best_opp = opps_list[0]
        exec_opp = {
            "spread_id": best_opp.get("spread_id", best_opp.get("signal_id", "unknown")),
            "router_address": best_opp.get("buy_pool", ""),
            "swap_calldata": best_opp.get("swap_calldata", ""),
            "expected_out": str(best_opp.get("gross_pnl_usdc_est", "0")),
            "gas_estimate": int(best_opp.get("gas_estimate", 300_000)),
            "quote_timestamp_ms": int(_time.time() * 1000),
            "simulation_passed": False,
            "expected_pnl_usd": str(best_opp.get("net_pnl_usdc_est", "0")),
            "paper_size_usd": str(config.get("paper_size_usd", 150)),
        }

        # Step 1: Pre-trade simulation (async)
        sim_config = SimulatorConfig(
            max_slippage_bps=config.get("max_slippage_bps", 100),
            max_gas_estimate=config.get("max_gas_estimate", 500_000),
            quote_freshness_ms=config.get("quote_freshness_ms", 3000),
        )
        simulator = PreTradeSimulator(sim_config)
        sim_result = asyncio.run(simulator.simulate_rpc(exec_opp, provider_http))

        if not sim_result.passed:
            logger.info(
                "Live execution: simulation FAILED (%s)",
                ", ".join(sim_result.blockers),
            )
            return {
                "enabled": True,
                "simulation_passed": False,
                "blockers": sim_result.blockers,
                "revert_reason": sim_result.revert_reason,
                "execution_attempted": False,
            }

        exec_opp["simulation_passed"] = True
        exec_opp["simulated_out"] = str(sim_result.simulated_out)

        # Step 2: Execute — requires signer
        signer_address = config.get("signer_address")
        sign_fn_path = config.get("sign_function")
        if signer_address and sign_fn_path:
            exec_config = ExecutorConfig(
                smoke_mode=False,
                execution_enabled=True,
                require_simulation=True,
                max_gas_price_gwei=config.get("max_gas_price_gwei", 50.0),
                max_slippage_bps=config.get("max_slippage_bps", 100),
            )
            # Executor instantiated but sign_and_send not yet wired
            _executor = DexDexExecutor(config=exec_config, kill_switch_active=False)
            logger.info(
                "Live execution: simulation PASSED (slippage=%d bps), signer ready but sign_fn not wired",
                sim_result.slippage_bps,
            )
            return {
                "enabled": True,
                "simulation_passed": True,
                "simulated_out": str(sim_result.simulated_out),
                "slippage_bps": sim_result.slippage_bps,
                "execution_attempted": False,
                "reason": "SIGNER_READY_BUT_NO_SIGN_FN_YET",
            }
        else:
            logger.info(
                "Live execution: simulation PASSED (slippage=%d bps) but no signer configured",
                sim_result.slippage_bps,
            )
            return {
                "enabled": True,
                "simulation_passed": True,
                "simulated_out": str(sim_result.simulated_out),
                "slippage_bps": sim_result.slippage_bps,
                "execution_attempted": False,
                "reason": "NO_SIGNER_CONFIGURED",
            }
    except Exception as exec_err:
        logger.warning("Live execution probe failed: %s", exec_err)
        return {
            "enabled": True,
            "error": str(exec_err),
            "execution_attempted": False,
        }
