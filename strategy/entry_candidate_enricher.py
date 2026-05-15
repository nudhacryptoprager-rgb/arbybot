"""M8 Phase 2 — EntryCandidateEnricher.

Fetches on-chain liquidity, normalises to USD, estimates spread, detects
mirror pools, and runs honeypot + slippage checks — producing a fully-
populated :class:`~strategy.sniper_entry_decision.EntryCandidate` that
the :class:`~strategy.sniper_entry_decision.EntryDecisionEngine` can
evaluate without returning ``INSUFFICIENT_DATA`` for well-seeded pools.

Design principles
-----------------
- Non-blocking: every RPC call is wrapped in try/except; failures
  return ``None`` so the decision engine handles them as ``INSUFFICIENT_DATA``
  (the correct, conservative outcome).
- Offline-safe: if ``w3`` is ``None`` the enricher returns a bare
  candidate identical to what the pre-enricher pipeline produced.
- Backward-compatible: no changes to ``EntryCandidate`` or
  ``EntryDecisionEngine`` — this is a pure input-enrichment layer.
- Not thread-safe for ``seen_pairs`` state; ``smoke_run`` uses a single-
  threaded decision path so this is fine.

Liquidity fetch strategy
------------------------
- V2 / Aerodrome ve33 / solidly forks  → ``getReserves()``
- V3 / Slipstream / Pancakeswap V3     → ``slot0()`` + ``liquidity()``
  with full-range virtual-reserve approximation
- Uniswap V4                           → ``StateView.getSlot0(poolId)`` +
  ``StateView.getLiquidity(poolId)`` (Base mainnet StateView at
  ``0xa3c0c9b65bad0b08107aa264b0f3db444b867a71``). Same full-range virtual
  reserve formula as V3. Falls back to ``V4_SKIP`` when the StateView
  address is not configured.

USD normalization
-----------------
Total pool liquidity is estimated as ``2 × anchor_side × anchor_price_usd``
(assumes balanced pool ≈ both sides equal USD value).  If neither token is
an anchor, returns ``None`` with note ``"NO_ANCHOR_IN_PAIR"``.

Spread estimation
-----------------
1. **Mirror spread** (highest priority): price deviation between the new
   pool and the most-recently-seen pool for the same token pair on a
   different DEX.  Spread = |P_new − P_mirror| / P_mirror × 10 000 bps.
2. **Anchor-ratio spread**: when *both* tokens are anchors (e.g. USDC/WETH)
   we compare the pool's implied price to the hard-coded reference ratio.
3. Otherwise ``None`` — single-sided anchor pairs with no mirror have no
   external reference price.

Honeypot check
--------------
Delegates to :func:`~monitoring.sniper_honeypot.check_token_honeypot`.
Phase 1 logic: KNOWN_SCAM → FAIL, KNOWN_LEGIT → PASS, else UNKNOWN.
Returns the combined verdict for both tokens.

Slippage guard
--------------
Runs :class:`~execution.slippage_guard.SlippageGuard` with a $100 probe
trade, using anchor-token pricing to size ``amount_in``.  The guard result
is stored in the enrichment dict for artifact export; it does **not** feed
directly into the decision engine's reject taxonomy (Phase 3 concern).

Expected PnL (paper)
--------------------
When all 4 decision gates would pass, estimates:

    expected_pnl_usd = liquidity_usd × spread_bps/10000 × CAPTURE_RATE − GAS_COST_USD

where ``CAPTURE_RATE = 0.5`` and ``GAS_COST_USD = 0.30`` (Base L2).
``None`` when any gate input is missing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from discovery.new_pool_listener import NewPoolEvent
from execution.slippage_guard import SlippageGuard
from monitoring.sniper_honeypot import HoneypotVerdict, check_token_honeypot
from strategy.sniper_entry_decision import EntryCandidate

__all__ = [
    "EntryCandidateEnricher",
    "EnrichmentResult",
    "ANCHOR_TOKEN_USD",
    "ANCHOR_ADDRESSES",
    "NATIVE_ETH_ADDR",
    "V4_STATEVIEW_ADDR_BASE",
]

# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_CONFIG_PATH: Path = (
    Path(__file__).resolve().parent.parent / "config" / "enricher.yaml"
)


def _load_enricher_config() -> Dict[str, Any]:
    """Load enricher config from ``config/enricher.yaml``.

    Returns an empty dict on any error (missing file, bad YAML, import
    failure) so the enricher falls back to module-level defaults.
    """
    try:
        import yaml  # type: ignore[import]
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Anchor tokens — Base mainnet (all lowercase, no EIP-55 checksum)
# ---------------------------------------------------------------------------

ANCHOR_ADDRESSES: FrozenSet[str] = frozenset(
    {
        "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",  # USDC  (6 dec)
        "0x4200000000000000000000000000000000000006",  # WETH  (18 dec)
        "0x50c5725949a6f0c72e6c4a641f24049a917db0cb",  # DAI   (18 dec)
        "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca",  # USDbC (6 dec)
    }
)

# Native ETH sentinel — Uniswap V4 uses 0x000...000 as currency0 for native ETH.
# We treat it as WETH-equivalent for anchor pricing.
NATIVE_ETH_ADDR: str = "0x0000000000000000000000000000000000000000"
_WETH_BASE: str = "0x4200000000000000000000000000000000000006"

# Conservative USD prices — updated manually, no live oracle in Phase 2.
ANCHOR_TOKEN_USD: Dict[str, float] = {
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 1.0,
    "0x4200000000000000000000000000000000000006": 2500.0,
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": 1.0,
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": 1.0,
    # Native ETH (V4 zero address) priced as WETH.
    NATIVE_ETH_ADDR: 2500.0,
}

# Decimal overrides so we skip an RPC ``decimals()`` call for anchors.
_ANCHOR_DECIMALS: Dict[str, int] = {
    "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913": 6,
    "0x4200000000000000000000000000000000000006": 18,
    "0x50c5725949a6f0c72e6c4a641f24049a917db0cb": 18,
    "0xd9aaec86b65d86f6a7b5b1b0c42ffa531710b6ca": 6,
    NATIVE_ETH_ADDR: 18,  # native ETH has 18 decimals like WETH
}

_DEFAULT_DECIMALS = 18

# ---------------------------------------------------------------------------
# Uniswap V4 StateView contract (Base mainnet).
# Lets us read per-pool state (slot0 / liquidity) by poolId (bytes32) from the
# PoolManager singleton without per-pool contracts. See:
#   https://docs.uniswap.org/contracts/v4/reference/periphery/lens/StateView
# ---------------------------------------------------------------------------

V4_STATEVIEW_ADDR_BASE: str = "0xa3c0c9b65bad0b08107aa264b0f3db444b867a71"

_V4_STATEVIEW_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "poolId", "type": "bytes32"}],
        "name": "getSlot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint24", "name": "protocolFee", "type": "uint24"},
            {"internalType": "uint24", "name": "lpFee", "type": "uint24"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "poolId", "type": "bytes32"}],
        "name": "getLiquidity",
        "outputs": [{"internalType": "uint128", "name": "liquidity", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    },
]

_ERC20_TOTAL_SUPPLY_ABI = [
    {
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ---------------------------------------------------------------------------
# Minimal ABIs (no external JSON files)
# ---------------------------------------------------------------------------

_V2_PAIR_ABI = [
    {
        "inputs": [],
        "name": "getReserves",
        "outputs": [
            {"internalType": "uint112", "name": "_reserve0", "type": "uint112"},
            {"internalType": "uint112", "name": "_reserve1", "type": "uint112"},
            {"internalType": "uint32", "name": "_blockTimestampLast", "type": "uint32"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

_V3_POOL_ABI = [
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

_ERC20_DECIMALS_ABI = [
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]

# ---------------------------------------------------------------------------
# Paper-mode PnL constants
# ---------------------------------------------------------------------------

_SLIPPAGE_PROBE_USD: float = 100.0
_CAPTURE_RATE: float = 0.5      # fraction of spread realistically captured
_GAS_COST_USD: float = 0.30     # Base L2 gas per trade (~$0.30 conservative)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class EnrichmentResult:
    """Holds both the enriched :class:`EntryCandidate` and raw enrichment data.

    All fields except ``candidate`` may be ``None`` when the corresponding
    data source was unavailable or returned an error.
    """

    candidate: EntryCandidate
    # Liquidity
    liquidity_usd: Optional[float] = None
    liquidity_note: Optional[str] = None    # reason string when liquidity_usd is None
    reserve0_raw: Optional[float] = None    # human units (after decimal normalisation)
    reserve1_raw: Optional[float] = None
    # Spread
    estimated_spread_bps: Optional[float] = None
    spread_note: Optional[str] = None       # "FROM_MIRROR" | "FROM_ANCHOR_RATIO" | reason
    # Mirror
    mirror_found: bool = False
    mirror_dex: Optional[str] = None
    mirror_pool: Optional[str] = None
    # Safety checks
    honeypot_verdict: Optional[str] = None
    slippage_result: Optional[Dict[str, Any]] = None
    # Economics
    expected_pnl_usd: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialisable dict for inclusion in rolling artifact per-event entries."""
        return {
            "liquidity_usd": self.liquidity_usd,
            "liquidity_note": self.liquidity_note,
            "estimated_spread_bps": self.estimated_spread_bps,
            "spread_note": self.spread_note,
            "mirror_found": self.mirror_found,
            "mirror_dex": self.mirror_dex,
            "mirror_pool": self.mirror_pool,
            "honeypot_verdict": self.honeypot_verdict,
            "slippage_result": self.slippage_result,
            "expected_pnl_usd": self.expected_pnl_usd,
        }


# ---------------------------------------------------------------------------
# Enricher
# ---------------------------------------------------------------------------


class EntryCandidateEnricher:
    """On-chain enricher for new-pool events.

    Instantiate once per run, reuse for every event in the session.
    The ``seen_pairs`` registry grows as events are processed and enables
    intra-session mirror detection.

    Parameters
    ----------
    w3:
        Initialized ``web3.Web3`` instance (or ``None`` for offline mode).
    slippage_guard:
        Optional pre-built :class:`SlippageGuard` (one is created if omitted).
    config:
        Optional config dict overriding ``config/enricher.yaml`` defaults.
        Keys: ``anchor_token_usd``, ``slippage_probe_usd``, ``capture_rate``,
        ``gas_cost_usd``, ``min_liquidity_usd``, ``min_spread_bps``.
    """

    def __init__(
        self,
        w3: Any,
        *,
        slippage_guard: Optional[SlippageGuard] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._w3 = w3
        self._slippage_guard = slippage_guard or SlippageGuard()
        # Load config (from YAML file unless overridden by caller).
        self._config: Dict[str, Any] = config if config is not None else _load_enricher_config()
        # Anchor prices: merge YAML overrides on top of module-level defaults.
        _yaml_anchors: Dict[str, float] = {
            str(k).lower(): float(v)
            for k, v in (self._config.get("anchor_token_usd") or {}).items()
        }
        self._anchor_prices: Dict[str, float] = {**ANCHOR_TOKEN_USD, **_yaml_anchors}
        # PnL estimation parameters (config-driven with module-level fallbacks).
        self._slippage_probe_usd: float = float(
            self._config.get("slippage_probe_usd", _SLIPPAGE_PROBE_USD)
        )
        self._capture_rate: float = float(
            self._config.get("capture_rate", _CAPTURE_RATE)
        )
        self._gas_cost_usd: float = float(
            self._config.get("gas_cost_usd", _GAS_COST_USD)
        )
        # seen_pairs: FrozenSet[{token0, token1}] → [(dex, pool, price_token1_per_token0)]
        # price may be None when reserves were unavailable.
        self._seen_pairs: Dict[FrozenSet, List[Tuple[str, str, Optional[float]]]] = {}
        # decimals cache to avoid repeated RPC calls for unknown tokens
        self._decimals: Dict[str, int] = {}
        # On-chain honeypot probe cache: token_addr → "PASS" | "FAIL" | "UNKNOWN"
        # Avoids repeated eth_getCode / totalSupply RPCs for the same token.
        self._honeypot_probe_cache: Dict[str, str] = {}
        # V4 StateView address (config-driven; falls back to Base mainnet default).
        self._v4_stateview_addr: Optional[str] = (
            str(self._config.get("v4_stateview_address", V4_STATEVIEW_ADDR_BASE)).lower()
            if self._config.get("v4_stateview_address", V4_STATEVIEW_ADDR_BASE)
            else None
        )
        # Flag: when False, V4 reserves fetch is intentionally skipped (legacy behaviour).
        self._v4_enabled: bool = bool(self._config.get("v4_enabled", True))

    def config_snapshot(self) -> Dict[str, Any]:
        """Return the effective enricher config for artifact export."""
        return {
            "anchor_token_usd": dict(self._anchor_prices),
            "slippage_probe_usd": self._slippage_probe_usd,
            "capture_rate": self._capture_rate,
            "gas_cost_usd": self._gas_cost_usd,
            "config_source": str(_CONFIG_PATH) if _CONFIG_PATH.exists() else "defaults",
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_seen_pair(self, event: "NewPoolEvent") -> None:
        """Register *event* in the ``seen_pairs`` mirror registry WITHOUT
        fetching on-chain reserves.

        This is a lightweight alternative to :meth:`enrich` intended for
        bulk historical seeding (e.g. mirror_seeder) where we only need the
        pair→dex mapping and do NOT want to issue per-pool RPC calls.
        The implied price is recorded as ``None``; live events arriving later
        will populate real prices via the normal :meth:`enrich` path.
        """
        token0 = (event.token0 or "").lower()
        token1 = (event.token1 or "").lower()
        pool = (event.pool or "").lower()
        dex = event.dex or ""
        pair_key: FrozenSet = frozenset([token0, token1])
        if pair_key not in self._seen_pairs:
            self._seen_pairs[pair_key] = []
        self._seen_pairs[pair_key].append((dex, pool, None))

    def enrich(self, event: "NewPoolEvent") -> EnrichmentResult:
        """Return :class:`EnrichmentResult` for *event*.  Never raises."""
        token0 = (event.token0 or "").lower()
        token1 = (event.token1 or "").lower()
        pool = (event.pool or "").lower()
        dex = event.dex or ""

        pair_key: FrozenSet = frozenset([token0, token1])

        # Step 1: check for mirror pool BEFORE registering this pool.
        mirror_found, mirror_dex, mirror_pool, mirror_price = self._find_mirror(
            pair_key, dex
        )

        # Step 2: fetch on-chain reserves.
        reserve0, reserve1, liq_note = self._fetch_reserves(pool, token0, token1, dex)

        # Step 3: compute implied price for future mirror matching.
        implied_price: Optional[float] = None
        if reserve0 is not None and reserve1 is not None and reserve0 > 0:
            implied_price = reserve1 / reserve0

        # Register this pool in the mirror registry.
        if pair_key not in self._seen_pairs:
            self._seen_pairs[pair_key] = []
        self._seen_pairs[pair_key].append((dex, pool, implied_price))

        # Step 4: USD normalisation.
        liquidity_usd, norm_note = self._normalize_usd(token0, token1, reserve0, reserve1)
        if liquidity_usd is None:
            liq_note = liq_note or norm_note

        # Step 5: spread estimation.
        estimated_spread_bps, spread_note = self._estimate_spread(
            token0, token1, reserve0, reserve1, mirror_price=mirror_price
        )

        # Step 6: honeypot check.
        honeypot_verdict = self._check_honeypot(token0, token1)

        # Step 7: slippage guard (only when reserves are available).
        slippage_result: Optional[Dict[str, Any]] = None
        if reserve0 is not None and reserve1 is not None and reserve0 > 0 and reserve1 > 0:
            slippage_result = self._check_slippage(pool, token0, token1, reserve0, reserve1)

        # Step 8: expected PnL estimate (paper-mode only).
        expected_pnl_usd = self._compute_expected_pnl(
            liquidity_usd=liquidity_usd,
            spread_bps=estimated_spread_bps,
            mirror_found=mirror_found,
            token0=token0,
            token1=token1,
            honeypot_verdict=honeypot_verdict,
        )

        candidate = EntryCandidate(
            token0=token0,
            token1=token1,
            pool=pool,
            liquidity_usd=liquidity_usd,
            estimated_spread_bps=estimated_spread_bps,
            mirror_found=mirror_found,
            honeypot_verdict=honeypot_verdict,
            dex=dex,
            block_number=event.block_number,
        )

        return EnrichmentResult(
            candidate=candidate,
            liquidity_usd=liquidity_usd,
            liquidity_note=liq_note,
            reserve0_raw=reserve0,
            reserve1_raw=reserve1,
            estimated_spread_bps=estimated_spread_bps,
            spread_note=spread_note,
            mirror_found=mirror_found,
            mirror_dex=mirror_dex,
            mirror_pool=mirror_pool,
            honeypot_verdict=honeypot_verdict,
            slippage_result=slippage_result,
            expected_pnl_usd=expected_pnl_usd,
        )

    # ------------------------------------------------------------------
    # Mirror registry
    # ------------------------------------------------------------------

    def _find_mirror(
        self,
        pair_key: FrozenSet,
        dex: str,
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[float]]:
        """Search the intra-session registry for the same pair on a different DEX."""
        for seen_dex, seen_pool, seen_price in self._seen_pairs.get(pair_key, []):
            if seen_dex != dex:
                return True, seen_dex, seen_pool, seen_price
        return False, None, None, None

    # ------------------------------------------------------------------
    # Reserve fetch
    # ------------------------------------------------------------------

    def _fetch_reserves(
        self,
        pool: str,
        token0: str,
        token1: str,
        dex: str,
    ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        """Dispatch to V2 or V3 fetcher; return (r0_human, r1_human, note)."""
        if self._w3 is None:
            return None, None, "NO_W3"
        dex_l = (dex or "").lower()
        # Classify DEX family
        if any(kw in dex_l for kw in ("_v4", "uniswap_v4")):
            if not self._v4_enabled or not self._v4_stateview_addr:
                return None, None, "V4_SKIP"
            return self._fetch_v4(pool, token0, token1)
        if any(kw in dex_l for kw in ("_v3", "slipstream", "pancakeswap")):
            return self._fetch_v3(pool, token0, token1)
        # Default: V2-style (Uniswap V2, Aerodrome ve33, SushiSwap V2, etc.)
        return self._fetch_v2(pool, token0, token1)

    def _fetch_v4(
        self,
        pool: str,
        token0: str,
        token1: str,
    ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        """Fetch V4 pool state via the StateView lens contract.

        ``pool`` is the 32-byte ``PoolId`` (hex-encoded, 66 chars with 0x).
        Uses the same full-range virtual-reserve approximation as V3:
            token0_virtual = L / sqrt(P),  token1_virtual = L * sqrt(P)

        Returns None when the pool is freshly created with zero liquidity
        (the most common case at the Initialize event block).
        """
        try:
            # PoolId is bytes32 — must be a 32-byte string (66 hex chars incl. 0x).
            pool_id_hex = pool if pool.startswith("0x") else "0x" + pool
            if len(pool_id_hex) != 66:
                return None, None, "V4_BAD_POOLID"
            pool_id_bytes = bytes.fromhex(pool_id_hex[2:])

            contract = self._w3.eth.contract(
                address=self._w3.to_checksum_address(self._v4_stateview_addr),
                abi=_V4_STATEVIEW_ABI,
            )
            slot0 = contract.functions.getSlot0(pool_id_bytes).call()
            sqrt_x96 = int(slot0[0])
            liq_raw = int(contract.functions.getLiquidity(pool_id_bytes).call())

            if sqrt_x96 == 0 or liq_raw == 0:
                return None, None, "V4_ZERO_AT_CREATION"

            sqrt_p = sqrt_x96 / (2**96)
            if sqrt_p <= 0:
                return None, None, "V4_ZERO_PRICE"

            r0_raw = liq_raw / sqrt_p
            r1_raw = liq_raw * sqrt_p
            dec0 = self._get_decimals(token0)
            dec1 = self._get_decimals(token1)
            return r0_raw / 10**dec0, r1_raw / 10**dec1, None
        except Exception as exc:
            return None, None, f"V4_RPC_ERR:{str(exc)[:50]}"

    def _fetch_v2(
        self,
        pool: str,
        token0: str,
        token1: str,
    ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        try:
            contract = self._w3.eth.contract(
                address=self._w3.to_checksum_address(pool),
                abi=_V2_PAIR_ABI,
            )
            res = contract.functions.getReserves().call()
            r0_raw, r1_raw = int(res[0]), int(res[1])
            dec0 = self._get_decimals(token0)
            dec1 = self._get_decimals(token1)
            return r0_raw / 10**dec0, r1_raw / 10**dec1, None
        except Exception as exc:
            return None, None, f"V2_RPC_ERR:{str(exc)[:50]}"

    def _fetch_v3(
        self,
        pool: str,
        token0: str,
        token1: str,
    ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        """Approximate V3 virtual reserves from active liquidity and sqrtPriceX96.

        Uses the standard V3 formula for a full-range position:
            token0_virtual = L / sqrt(P),  token1_virtual = L * sqrt(P)
        where P = (sqrtPriceX96 / 2^96)^2.

        Returns None when the pool is freshly created with zero liquidity
        (the most common case for brand-new pools).
        """
        try:
            contract = self._w3.eth.contract(
                address=self._w3.to_checksum_address(pool),
                abi=_V3_POOL_ABI,
            )
            liq_raw = int(contract.functions.liquidity().call())
            slot0 = contract.functions.slot0().call()
            sqrt_x96 = int(slot0[0])

            if sqrt_x96 == 0 or liq_raw == 0:
                return None, None, "V3_ZERO_AT_CREATION"

            sqrt_p = sqrt_x96 / (2**96)
            if sqrt_p <= 0:
                return None, None, "V3_ZERO_PRICE"

            r0_raw = liq_raw / sqrt_p
            r1_raw = liq_raw * sqrt_p
            dec0 = self._get_decimals(token0)
            dec1 = self._get_decimals(token1)
            return r0_raw / 10**dec0, r1_raw / 10**dec1, None
        except Exception as exc:
            return None, None, f"V3_RPC_ERR:{str(exc)[:50]}"

    def _get_decimals(self, token: str) -> int:
        """Return ERC20 decimals for *token*; falls back to 18 on any error."""
        if token in _ANCHOR_DECIMALS:
            return _ANCHOR_DECIMALS[token]
        if token in self._decimals:
            return self._decimals[token]
        if self._w3 is None:
            return _DEFAULT_DECIMALS
        try:
            contract = self._w3.eth.contract(
                address=self._w3.to_checksum_address(token),
                abi=_ERC20_DECIMALS_ABI,
            )
            dec = int(contract.functions.decimals().call())
            self._decimals[token] = dec
            return dec
        except Exception:
            return _DEFAULT_DECIMALS

    # ------------------------------------------------------------------
    # USD normalisation
    # ------------------------------------------------------------------

    def _normalize_usd(
        self,
        token0: str,
        token1: str,
        r0: Optional[float],
        r1: Optional[float],
    ) -> Tuple[Optional[float], Optional[str]]:
        """Compute total pool liquidity in USD.

        Assumes a balanced pool so the anchor side × price × 2 ≈ total.
        """
        if r0 is None or r1 is None:
            return None, "RESERVES_UNAVAILABLE"
        price0 = self._anchor_prices.get(token0)
        price1 = self._anchor_prices.get(token1)
        if price0 is not None:
            return round(r0 * price0 * 2.0, 2), None
        if price1 is not None:
            return round(r1 * price1 * 2.0, 2), None
        return None, "NO_ANCHOR_IN_PAIR"

    # ------------------------------------------------------------------
    # Spread estimation
    # ------------------------------------------------------------------

    def _estimate_spread(
        self,
        token0: str,
        token1: str,
        r0: Optional[float],
        r1: Optional[float],
        mirror_price: Optional[float] = None,
    ) -> Tuple[Optional[float], Optional[str]]:
        """Return (spread_bps, note) using the best available reference.

        Priority:
          1. Mirror spread (same pair, different DEX price)
          2. Anchor-ratio spread (both tokens have known USD prices)
          3. None if no reference is available
        """
        if r0 is None or r1 is None or r0 <= 0 or r1 <= 0:
            return None, "ZERO_OR_MISSING_RESERVES"

        current_price = r1 / r0  # units: token1 per token0

        # 1. Mirror spread
        if mirror_price is not None and mirror_price > 0:
            deviation = abs(current_price - mirror_price) / mirror_price
            return round(deviation * 10_000.0, 1), "FROM_MIRROR"

        # 2. Anchor-ratio spread (both tokens have known USD prices)
        price0 = self._anchor_prices.get(token0)
        price1 = self._anchor_prices.get(token1)
        if price0 is not None and price1 is not None and price1 > 0:
            expected_price = price0 / price1  # token1 per token0
            if expected_price > 0:
                deviation = abs(current_price - expected_price) / expected_price
                return round(deviation * 10_000.0, 1), "FROM_ANCHOR_RATIO"

        return None, "NO_REFERENCE_PRICE"

    # ------------------------------------------------------------------
    # Honeypot check
    # ------------------------------------------------------------------

    def _check_honeypot(self, token0: str, token1: str) -> Optional[str]:
        """Combined honeypot verdict for both tokens of a pool.

        Combines the static registry (KNOWN_SCAM / KNOWN_LEGIT) with two
        cheap on-chain probes (eth_getCode + totalSupply) so that brand-new
        tokens which look like normal ERC20 contracts get a more useful
        verdict than the static-only UNKNOWN.

        Verdict matrix per token:
          registry FAIL → FAIL
          registry PASS → PASS
          registry UNKNOWN + on-chain probe FAIL → FAIL
          registry UNKNOWN + on-chain probe PASS → PASS (best-effort)
          registry UNKNOWN + on-chain probe UNKNOWN → UNKNOWN

        Combined verdict for the pool:
          - either FAIL  → FAIL
          - both PASS    → PASS
          - otherwise    → UNKNOWN

        Returns ``None`` only on unexpected internal exception.
        """
        try:
            v0 = self._token_honeypot_verdict(token0)
            v1 = self._token_honeypot_verdict(token1)
            if v0 == "FAIL" or v1 == "FAIL":
                return "FAIL"
            if v0 == "PASS" and v1 == "PASS":
                return "PASS"
            return "UNKNOWN"
        except Exception:
            return None

    def _token_honeypot_verdict(self, token: str) -> str:
        """Return ``PASS`` | ``FAIL`` | ``UNKNOWN`` for a single token.

        Combines the static registry with cheap on-chain probes. Cached.
        """
        token = (token or "").lower()
        # Native ETH sentinel — always safe.
        if token == NATIVE_ETH_ADDR:
            return "PASS"
        cached = self._honeypot_probe_cache.get(token)
        if cached is not None:
            return cached

        # 1. Static registry first (cheap, deterministic).
        try:
            registry = check_token_honeypot(token)
        except Exception:
            registry = HoneypotVerdict.UNKNOWN
        if registry == HoneypotVerdict.FAIL:
            self._honeypot_probe_cache[token] = "FAIL"
            return "FAIL"
        if registry == HoneypotVerdict.PASS:
            self._honeypot_probe_cache[token] = "PASS"
            return "PASS"

        # 2. On-chain probes (only when registry is UNKNOWN and w3 is available).
        if self._w3 is None:
            self._honeypot_probe_cache[token] = "UNKNOWN"
            return "UNKNOWN"

        # 2a. eth_getCode — empty bytecode means EOA / non-contract → FAIL.
        try:
            code = self._w3.eth.get_code(self._w3.to_checksum_address(token))
            code_hex = code.hex() if hasattr(code, "hex") else str(code)
            if not code_hex or code_hex in ("0x", "", "0x0"):
                self._honeypot_probe_cache[token] = "FAIL"
                return "FAIL"
        except Exception:
            # RPC error → don't conclude FAIL; fall through to UNKNOWN.
            self._honeypot_probe_cache[token] = "UNKNOWN"
            return "UNKNOWN"

        # 2b. totalSupply() call — reverts on broken ERC20 → FAIL.
        try:
            erc20 = self._w3.eth.contract(
                address=self._w3.to_checksum_address(token),
                abi=_ERC20_TOTAL_SUPPLY_ABI,
            )
            supply = int(erc20.functions.totalSupply().call())
            if supply <= 0:
                # zero supply tokens cannot be traded
                self._honeypot_probe_cache[token] = "FAIL"
                return "FAIL"
        except Exception:
            # totalSupply revert is suspicious but not definitive scam.
            self._honeypot_probe_cache[token] = "UNKNOWN"
            return "UNKNOWN"

        # Passed both probes: looks like a normal ERC20.  Mark as best-effort PASS.
        self._honeypot_probe_cache[token] = "PASS"
        return "PASS"

    # ------------------------------------------------------------------
    # Slippage guard
    # ------------------------------------------------------------------

    def _check_slippage(
        self,
        pool: str,
        token0: str,
        token1: str,
        r0: float,
        r1: float,
    ) -> Optional[Dict[str, Any]]:
        """Run a $-probe trade (``slippage_probe_usd``) through :class:`SlippageGuard`.

        Returns the guard result dict or ``None`` on any error.
        """
        try:
            price0 = self._anchor_prices.get(token0)
            price1 = self._anchor_prices.get(token1)
            if price0 is not None:
                amount_in = self._slippage_probe_usd / price0
                r_in, r_out = r0, r1
            elif price1 is not None:
                amount_in = self._slippage_probe_usd / price1
                r_in, r_out = r1, r0
            else:
                amount_in = self._slippage_probe_usd
                r_in, r_out = r0, r1
            result = self._slippage_guard.check(
                pool=pool,
                reserve_in=r_in,
                reserve_out=r_out,
                amount_in=amount_in,
                fee_bps=30.0,  # conservative (actual V3 pools may have lower fees)
            )
            return result.to_dict()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Expected PnL (paper-mode only)
    # ------------------------------------------------------------------

    def _compute_expected_pnl(
        self,
        *,
        liquidity_usd: Optional[float],
        spread_bps: Optional[float],
        mirror_found: bool,
        token0: str,
        token1: str,
        honeypot_verdict: Optional[str],
    ) -> Optional[float]:
        """Rough paper-mode PnL estimate.

        Only computed when all decision-gate inputs are available and
        the anchor/mirror condition passes.  Returns ``None`` otherwise.

            gross = liquidity_usd × spread_bps/10000 × CAPTURE_RATE
            net   = gross − GAS_COST_USD
        """
        if liquidity_usd is None or liquidity_usd <= 0:
            return None
        if spread_bps is None or spread_bps <= 0:
            return None
        if not (
            mirror_found
            or token0 in ANCHOR_ADDRESSES
            or token1 in ANCHOR_ADDRESSES
            or token0 == NATIVE_ETH_ADDR
            or token1 == NATIVE_ETH_ADDR
        ):
            return None
        # Only HONEYPOT_FAIL blocks PnL estimation. UNKNOWN is the conservative
        # default for any token outside the static registry and would suppress
        # all observability — so we *compute* PnL for UNKNOWN as a paper-only
        # what-if number. The decision engine still refuses to enter on UNKNOWN
        # (via ``reject_unknown_honeypot=True``), keeping safety unchanged.
        if honeypot_verdict == "FAIL":
            return None

        gross = liquidity_usd * (spread_bps / 10_000.0) * self._capture_rate
        net = round(gross - self._gas_cost_usd, 4)
        return net
