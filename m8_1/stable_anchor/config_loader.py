"""M8_1 config loader — validated immutable config dataclasses."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple
from pathlib import Path

import yaml  # type: ignore[import]


_ADDR_RE = re.compile(r"^0x[0-9a-f]{40}$")
_DEFAULT_CONFIG = "m8_1_stable_anchor.yaml"
_VALID_ADAPTER_TYPES = {
    "uniswap_v3",
    "uniswap_v4",
    "aerodrome_slipstream",
    "aerodrome_v2_stable",
    "ve33",
    "curve_stable",
    "balancer_stable",
    "uniswap_v2",
    "maverick_v2",
    # Algebra-protocol DEXes (Camelot V3, QuickSwap V3): dynamic-fee concentrated liquidity.
    # Quotes via quoteExactInputSingle(tokenIn,tokenOut,amountIn,limitSqrtPrice=0) — no fee param.
    "algebra",
}


def _check_addr(label: str, addr: str) -> None:
    if not _ADDR_RE.match(addr):
        raise ValueError(
            f"{label} must be lowercase 0x-prefixed 40-hex address, got: {addr!r}"
        )


@dataclass(frozen=True)
class DexCfg:
    dex_id: str
    enabled: bool
    adapter_type: str
    factory: str
    quoter: str
    fee_tiers: tuple
    tick_spacings: tuple
    quarantine_reason: Optional[str]
    pools: dict

    def pool_for(self, pair_id: str) -> Optional[str]:
        """Return pool address for ``pair_id``, or None if not found."""
        return self.pools.get(pair_id)

    def __post_init__(self) -> None:
        if not self.enabled:
            return
        if self.adapter_type not in _VALID_ADAPTER_TYPES:
            raise ValueError(
                f"dex {self.dex_id}: adapter_type must be in {_VALID_ADAPTER_TYPES}, "
                f"got {self.adapter_type!r}"
            )
        if self.factory != "0x0000000000000000000000000000000000000000":
            _check_addr(f"dex.{self.dex_id}.factory", self.factory)
        if self.quoter != "0x0000000000000000000000000000000000000000":
            _check_addr(f"dex.{self.dex_id}.quoter", self.quoter)
        if self.adapter_type == "uniswap_v3" and not self.fee_tiers:
            raise ValueError(f"dex {self.dex_id}: uniswap_v3 requires non-empty fee_tiers")
        for ft in self.fee_tiers:
            if not isinstance(ft, int) or ft < 0:
                raise ValueError(f"dex {self.dex_id}: invalid fee tier {ft!r}")
        if self.adapter_type == "aerodrome_slipstream" and not self.tick_spacings:
            raise ValueError(f"dex {self.dex_id}: aerodrome_slipstream requires non-empty tick_spacings")


@dataclass(frozen=True)
class TokenCfg:
    symbol: str
    address: str
    decimals: int

    def __post_init__(self) -> None:
        _check_addr(f"tokens.{self.symbol}.address", self.address)
        if not (0 <= self.decimals <= 30):
            raise ValueError(f"tokens.{self.symbol}: decimals out of range: {self.decimals}")


@dataclass(frozen=True)
class PairCfg:
    pair_id: str
    token0_symbol: str
    token1_symbol: str
    kind: str

    def __post_init__(self) -> None:
        valid_kinds = {"STABLE_STABLE", "STABLE_FOREX", "ETH_LST"}
        if self.kind not in valid_kinds:
            raise ValueError(f"pair {self.pair_id}: kind must be in {valid_kinds}")
        if self.token0_symbol >= self.token1_symbol:
            raise ValueError(
                f"pair {self.pair_id}: tokens must be alphabetically sorted "
                f"({self.token0_symbol!r} < {self.token1_symbol!r})"
            )
        expected = f"{self.token0_symbol}_{self.token1_symbol}"
        if self.pair_id != expected:
            raise ValueError(f"pair_id {self.pair_id!r} must equal {expected!r}")


@dataclass(frozen=True)
class HealthFilterCfg:
    min_liquidity: int
    require_slot0_unlocked: bool
    require_sqrt_price_positive: bool


@dataclass(frozen=True)
class QuoteGateCfg:
    target_quote_success_rate: float
    target_rpc_error_rate_max: float
    async_max_workers: int
    async_timeout_s: int
    retry_backoff_s: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.target_quote_success_rate <= 1.0):
            raise ValueError(f"target_quote_success_rate out of range: {self.target_quote_success_rate}")
        if not (0.0 <= self.target_rpc_error_rate_max <= 1.0):
            raise ValueError(f"target_rpc_error_rate_max out of range: {self.target_rpc_error_rate_max}")


@dataclass(frozen=True)
class CostProfile:
    name: str
    gas_usd: float
    l1_fee_usd: float
    slippage_bps: float


@dataclass(frozen=True)
class CostModelCfg:
    default_profile: str
    profiles: Mapping[str, CostProfile]
    gas_mode_default: str
    paper_haircut: float
    slippage_mode_default: str

    def get_profile(self, name: Optional[str] = None) -> CostProfile:
        key = name or self.default_profile
        if key not in self.profiles:
            raise ValueError(f"unknown cost profile: {key!r}")
        return self.profiles[key]


@dataclass(frozen=True)
class ReplayCfg:
    enabled_by_default: bool
    top_n_near_misses: int
    anvil_url_default: str
    fork_block_default: str
    require_non_stub: bool


@dataclass(frozen=True)
class SimulationCfg:
    univ3_router02: str
    aero_router: str
    simulation_test_addr: str
    usdc_usdt_v3_pool: str

    def __post_init__(self) -> None:
        _check_addr("simulation.univ3_router02", self.univ3_router02)
        _check_addr("simulation.aero_router", self.aero_router)
        _check_addr("simulation.simulation_test_addr", self.simulation_test_addr)
        _check_addr("simulation.usdc_usdt_v3_pool", self.usdc_usdt_v3_pool)


@dataclass(frozen=True)
class M8_1Config:
    """Validated M8_1 stable-anchor config (immutable)."""

    schema_version: str
    chain: str
    chain_id: int
    dexes: Mapping[str, DexCfg]
    tokens: Mapping[str, TokenCfg]
    pairs: Tuple[PairCfg, ...]
    factory_ladder: Mapping[str, Mapping[int, str]]
    health_filter: HealthFilterCfg
    quote_gate: QuoteGateCfg
    sizes_usd: Tuple[float, ...]
    cost_model: CostModelCfg
    replay: ReplayCfg
    simulation: SimulationCfg
    public_rpc_blocklist: Tuple[str, ...]
    source_path: Optional[str]

    def enabled_dexes(self) -> Dict[str, DexCfg]:
        return {dex_id: d for dex_id, d in self.dexes.items() if d.enabled}

    def factory_class(self, dex_id: str, fee: int) -> str:
        """Return ladder class for (dex_id, fee). Unknown → MID_EFFICIENCY."""
        try:
            return self.factory_ladder[dex_id][fee]
        except (KeyError, TypeError):
            return "MID_EFFICIENCY"


def _parse_dex(dex_id: str, raw: dict) -> DexCfg:
    return DexCfg(
        dex_id=dex_id,
        enabled=bool(raw.get("enabled", True)),
        adapter_type=raw["adapter_type"],
        factory=raw.get("factory", "0x0000000000000000000000000000000000000000"),
        quoter=raw.get("quoter", "0x0000000000000000000000000000000000000000"),
        fee_tiers=tuple(int(x) for x in raw.get("fee_tiers", [])),
        tick_spacings=tuple(int(x) for x in raw.get("tick_spacings", [])),
        quarantine_reason=raw.get("quarantine_reason"),
        pools=dict(raw.get("pools", {})),
    )


def _parse_token(sym: str, raw: dict) -> TokenCfg:
    return TokenCfg(
        symbol=sym,
        address=raw["address"],
        decimals=int(raw["decimals"]),
    )


def _parse_pair(raw: dict) -> PairCfg:
    return PairCfg(
        pair_id=raw["pair_id"],
        token0_symbol=raw["token0_symbol"],
        token1_symbol=raw["token1_symbol"],
        kind=raw["kind"],
    )


def _parse_health_filter(raw: dict) -> HealthFilterCfg:
    return HealthFilterCfg(
        min_liquidity=int(raw.get("min_liquidity", 0)),
        require_slot0_unlocked=bool(raw.get("require_slot0_unlocked", False)),
        require_sqrt_price_positive=bool(raw.get("require_sqrt_price_positive", False)),
    )


def _parse_quote_gate(raw: dict) -> QuoteGateCfg:
    return QuoteGateCfg(
        target_quote_success_rate=float(raw.get("target_quote_success_rate", 0.0)),
        target_rpc_error_rate_max=float(raw.get("target_rpc_error_rate_max", 1.0)),
        async_max_workers=int(raw.get("async_max_workers", 4)),
        async_timeout_s=int(raw.get("async_timeout_s", 10)),
        retry_backoff_s=float(raw.get("retry_backoff_s", 1.0)),
    )


def _parse_cost_profile(name: str, raw: dict) -> CostProfile:
    return CostProfile(
        name=name,
        gas_usd=float(raw.get("gas_usd", 0.0)),
        l1_fee_usd=float(raw.get("l1_fee_usd", 0.0)),
        slippage_bps=float(raw.get("slippage_bps", 0.0)),
    )


def _parse_cost_model(raw: dict) -> CostModelCfg:
    profiles = {k: _parse_cost_profile(k, v) for k, v in raw.get("profiles", {}).items()}
    return CostModelCfg(
        default_profile=raw.get("default_profile", "default"),
        profiles=profiles,
        gas_mode_default=raw.get("gas_mode_default", "static"),
        paper_haircut=float(raw.get("paper_haircut", 0.0)),
        slippage_mode_default=raw.get("slippage_mode_default", "static"),
    )


def _parse_replay(raw: dict) -> ReplayCfg:
    return ReplayCfg(
        enabled_by_default=bool(raw.get("enabled_by_default", False)),
        top_n_near_misses=int(raw.get("top_n_near_misses", 0)),
        anvil_url_default=raw.get("anvil_url_default", "http://127.0.0.1:8545"),
        fork_block_default=raw.get("fork_block_default", "latest"),
        require_non_stub=bool(raw.get("require_non_stub", False)),
    )


def _parse_simulation(raw: dict) -> SimulationCfg:
    return SimulationCfg(
        univ3_router02=raw.get("univ3_router02", "0x0000000000000000000000000000000000000000"),
        aero_router=raw.get("aero_router", "0x0000000000000000000000000000000000000000"),
        simulation_test_addr=raw.get("simulation_test_addr", "0x0000000000000000000000000000000000000000"),
        usdc_usdt_v3_pool=raw.get("usdc_usdt_v3_pool", "0x0000000000000000000000000000000000000000"),
    )


def load_config(path: "str | Path") -> M8_1Config:
    """Load and validate M8_1 config from YAML file."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    dexes: Dict[str, DexCfg] = {k: _parse_dex(k, v) for k, v in raw.get("dexes", {}).items()}
    tokens: Dict[str, TokenCfg] = {k: _parse_token(k, v) for k, v in raw.get("tokens", {}).items()}
    pairs: Tuple[PairCfg, ...] = tuple(_parse_pair(p) for p in raw.get("pairs", []))

    factory_ladder: Dict[str, Dict[int, str]] = {}
    for dex_id, tiers in raw.get("factory_ladder", {}).items():
        factory_ladder[dex_id] = {int(k): v for k, v in tiers.items()}

    return M8_1Config(
        schema_version=str(raw.get("schema_version", "m8_1.0")),
        chain=str(raw.get("chain", "base")),
        chain_id=int(raw.get("chain_id", 8453)),
        dexes=dexes,
        tokens=tokens,
        pairs=pairs,
        factory_ladder=factory_ladder,
        health_filter=_parse_health_filter(raw.get("health_filter", {})),
        quote_gate=_parse_quote_gate(raw.get("quote_gate", {})),
        sizes_usd=tuple(float(x) for x in raw.get("sizes_usd", [])),
        cost_model=_parse_cost_model(raw.get("cost_model", {})),
        replay=_parse_replay(raw.get("replay", {})),
        simulation=_parse_simulation(raw.get("simulation", {})),
        public_rpc_blocklist=tuple(raw.get("public_rpc_blocklist", [])),
        source_path=str(path),
    )
