"""Token and pair primitives for stable-anchor strategy."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TokenInfo:
    """Lightweight token descriptor used throughout the M8_1 pipeline."""

    symbol: str
    address: str
    decimals: int

    def __post_init__(self) -> None:
        if not self.address.startswith("0x"):
            raise ValueError(f"TokenInfo.address must be 0x-prefixed: {self.address!r}")
        if self.address != self.address.lower():
            raise ValueError(f"TokenInfo.address must be lowercase: {self.address!r}")
        if not (0 <= self.decimals <= 30):
            raise ValueError(f"TokenInfo.decimals out of range: {self.decimals}")


@dataclass(frozen=True)
class StablePair:
    """A pair of tokens suitable for stable-anchor quoting."""

    pair_id: str
    token0: TokenInfo
    token1: TokenInfo
    kind: str  # "STABLE_STABLE" | "STABLE_FOREX" | "ETH_LST"

    def __post_init__(self) -> None:
        valid_kinds = {"STABLE_STABLE", "STABLE_FOREX", "ETH_LST"}
        if self.kind not in valid_kinds:
            raise ValueError(f"Unknown pair kind: {self.kind!r} (expected one of {valid_kinds})")
        if self.token0.symbol >= self.token1.symbol:
            raise ValueError(
                f"StablePair tokens must be alphabetically sorted: "
                f"{self.token0.symbol!r} >= {self.token1.symbol!r}"
            )
        expected_id = f"{self.token0.symbol}_{self.token1.symbol}"
        if self.pair_id != expected_id:
            raise ValueError(
                f"pair_id mismatch: got {self.pair_id!r}, expected {expected_id!r}"
            )


def _make_pair(
    sym_a: str,
    sym_b: str,
    kind: str,
    tokens: Optional[Dict[str, TokenInfo]] = None,
) -> StablePair:
    if sym_a == sym_b:
        raise ValueError(f"Pair tokens must differ: {sym_a!r}")
    t0_sym, t1_sym = sorted([sym_a, sym_b])
    if tokens is None:
        tokens = {}
    t0 = tokens[t0_sym]
    t1 = tokens[t1_sym]
    pair_id = f"{t0_sym}_{t1_sym}"
    return StablePair(pair_id=pair_id, token0=t0, token1=t1, kind=kind)


def _build_from_config(cfg: "Any") -> "tuple[Dict[str, TokenInfo], List[StablePair]]":
    """Load YAML config and assemble BASE_TOKENS / BASE_STABLE_PAIRS."""
    token_cfgs = cfg.tokens  # Mapping[str, TokenCfg]
    base_tokens: Dict[str, TokenInfo] = {
        sym: TokenInfo(symbol=sym, address=tc.address, decimals=tc.decimals)
        for sym, tc in token_cfgs.items()
    }
    pairs: List[StablePair] = [
        _make_pair(pc.token0_symbol, pc.token1_symbol, pc.kind, base_tokens)
        for pc in cfg.pairs
    ]
    return base_tokens, pairs


def list_pairs(cfg: "Any" = None) -> "List[StablePair]":
    """Return a copy of the configured pair list."""
    _, pairs = _build_from_config(cfg)
    return list(pairs)


def list_pairs_from_cfg(cfg: "Any") -> "List[StablePair]":
    token_cfgs = cfg.tokens
    base_tokens: Dict[str, TokenInfo] = {
        sym: TokenInfo(symbol=sym, address=tc.address, decimals=tc.decimals)
        for sym, tc in token_cfgs.items()
    }
    pairs: List[StablePair] = [
        _make_pair(pc.token0_symbol, pc.token1_symbol, pc.kind, base_tokens)
        for pc in cfg.pairs
    ]
    return pairs
