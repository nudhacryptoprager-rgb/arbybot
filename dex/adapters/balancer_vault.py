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


def _encode_query_batch_swap(
    pool_id: str,
    token_in_addr: str,
    token_out_addr: str,
    amount_in: int,
    sender: str = "0x" + "0" * 40,
    recipient: str = "0x" + "0" * 40,
) -> bytes:
    """Encode a single-hop ``queryBatchSwap`` call for a Balancer pool.

    This encodes the minimal ABI for a 1-pool, 2-token GIVEN_IN swap.

    ABI encoding layout (all uint256 aligned):
    - selector (4 bytes)
    - kind (uint8 as uint256)
    - offset to swaps array (uint256)
    - offset to assets array (uint256)
    - funds struct inline (4 × uint256)
    - swaps array: length + 1 element (5 × uint256 + bytes offset + bytes length)
    - assets array: length + 2 addresses
    """
    zero_addr = "0x" + "0" * 40

    # Canonicalize addresses (lowercase, 20-byte)
    pool_id_bytes = bytes.fromhex(pool_id.replace("0x", ""))[:32]  # pool_id is bytes32
    token_in_int = int(token_in_addr, 16)
    token_out_int = int(token_out_addr, 16)
    sender_int = int(sender, 16)
    recipient_int = int(recipient, 16)

    # Build static head (kind + 2 offsets + funds)
    kind_enc = _SWAP_KIND_GIVEN_IN.to_bytes(32, "big")

    # The ABI for queryBatchSwap has:
    #   arg[0]: kind (uint8)
    #   arg[1]: swaps[] (dynamic)
    #   arg[2]: assets[] (dynamic)
    #   arg[3]: funds (FundManagement struct — 4 slots)
    #
    # Static head layout (slot positions, 0-based 32-byte words):
    #   0: kind
    #   1: offset to swaps[] data (relative to arg[0] start)
    #   2: offset to assets[] data
    #   3-6: funds (sender, fromInternalBalance, recipient, toInternalBalance)
    #
    # swaps[] data starts at byte offset = 7 * 32 = 224 (from arg start)
    # assets[] data starts after swaps[] (dynamic, computed below)

    # 1 swap × 5 uint256 + 1 dynamic bytes (empty, offset + len = 2 uint256)
    # swap element layout: poolId(bytes32), assetInIndex(uint256), assetOutIndex(uint256),
    #                      amount(uint256), userData_offset(uint256) [relative to element start]
    #                      userData_length(uint256), userData_bytes (none)
    # Total per swap = 6 uint256 = 192 bytes
    # swaps[] ABI block = length(1 uint256) + 1 element (192 bytes) = 224 bytes

    # Offsets (relative to start of data section, i.e., after selector)
    # static portion: kind(32) + offset_swaps(32) + offset_assets(32) + funds(4×32) = 7 × 32 = 224
    swaps_offset = 7 * 32   # 224 bytes
    # swaps block: length(32) + 1 element × 6 slots(192) = 224 bytes
    assets_offset = swaps_offset + 32 + 6 * 32  # 224 + 224 = 448

    # Funds struct
    from_internal = 0
    to_internal = 0

    # Static head (7 × 32 bytes)
    head = (
        kind_enc
        + swaps_offset.to_bytes(32, "big")
        + assets_offset.to_bytes(32, "big")
        + sender_int.to_bytes(32, "big")
        + from_internal.to_bytes(32, "big")
        + recipient_int.to_bytes(32, "big")
        + to_internal.to_bytes(32, "big")
    )

    # Swaps array: length=1, then one BatchSwapStep
    # BatchSwapStep: {bytes32 poolId, uint256 assetInIndex, uint256 assetOutIndex,
    #                 uint256 amount, bytes userData}
    # For ABI encoding of struct with bytes (dynamic), we inline the bytes offset
    # relative to the start of the struct encoding.
    # userData is empty → offset points 5*32=160 bytes into struct, length=0
    userData_offset_in_struct = 5 * 32  # 5 preceding uint256 fields
    swap_step = (
        pool_id_bytes  # bytes32 poolId (already 32 bytes)
        + (0).to_bytes(32, "big")  # assetInIndex = 0
        + (1).to_bytes(32, "big")  # assetOutIndex = 1
        + amount_in.to_bytes(32, "big")  # amount
        + userData_offset_in_struct.to_bytes(32, "big")  # userData offset (relative to struct start)
        + (0).to_bytes(32, "big")  # userData length = 0
    )
    swaps_block = (1).to_bytes(32, "big") + swap_step  # length=1 + element

    # Assets array: 2 elements [token_in, token_out]
    assets_block = (
        (2).to_bytes(32, "big")
        + token_in_int.to_bytes(32, "big")
        + token_out_int.to_bytes(32, "big")
    )

    return _SELECTOR_QUERY_BATCH_SWAP + head + swaps_block + assets_block


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
