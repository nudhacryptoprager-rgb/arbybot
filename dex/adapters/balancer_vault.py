"""Balancer Vault adapter for M9 graph-arb scanner.

Quotes Balancer pools (weighted and composable-stable) via the single
shared Vault contract's ``queryBatchSwap`` view function.

Design
------
All Balancer pools (V2+) share a single Vault contract that holds all
token balances and routes swaps.  Unlike V3/V4 per-pool quoters, a single
RPC call to the Vault can quote a full multi-hop path in one round-trip.

This makes Balancer ideal for cycles that include stablecoin legs:
  USDC → DAI (Balancer ComposableStable) → WETH (Balancer 80/20 weighted)

Function: queryBatchSwap(kind, swaps[], assets[], funds)
  - kind: 0 = GIVEN_IN (exact input)
  - swaps[]: [{poolId, assetInIndex, assetOutIndex, amount, userData}]
  - assets[]: ordered token address list
  - funds: {sender, fromInternalBalance, recipient, toInternalBalance}
  - Returns: int256[] deltas (negative = tokens in, positive = tokens out)

Selector: keccak256("queryBatchSwap(uint8,(bytes32,uint256,uint256,uint256,bytes)[],address[],(address,bool,address,bool))")[:4]
computed: f84d066e

Integration with M9
-------------------
1. bridge_builder.py must map "balancer_stable" / "balancer_weighted" →
   "balancer_vault" adapter_type and remove them from _PENDING_ADAPTER_TYPES.
   (Do this after tests confirm the adapter works end-to-end.)
2. cost_model.py already maps "balancer_weighted" → 10 bps, "balancer_stable" → 4 bps.
3. quote_probe.py needs a new elif branch for "balancer_vault" or "balancer_stable"
   / "balancer_weighted" (can check by adapter_type prefix "balancer_").

Balancer Vault on Base
-----------------------
- Official Vault: 0xBA12222222228d8Ba445958a75a0704d566BF2C8  (same across EVM chains)

Known pool types on Base
-------------------------
- WeightedPool2Tokens / WeightedPool (80/20, 50/50, etc.)
- ComposableStablePool (replaces StablePool; supports BPT as liquidity)
- AaveLinearPool (boosted pools with yield)
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from core.logging import get_logger
from core.exceptions import QuoteError, ErrorCode

logger = get_logger(__name__)

# Balancer Vault: same address on all supported EVM chains (Base, Ethereum, Arbitrum, etc.)
BALANCER_VAULT_ADDRESS: str = "0xBA12222222228d8Ba445958a75a0704d566BF2C8"

# queryBatchSwap selector
# keccak256("queryBatchSwap(uint8,(bytes32,uint256,uint256,uint256,bytes)[],address[],(address,bool,address,bool))")
_SELECTOR_QUERY_BATCH_SWAP = bytes.fromhex("f84d066e")

# SwapKind: 0 = GIVEN_IN
_SWAP_KIND_GIVEN_IN = 0

_QUERY_BATCH_SWAP_ABI = [
    {
        "name": "queryBatchSwap",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "kind", "type": "uint8"},
            {
                "name": "swaps",
                "type": "tuple[]",
                "components": [
                    {"name": "poolId", "type": "bytes32"},
                    {"name": "assetInIndex", "type": "uint256"},
                    {"name": "assetOutIndex", "type": "uint256"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "userData", "type": "bytes"},
                ],
            },
            {"name": "assets", "type": "address[]"},
            {
                "name": "funds",
                "type": "tuple",
                "components": [
                    {"name": "sender", "type": "address"},
                    {"name": "fromInternalBalance", "type": "bool"},
                    {"name": "recipient", "type": "address"},
                    {"name": "toInternalBalance", "type": "bool"},
                ],
            },
        ],
        "outputs": [{"name": "", "type": "int256[]"}],
    }
]


def _encode_query_batch_swap(
    pool_id: str,
    token_in_addr: str,
    token_out_addr: str,
    amount_in: int,
    sender: str = "0x" + "0" * 40,
    recipient: str = "0x" + "0" * 40,
    *,
    all_assets: Optional[List[str]] = None,
) -> bytes:
    """Encode a single-hop ``queryBatchSwap`` call for a Balancer pool."""
    from web3 import Web3

    token_in_addr = token_in_addr.lower()
    token_out_addr = token_out_addr.lower()
    if all_assets is None:
        all_assets = [token_in_addr, token_out_addr]
    else:
        all_assets = [a.lower() for a in all_assets]
    try:
        asset_in_index = all_assets.index(token_in_addr)
        asset_out_index = all_assets.index(token_out_addr)
    except ValueError as exc:
        raise ValueError(
            f"token pair not in all_assets: {token_in_addr} -> {token_out_addr}"
        ) from exc

    pool_id_bytes = bytes.fromhex(pool_id.replace("0x", ""))[:32]
    w3 = Web3()
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(BALANCER_VAULT_ADDRESS),
        abi=_QUERY_BATCH_SWAP_ABI,
    )
    hex_data = contract.encode_abi(
        "queryBatchSwap",
        args=[
            _SWAP_KIND_GIVEN_IN,
            [
                (
                    pool_id_bytes,
                    asset_in_index,
                    asset_out_index,
                    amount_in,
                    b"",
                )
            ],
            [Web3.to_checksum_address(a) for a in all_assets],
            (
                Web3.to_checksum_address(sender.lower()),
                False,
                Web3.to_checksum_address(recipient.lower()),
                False,
            ),
        ],
    )
    raw = hex_data[2:] if hex_data.startswith("0x") else hex_data
    return bytes.fromhex(raw)


def _decode_query_batch_swap(hex_result: str) -> Tuple[int, int]:
    """Decode ``queryBatchSwap`` response: int256[] deltas.

    Returns ``(delta_in, delta_out)`` where:
    - delta_in  > 0 (token sent into Vault — positive = vault receives)
    - delta_out < 0 (token sent out of Vault — negative = vault sends)

    Amount out = abs(delta_out).
    """
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 4 * 64:
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"Balancer queryBatchSwap response too short: {len(raw)} chars",
        )
    # Response is: int256[] = offset(32) + length(32) + elements...
    # offset to array data
    arr_offset = int(raw[:64], 16) * 2  # convert byte offset → hex-char offset
    arr_len = int(raw[arr_offset:arr_offset + 64], 16)
    if arr_len < 2:
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"Balancer queryBatchSwap returned {arr_len} deltas, expected >=2",
        )
    delta0_hex = raw[arr_offset + 64: arr_offset + 128]
    delta1_hex = raw[arr_offset + 128: arr_offset + 192]
    delta0 = int(delta0_hex, 16)
    delta1 = int(delta1_hex, 16)
    # Sign-extend from int256
    if delta0 >= 2 ** 255:
        delta0 -= 2 ** 256
    if delta1 >= 2 ** 255:
        delta1 -= 2 ** 256
    return delta0, delta1


class BalancerVaultAdapter:
    """Adapter for Balancer V2+ pools via single Vault queryBatchSwap.

    Supports WeightedPool, ComposableStablePool, and other V2+ pool types.

    Parameters
    ----------
    provider:
        Provider with ``eth_call(to, data, block) -> str`` method.
    vault_address:
        Balancer Vault contract address. Defaults to the canonical address.
    dex_id:
        DEX identifier (default "balancer").
    """

    ADAPTER_TYPE: str = "balancer_vault"

    def __init__(
        self,
        provider: Any,
        vault_address: str = BALANCER_VAULT_ADDRESS,
        dex_id: str = "balancer",
    ) -> None:
        self.provider = provider
        self.vault_address = vault_address
        self.dex_id = dex_id

    def get_quote(
        self,
        pool_id: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: Optional[int] = None,          # not used for Balancer
        block_number: Optional[int] = None,
        pool_address: Optional[str] = None,  # optional for API consistency
    ) -> dict:
        """Quote via Balancer Vault queryBatchSwap.

        Parameters
        ----------
        pool_id:
            32-byte Balancer pool ID (not the pool *address* — includes pool type bits).
            Typically: ``0x<pool_address><2 bytes pool type><4 bytes nonce>``.
        token_in, token_out:
            Token addresses.
        amount_in:
            Token-in amount (raw).
        """
        if not pool_id or len(pool_id.replace("0x", "")) != 64:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"balancer: pool_id must be 32-byte hex, got {pool_id!r}",
            )
        if not token_in or not token_out:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message="balancer: token_in and token_out required",
            )
        if amount_in <= 0:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"balancer: amount_in must be positive, got {amount_in}",
            )

        calldata = "0x" + _encode_query_batch_swap(
            pool_id=pool_id,
            token_in_addr=token_in,
            token_out_addr=token_out,
            amount_in=amount_in,
        ).hex()

        try:
            result = self.provider.eth_call(
                to=self.vault_address,
                data=calldata,
                block=block_number,
            )
            delta_in, delta_out = _decode_query_batch_swap(result)
        except QuoteError:
            raise
        except Exception as e:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"Balancer queryBatchSwap failed: {e}",
            ) from e

        # delta_in should be positive (Vault receives token_in)
        # delta_out should be negative (Vault sends token_out)
        amount_out = abs(delta_out)
        if amount_out == 0:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"Balancer queryBatchSwap returned 0 amount_out for pool {pool_id}",
            )

        return {
            "amount_out": amount_out,
            "gas_estimate": 150_000,  # Balancer calls are gas-moderate (vault routing overhead)
            "quote_source": "balancer_vault_queryBatchSwap",
            "adapter_type": self.ADAPTER_TYPE,
            "delta_in": delta_in,
            "delta_out": delta_out,
            "sqrt_price_after": 0,
            "ticks_crossed": 0,
        }

    def supports_fee_tiers(self) -> bool:
        """Balancer pools do not use discrete fee tiers in the V3 sense."""
        return False
