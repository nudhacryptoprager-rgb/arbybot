"""E1.80 Iter 7 — Aave V3 (Base) flash loan adapter skeleton.

This is a SKELETON ONLY — no on-chain deployment, no execution path.
Provides the math + calldata helpers needed to evaluate whether a flash-
loaned arbitrage clears Aave V3's 9 bps premium plus gas, and to build
the calldata that an on-chain receiver contract would consume.

Aave V3 Base Pool address (mainnet):
    0xA238Dd80C259a72e81d7e4664a9801593F98d1c5
Flash loan premium (flashLoanPremiumTotal):
    9 bps  ==  0.0009  ==  9 / 10000

References:
  https://docs.aave.com/developers/core-contracts/pool#flashloansimple
  https://github.com/aave/aave-v3-core/blob/master/contracts/protocol/pool/Pool.sol
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Aave V3 Pool on Base mainnet (immutable via PoolAddressesProvider).
AAVE_V3_BASE_POOL = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"

# Flash loan total premium charged by Aave V3 (bps).  This is the
# `flashLoanPremiumTotal` storage value; the protocol fee share is
# subtracted on the receiver side, but the borrower always pays the
# full 9 bps on `flashLoanSimple`.
AAVE_V3_FLASH_PREMIUM_BPS = 9.0


@dataclass(frozen=True)
class FlashLoanEconomics:
    """Result of estimating flash-loan-adjusted profitability."""

    spread_bps: float
    flash_premium_bps: float
    gas_cost_usd: float
    size_usd: float
    flash_premium_usd: float
    gross_profit_usd: float
    net_profit_usd: float
    profitable: bool


def estimate_flash_loan_profit(
    *,
    spread_bps: float,
    size_usd: float,
    gas_cost_usd: float,
    flash_premium_bps: float = AAVE_V3_FLASH_PREMIUM_BPS,
) -> FlashLoanEconomics:
    """Estimate net profit when funding `size_usd` via Aave V3 flash loan.

    Inputs:
      spread_bps:        gross arbitrage edge in bps (e.g. 25.0 = 0.25%)
      size_usd:          notional borrowed in USD
      gas_cost_usd:      total gas cost (entry+repay+receiver execution)
      flash_premium_bps: protocol premium (default 9 bps for Aave V3 Base)

    Result is structured so the caller can log every component for
    reviewer-friendly diagnosis.
    """
    if size_usd <= 0:
        return FlashLoanEconomics(
            spread_bps=spread_bps,
            flash_premium_bps=flash_premium_bps,
            gas_cost_usd=gas_cost_usd,
            size_usd=size_usd,
            flash_premium_usd=0.0,
            gross_profit_usd=0.0,
            net_profit_usd=-gas_cost_usd,
            profitable=False,
        )
    flash_premium_usd = size_usd * (flash_premium_bps / 10_000.0)
    gross_profit_usd = size_usd * (spread_bps / 10_000.0)
    net_profit_usd = gross_profit_usd - flash_premium_usd - gas_cost_usd
    return FlashLoanEconomics(
        spread_bps=spread_bps,
        flash_premium_bps=flash_premium_bps,
        gas_cost_usd=gas_cost_usd,
        size_usd=size_usd,
        flash_premium_usd=flash_premium_usd,
        gross_profit_usd=gross_profit_usd,
        net_profit_usd=net_profit_usd,
        profitable=net_profit_usd > 0,
    )


def min_profitable_spread_bps(
    *,
    size_usd: float,
    gas_cost_usd: float,
    flash_premium_bps: float = AAVE_V3_FLASH_PREMIUM_BPS,
    safety_margin_bps: float = 1.0,
) -> Optional[float]:
    """Return the minimum spread (bps) at which a flash-loaned trade clears.

    Returns ``None`` for non-positive ``size_usd``. Always adds
    ``safety_margin_bps`` (default 1 bps) on top of the analytical break-even
    so callers can use the value as an admission threshold.
    """
    if size_usd <= 0:
        return None
    breakeven = flash_premium_bps + (gas_cost_usd / size_usd) * 10_000.0
    return breakeven + max(0.0, safety_margin_bps)


# --------------------------------------------------------------------- #
# Calldata helpers (skeleton).  Real deployment requires a deployed
# IFlashLoanReceiver contract; we expose only the encoder shape so that
# unit tests can lock the call signature and a future executor can plug
# in web3 / eth_abi without further refactor.
# --------------------------------------------------------------------- #

# `flashLoanSimple(address receiver, address asset, uint256 amount,
#                  bytes params, uint16 referralCode)`
FLASH_LOAN_SIMPLE_SELECTOR = "0x42b0b77c"


def build_flash_loan_simple_call(
    *,
    receiver: str,
    asset: str,
    amount_wei: int,
    params_hex: str = "0x",
    referral_code: int = 0,
) -> dict:
    """Return a structured description of the Aave V3 flashLoanSimple call.

    This intentionally does NOT ABI-encode (no eth_abi dependency in the
    skeleton).  A future executor module can take this dict and assemble
    the final transaction via the standard web3 contract bindings.
    """
    if not receiver or not asset:
        raise ValueError("receiver and asset addresses are required")
    if amount_wei <= 0:
        raise ValueError("amount_wei must be positive")
    if referral_code < 0 or referral_code > 0xFFFF:
        raise ValueError("referral_code must fit in uint16")
    return {
        "to": AAVE_V3_BASE_POOL,
        "selector": FLASH_LOAN_SIMPLE_SELECTOR,
        "args": {
            "receiver": receiver,
            "asset": asset,
            "amount": amount_wei,
            "params": params_hex,
            "referralCode": referral_code,
        },
    }


__all__ = [
    "AAVE_V3_BASE_POOL",
    "AAVE_V3_FLASH_PREMIUM_BPS",
    "FLASH_LOAN_SIMPLE_SELECTOR",
    "FlashLoanEconomics",
    "build_flash_loan_simple_call",
    "estimate_flash_loan_profit",
    "min_profitable_spread_bps",
]
