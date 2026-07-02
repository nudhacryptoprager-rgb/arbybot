"""Uniswap v4 poolId existence resolver for mirror recall."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from m8.discovery.hint_verifier import (
    VERIFY_BYTECODE,
    VERIFY_FACTORY_GET_POOL,
    is_bytes32_hex,
    resolve_pool_id,
    verify_factory_pool,
    verify_v4_pool_id,
    verify_v4_pool_id_exists,
)
from m8.discovery.pool_hints import PoolHint

V4_POOLID_NOT_RESOLVED = "V4_POOLID_NOT_RESOLVED"
V4_POOLID_EXISTS = "V4_POOLID_EXISTS"
V4_MISLABEL_V3_POOL = "V4_MISLABEL_V3_POOL"


def _pair_from_hint(hint: PoolHint) -> Dict[str, Any]:
    raw = hint.raw or {}
    pair = raw.get("pair")
    return pair if isinstance(pair, dict) else {}


def _pool_id_from_hint(hint: PoolHint, pair: Dict[str, Any]) -> str:
  raw = hint.raw or {}
  for candidate in (
      raw.get("poolId"),
      raw.get("pool_id"),
      pair.get("poolId"),
      pair.get("pool_id"),
  ):
      val = str(candidate or "").strip().lower()
      if is_bytes32_hex(val):
          return val
  pool = str(hint.pool_address or "").lower().strip()
  if is_bytes32_hex(pool):
      return pool
  return ""


def resolve_v4_pool_existence(
    hint: PoolHint,
    *,
    chain: str = "base",
) -> Tuple[bool, str, Optional[str]]:
    """Resolve v4 poolId -> existence proof. Returns (exists, bucket, detail)."""
    h = hint
    pair = _pair_from_hint(h)
    pool_id = _pool_id_from_hint(h, pair) or resolve_pool_id(h) or str(h.pool_address or "")

    if is_bytes32_hex(pool_id):
        ok, method = verify_v4_pool_id_exists(pool_id, chain=chain)
        if ok:
            return True, V4_POOLID_EXISTS, method
        ok_full, method_full = verify_v4_pool_id(
            pool_id,
            chain=chain,
            token0=h.token0_addr,
            token1=h.token1_addr,
        )
        if ok_full:
            return True, V4_POOLID_EXISTS, method_full
        if h.token0_addr and h.token1_addr:
            v3 = PoolHint.from_dict(h.to_dict())
            v3.dex_id = "uniswap_v3"
            pair = _pair_from_hint(h)
            fee_raw = pair.get("feeTier") or pair.get("fee")
            if fee_raw is not None:
                try:
                    v3.fee = int(fee_raw)
                except (TypeError, ValueError):
                    pass
            f_ok, f_method = verify_factory_pool(v3, chain=chain)
            if f_ok:
                return True, V4_MISLABEL_V3_POOL, f_method
        return False, V4_POOLID_NOT_RESOLVED, method

    addr = str(h.pool_address or "").lower()
    if addr.startswith("0x") and len(addr) == 42:
        from m8.discovery.hint_verifier import _eth_get_code, _rpc_url

        url = _rpc_url(chain, None)
        if url and _eth_get_code(url, addr):
            return True, V4_MISLABEL_V3_POOL, VERIFY_BYTECODE

    fee = pair.get("feeTier") or pair.get("fee")
    if h.token0_addr and h.token1_addr and fee is not None:
        v3 = PoolHint.from_dict(h.to_dict())
        v3.dex_id = "uniswap_v3"
        try:
            v3.fee = int(fee)
        except (TypeError, ValueError):
            pass
        f_ok, f_method = verify_factory_pool(v3, chain=chain)
        if f_ok:
            return True, V4_MISLABEL_V3_POOL, f_method

    return False, V4_POOLID_NOT_RESOLVED, "V4_INVALID_POOL_ID"
