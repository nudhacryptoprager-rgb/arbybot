"""execution/signer.py — Key loader and sign_and_send factory.

Provides a ``make_sign_and_send`` factory that reads ``ARBY_PRIVATE_KEY``
from the environment and returns an async callable accepted by
``dex_dex_executor.execute_live()``.

Security rules (OWASP A02/A07):
  - Private key is read once at call time from the environment; it is
    NEVER logged, stored in a dict, or placed in any artifact/rollup.
  - EIP-155 replay protection is enforced (chainId in every tx).
  - The module refuses to sign if ``ARBY_PAPER_SIGNING=1`` is set.

Environment variables:
  ``ARBY_PRIVATE_KEY``        — 0x-prefixed hex private key (required for live).
  ``ARBY_PAPER_SIGNING``      — set to "1" to disable all signing (default "1").
  ``ARBY_LIVE_EXECUTION_ACK`` — must be exactly "YES" to allow live on-chain signing.
                                 Any other value (including empty) blocks live execution.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Coroutine

from core.logging import get_logger

logger = get_logger("execution.signer")

_PAPER_SIGNING_ENV = "ARBY_PAPER_SIGNING"
_PRIVATE_KEY_ENV = "ARBY_PRIVATE_KEY"
_LIVE_ACK_ENV = "ARBY_LIVE_EXECUTION_ACK"


def _paper_signing() -> bool:
    return os.environ.get(_PAPER_SIGNING_ENV, "1").strip() != "0"


def _live_ack_confirmed() -> bool:
    """Return True only when the operator has explicitly acknowledged live execution."""
    return os.environ.get(_LIVE_ACK_ENV, "").strip() == "YES"


def _load_private_key() -> str:
    """Read private key from env. Raises ValueError if missing or malformed."""
    raw = os.environ.get(_PRIVATE_KEY_ENV, "").strip()
    if not raw:
        raise ValueError(
            f"ARBY_PRIVATE_KEY is not set. Cannot sign transactions. "
            f"Set ARBY_PAPER_SIGNING=1 for paper mode."
        )
    if not raw.startswith("0x") or len(raw) != 66:
        raise ValueError(
            "ARBY_PRIVATE_KEY must be a 0x-prefixed 32-byte hex string (66 chars). "
            "Never log or commit private keys."
        )
    return raw


def make_sign_and_send(
    provider: Any,
    *,
    chain_id: int,
) -> Callable[[dict], Coroutine[Any, Any, str]]:
    """Return an async ``sign_and_send(tx_dict) -> tx_hash_hex`` function.

    The returned callable:
      1. Checks ``ARBY_PAPER_SIGNING`` — raises ``RuntimeError`` if set to "1".
      2. Loads the private key from ``ARBY_PRIVATE_KEY`` at call time.
      3. Signs the tx with EIP-155 chain-id and ``eth_account``.
      4. Submits via ``provider.send_raw_transaction()``.
      5. Returns the tx hash hex string.

    ``provider`` must expose ``send_raw_transaction(raw_hex: str) -> str``
    as in ``chains.providers.RPCProvider``.
    """

    async def _sign_and_send(tx_dict: dict) -> str:
        if _paper_signing():
            raise RuntimeError(
                "ARBY_PAPER_SIGNING=1 is active — live signing is blocked. "
                "Set ARBY_PAPER_SIGNING=0 to enable real transaction signing."
            )

        # Hard acknowledgment gate (Step 1 — reviewer requirement)
        if not _live_ack_confirmed():
            raise RuntimeError(
                "ARBY_LIVE_EXECUTION_ACK is not set to 'YES'. "
                "Set ARBY_LIVE_EXECUTION_ACK=YES to authorize live on-chain signing. "
                "This is a deliberate hard gate — never auto-set in code."
            )

        # Load key at call time (not at factory time) so env changes propagate
        private_key = _load_private_key()

        try:
            from eth_account import Account  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("eth_account not installed: pip install eth_account") from exc

        # Ensure EIP-155 chain-id is in the tx
        tx = dict(tx_dict)
        tx.setdefault("chainId", chain_id)

        signed = Account.sign_transaction(tx, private_key=private_key)

        # Normalize: web3.py v6 uses .raw_transaction (bytes), older uses .rawTransaction
        raw_bytes: bytes = getattr(signed, "raw_transaction", None) or getattr(
            signed, "rawTransaction", None
        )
        if raw_bytes is None:
            raise RuntimeError("eth_account.sign_transaction returned no raw bytes")

        raw_hex = "0x" + raw_bytes.hex()

        # provider.send_raw_transaction returns the tx hash hex
        tx_hash = await provider.send_raw_transaction(raw_hex)
        logger.info(
            "Transaction submitted",
            extra={"context": {"tx_hash": tx_hash, "chain_id": chain_id}},
        )
        return tx_hash

    return _sign_and_send


def get_signer_address() -> str:
    """Derive the public address from ``ARBY_PRIVATE_KEY``.

    Returns empty string if key is missing (paper mode). Never logs the key.
    """
    if _paper_signing():
        return ""
    try:
        private_key = _load_private_key()
        from eth_account import Account  # type: ignore[import-untyped]

        return Account.from_key(private_key).address
    except Exception:
        return ""


__all__ = ["make_sign_and_send", "get_signer_address"]
