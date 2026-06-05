"""Probe EVM token contract deployment block via eth_getCode binary search."""
from __future__ import annotations

from typing import Any, Callable, Optional


def _has_code_at(w3: Any, address: str, block: int) -> bool:
    code = w3.eth.get_code(w3.to_checksum_address(address), block)
    return bool(code and len(code) > 0)


def probe_token_creation_block(
    w3: Any,
    address: str,
    *,
    latest_block: Optional[int] = None,
    low_block: int = 0,
    has_code_fn: Optional[Callable[[str, int], bool]] = None,
) -> Optional[int]:
    """Return first block where ``address`` has non-empty bytecode, or None."""
    if not address:
        return None
    addr = address.lower()
    check = has_code_fn or (lambda a, b: _has_code_at(w3, a, b))
    hi = latest_block if latest_block is not None else int(w3.eth.block_number)
    if not check(addr, hi):
        return None
    if check(addr, low_block):
        return low_block

    lo, hi = low_block, hi
    while lo < hi:
        mid = (lo + hi) // 2
        if check(addr, mid):
            hi = mid
        else:
            lo = mid + 1
    return lo if check(addr, lo) else None


def annotate_token_contract_age(
    rows: list[dict[str, Any]],
    *,
    address_key: str = "token0_addr",
    w3: Any,
    latest_block: Optional[int] = None,
) -> dict[str, Any]:
    """Mutate ``rows`` in place with ``token_creation_block`` when probe succeeds."""
    probed = 0
    found = 0
    cache: dict[str, Optional[int]] = {}
    for row in rows:
        addr = (row.get(address_key) or "").lower()
        if not addr or addr in cache:
            row["token_creation_block"] = cache.get(addr)
            continue
        block = probe_token_creation_block(w3, addr, latest_block=latest_block)
        cache[addr] = block
        row["token_creation_block"] = block
        probed += 1
        if block is not None:
            found += 1
    return {"probed": probed, "found": found, "unique_addresses": len(cache)}
