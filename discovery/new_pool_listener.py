"""M8 Phase 1 — New-pool factory event parser.

This module is **pure and side-effect-free**:
  - no network calls,
  - no web3 imports at module load,
  - no rolling artifact writes,
  - no cold-lane or orderflow modifications.

Responsibilities:
  1. Load factory config from ``config/new_pool_factories.yaml``.
  2. Parse raw ``eth_getLogs`` / ``eth_subscribe logs`` dicts into
     ``NewPoolEvent`` dataclasses.
  3. Produce deterministic event IDs for deduplication.
  4. Deduplicate event lists.

The runtime listener loop, artifact writing, and cold-lane integration
are intentionally NOT in this module (those are Phase 1 Day 8–9 concerns).

Log layout constants (see config/new_pool_factories.yaml):
  ``v3_pool_created``         — Uniswap V3 / PancakeSwap V3
  ``slipstream_pool_created`` — Aerodrome Slipstream CL
  ``ve33_pool_created``       — Aerodrome/Velodrome ve33 PoolFactory
  ``ve33_pair_created``       — Aerodrome ve33 / Solidly forks
  ``v2_pair_created``         — Uniswap V2 / SushiSwap V2 / BaseSwap V2
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "NewPoolEvent",
    "FactoryConfig",
    "load_factory_config",
    "parse_raw_log",
    "make_event_id",
    "dedup_events",
    "LAYOUT_V3_POOL_CREATED",
    "LAYOUT_SLIPSTREAM_POOL_CREATED",
    "LAYOUT_VE33_POOL_CREATED",
    "LAYOUT_VE33_PAIR_CREATED",
    "LAYOUT_V2_PAIR_CREATED",
    "LAYOUT_V4_INITIALIZE",
]

# ---------------------------------------------------------------------------
# Log layout constants (mirrors config/new_pool_factories.yaml)
# ---------------------------------------------------------------------------

LAYOUT_V3_POOL_CREATED = "v3_pool_created"
LAYOUT_SLIPSTREAM_POOL_CREATED = "slipstream_pool_created"
LAYOUT_VE33_POOL_CREATED = "ve33_pool_created"
LAYOUT_VE33_PAIR_CREATED = "ve33_pair_created"
LAYOUT_V2_PAIR_CREATED = "v2_pair_created"
LAYOUT_V4_INITIALIZE = "v4_initialize"

_KNOWN_LAYOUTS = frozenset({
    LAYOUT_V3_POOL_CREATED,
    LAYOUT_SLIPSTREAM_POOL_CREATED,
    LAYOUT_VE33_POOL_CREATED,
    LAYOUT_VE33_PAIR_CREATED,
    LAYOUT_V2_PAIR_CREATED,
    LAYOUT_V4_INITIALIZE,
})

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewPoolEvent:
    """A single pool-creation event parsed from a factory log."""

    # Identity
    event_id: str           # deterministic dedupe key: chain:factory:txhash:logindex
    chain: str
    dex: str
    adapter_type: str
    factory: str            # lowercase checksum address
    event_name: str         # "PoolCreated" | "PairCreated"

    # Pool info
    pool: str               # lowercase checksum address (20-byte); OR for V4: 66-char
                            # 0x-prefixed bytes32 PoolId (since V4 has no per-pool contract)
    token0: str             # lowercase checksum address (as emitted by contract)
    token1: str             # lowercase checksum address

    # Fee / tick / stable info (depends on adapter_type)
    fee: Optional[int]          # uint24 fee in parts-per-million (V3 only)
    tick_spacing: Optional[int]  # int24 (Slipstream only)
    stable: Optional[bool]       # bool (ve33 only)

    # Block provenance
    block_number: int
    tx_hash: str            # lowercase 0x-prefixed
    log_index: int

    # V4-specific (default=None for backward compat with non-V4 events)
    hooks: Optional[str] = None  # address (V4 only); None = not set / vanilla (0x0)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FactoryConfig:
    """One entry from config/new_pool_factories.yaml."""

    chain: str
    dex: str
    adapter_type: str
    factory: str            # lowercased on load
    event_name: str
    event_signature: str
    log_layout: str
    topic0: Optional[str]   # None = not yet verified; listener filters by factory addr
    topic0_verified: bool    # True = topic0 confirmed from contract source/ABI; False = computed only
    verification_from_block: Optional[int]
    verification_to_block: Optional[int]
    discovery_only: bool = False  # True = factory is discovery/listener-only; must NOT enter execution path


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "new_pool_factories.yaml"


def load_factory_config(
    path: Optional[Path] = None,
    *,
    chain_filter: Optional[str] = None,
    dex_filter: Optional[str] = None,
) -> List[FactoryConfig]:
    """Load factory configs from YAML.  Returns list of ``FactoryConfig``.

    Parameters
    ----------
    path:
        Path to the YAML file.  Defaults to ``config/new_pool_factories.yaml``.
    chain_filter:
        If provided, only return factories for this chain.
    dex_filter:
        If provided, only return configs for this DEX name.

    Raises
    ------
    FileNotFoundError:
        If the config file does not exist.
    ValueError:
        If the YAML structure is invalid.
    """
    try:
        import yaml  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to load factory config: pip install pyyaml"
        ) from exc

    config_path = path or _DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise FileNotFoundError(f"Factory config not found: {config_path}")

    with open(config_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        raise ValueError(f"Expected a YAML mapping at top level, got {type(raw)}")

    chain = raw.get("chain", "")
    factories_raw = raw.get("factories", [])

    if not isinstance(factories_raw, list):
        raise ValueError("'factories' key must be a list")

    result: List[FactoryConfig] = []
    for entry in factories_raw:
        if not isinstance(entry, dict):
            continue
        entry_chain = entry.get("chain", chain)
        if chain_filter and entry_chain != chain_filter:
            continue
        if dex_filter and entry.get("dex", "") != dex_filter:
            continue

        layout = entry.get("log_layout", "")
        if layout not in _KNOWN_LAYOUTS:
            # Unknown layout — skip with warning (don't crash)
            from core.logging import get_logger
            get_logger(__name__).warning(
                "Unknown log_layout %r for dex=%s; skipping",
                layout,
                entry.get("dex", "?"),
            )
            continue

        topic0_raw = entry.get("topic0")
        result.append(FactoryConfig(
            chain=entry_chain,
            dex=entry.get("dex", ""),
            adapter_type=entry.get("adapter_type", ""),
            factory=entry.get("factory", "").lower(),
            event_name=entry.get("event_name", ""),
            event_signature=entry.get("event_signature", ""),
            log_layout=layout,
            topic0=topic0_raw.lower() if topic0_raw else None,
            topic0_verified=bool(entry.get("topic0_verified", True)),
            verification_from_block=entry.get("verification_from_block"),
            verification_to_block=entry.get("verification_to_block"),
            discovery_only=bool(entry.get("discovery_only", False)),
        ))

    return result


# ---------------------------------------------------------------------------
# Low-level hex helpers (pure, no web3)
# ---------------------------------------------------------------------------


def _strip_0x(s: Any) -> str:
    """Strip 0x prefix; also handles bytes/HexBytes from web3."""
    if isinstance(s, (bytes, bytearray)):
        return s.hex()  # returns lowercase hex WITHOUT 0x prefix
    s = str(s)
    return s[2:] if s.startswith("0x") or s.startswith("0X") else s


def _normalize_raw_log(raw_log: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a web3 AttributeDict log to plain str/int fields.

    web3 v6 returns ``HexBytes`` for ``topics``, ``data``, ``transactionHash``
    and ``address``.  The per-layout parsers expect hex strings.  This function
    converts bytes-like values to ``"0x" + hex`` strings so the parsers work
    regardless of whether the log came from web3 or a plain dict (e.g. tests).
    """
    def _to_hex_str(v: Any) -> Any:
        if isinstance(v, (bytes, bytearray)):
            return "0x" + v.hex()
        return v

    result: Dict[str, Any] = dict(raw_log)
    topics = result.get("topics")
    if isinstance(topics, (list, tuple)):
        result["topics"] = [_to_hex_str(t) for t in topics]
    for key in ("data", "transactionHash", "address"):
        if key in result:
            result[key] = _to_hex_str(result[key])
    return result


def _topic_to_address(topic: str) -> str:
    """Extract 20-byte address from a 32-byte hex topic string."""
    raw = _strip_0x(topic).zfill(64)
    return "0x" + raw[-40:].lower()


def _topic_to_uint(topic: str) -> int:
    """Parse unsigned integer from a 32-byte hex topic."""
    return int(_strip_0x(topic), 16)


def _data_word(data: str, word_index: int) -> str:
    """Return hex string for the N-th 32-byte word in ABI-encoded data (no 0x prefix)."""
    raw = _strip_0x(data)
    start = word_index * 64
    end = start + 64
    if len(raw) < end:
        return "0" * 64
    return raw[start:end]


def _word_to_int24(word_hex: str) -> int:
    """Decode an int24 stored in a 32-byte word (two's complement)."""
    v = int(word_hex, 16)
    # int24 has range -2^23 .. 2^23-1
    if v >= (1 << 23):
        v -= 1 << 24
    return v


def _word_to_bool(word_hex: str) -> bool:
    return bool(int(word_hex, 16))


def _parse_block_number(raw_log: Dict[str, Any]) -> int:
    v = raw_log.get("blockNumber", 0)
    if isinstance(v, str):
        return int(v, 16) if v.startswith(("0x", "0X")) else int(v)
    return int(v or 0)


def _parse_log_index(raw_log: Dict[str, Any]) -> int:
    v = raw_log.get("logIndex", 0)
    if isinstance(v, str):
        return int(v, 16) if v.startswith(("0x", "0X")) else int(v)
    return int(v or 0)


# ---------------------------------------------------------------------------
# Per-layout parsers
# ---------------------------------------------------------------------------


def _parse_v3_pool_created(
    raw_log: Dict[str, Any],
    cfg: FactoryConfig,
) -> Optional[NewPoolEvent]:
    """Parse Uniswap V3 / PancakeSwap V3 PoolCreated event.

    Log structure:
      topics[0]: keccak256("PoolCreated(address,address,uint24,int24,address)")
      topics[1]: token0   (indexed address)
      topics[2]: token1   (indexed address)
      topics[3]: fee      (indexed uint24)
      data:      abi.encode(int24 tickSpacing, address pool)
                 = word0: tickSpacing | word1: pool address
    """
    topics = raw_log.get("topics") or []
    if len(topics) < 4:
        return None

    token0 = _topic_to_address(topics[1])
    token1 = _topic_to_address(topics[2])
    fee = _topic_to_uint(topics[3])

    data = raw_log.get("data", "0x") or "0x"
    # data must have at least 2 words (128 hex chars + optional 0x)
    if len(_strip_0x(data)) < 128:
        return None

    tick_spacing = _word_to_int24(_data_word(data, 0))
    pool = "0x" + _data_word(data, 1)[-40:].lower()

    block_number = _parse_block_number(raw_log)
    tx_hash = (raw_log.get("transactionHash") or "").lower()
    log_index = _parse_log_index(raw_log)

    event_id = make_event_id(cfg.chain, cfg.factory, tx_hash, log_index)
    return NewPoolEvent(
        event_id=event_id,
        chain=cfg.chain,
        dex=cfg.dex,
        adapter_type=cfg.adapter_type,
        factory=cfg.factory,
        event_name=cfg.event_name,
        pool=pool,
        token0=token0,
        token1=token1,
        fee=fee,
        tick_spacing=tick_spacing,
        stable=None,
        block_number=block_number,
        tx_hash=tx_hash,
        log_index=log_index,
    )


def _parse_slipstream_pool_created(
    raw_log: Dict[str, Any],
    cfg: FactoryConfig,
) -> Optional[NewPoolEvent]:
    """Parse Aerodrome Slipstream CL PoolCreated event.

    Log structure:
      topics[0]: keccak256("PoolCreated(address,address,int24,address)")
      topics[1]: token0      (indexed address)
      topics[2]: token1      (indexed address)
      topics[3]: tickSpacing (indexed int24)
      data:      abi.encode(address pool)   = word0: pool address
    """
    topics = raw_log.get("topics") or []
    if len(topics) < 4:
        return None

    token0 = _topic_to_address(topics[1])
    token1 = _topic_to_address(topics[2])
    # tickSpacing stored as uint256 in the topic, interpret as int24
    tick_spacing = _word_to_int24(_strip_0x(topics[3]).zfill(64))

    data = raw_log.get("data", "0x") or "0x"
    if len(_strip_0x(data)) < 64:
        return None

    pool = "0x" + _data_word(data, 0)[-40:].lower()

    block_number = _parse_block_number(raw_log)
    tx_hash = (raw_log.get("transactionHash") or "").lower()
    log_index = _parse_log_index(raw_log)

    event_id = make_event_id(cfg.chain, cfg.factory, tx_hash, log_index)
    return NewPoolEvent(
        event_id=event_id,
        chain=cfg.chain,
        dex=cfg.dex,
        adapter_type=cfg.adapter_type,
        factory=cfg.factory,
        event_name=cfg.event_name,
        pool=pool,
        token0=token0,
        token1=token1,
        fee=None,
        tick_spacing=tick_spacing,
        stable=None,
        block_number=block_number,
        tx_hash=tx_hash,
        log_index=log_index,
    )


def _parse_ve33_pair_created(
    raw_log: Dict[str, Any],
    cfg: FactoryConfig,
) -> Optional[NewPoolEvent]:
    """Parse Aerodrome ve33 / Solidly PairCreated event.

    Log structure:
      topics[0]: keccak256("PairCreated(address,address,bool,address,uint256)")
      topics[1]: token0  (indexed address)
      topics[2]: token1  (indexed address)
      data:      abi.encode(bool stable, address pair, uint256 allPairs)
                 = word0: stable | word1: pair | word2: allPairs
    """
    topics = raw_log.get("topics") or []
    if len(topics) < 3:
        return None

    token0 = _topic_to_address(topics[1])
    token1 = _topic_to_address(topics[2])

    data = raw_log.get("data", "0x") or "0x"
    if len(_strip_0x(data)) < 192:  # need at least 3 words
        return None

    stable = _word_to_bool(_data_word(data, 0))
    pool = "0x" + _data_word(data, 1)[-40:].lower()

    block_number = _parse_block_number(raw_log)
    tx_hash = (raw_log.get("transactionHash") or "").lower()
    log_index = _parse_log_index(raw_log)

    event_id = make_event_id(cfg.chain, cfg.factory, tx_hash, log_index)
    return NewPoolEvent(
        event_id=event_id,
        chain=cfg.chain,
        dex=cfg.dex,
        adapter_type=cfg.adapter_type,
        factory=cfg.factory,
        event_name=cfg.event_name,
        pool=pool,
        token0=token0,
        token1=token1,
        fee=None,
        tick_spacing=None,
        stable=stable,
        block_number=block_number,
        tx_hash=tx_hash,
        log_index=log_index,
    )


def _parse_ve33_pool_created(
    raw_log: Dict[str, Any],
    cfg: FactoryConfig,
) -> Optional[NewPoolEvent]:
    """Parse Aerodrome / Velodrome ve33 PoolCreated event.

    Log structure:
      topics[0]: keccak256("PoolCreated(address,address,bool,address,uint256)")
      topics[1]: token0  (indexed address)
      topics[2]: token1  (indexed address)
      topics[3]: stable  (indexed bool)
      data:      abi.encode(address pool, uint256 allPools)
                 = word0: pool | word1: allPools
    """
    topics = raw_log.get("topics") or []
    if len(topics) < 4:
        return None

    token0 = _topic_to_address(topics[1])
    token1 = _topic_to_address(topics[2])
    stable = bool(_topic_to_uint(topics[3]))

    data = raw_log.get("data", "0x") or "0x"
    if len(_strip_0x(data)) < 128:  # need at least 2 words
        return None

    pool = "0x" + _data_word(data, 0)[-40:].lower()

    block_number = _parse_block_number(raw_log)
    tx_hash = (raw_log.get("transactionHash") or "").lower()
    log_index = _parse_log_index(raw_log)

    event_id = make_event_id(cfg.chain, cfg.factory, tx_hash, log_index)
    return NewPoolEvent(
        event_id=event_id,
        chain=cfg.chain,
        dex=cfg.dex,
        adapter_type=cfg.adapter_type,
        factory=cfg.factory,
        event_name=cfg.event_name,
        pool=pool,
        token0=token0,
        token1=token1,
        fee=None,
        tick_spacing=None,
        stable=stable,
        block_number=block_number,
        tx_hash=tx_hash,
        log_index=log_index,
    )


def _parse_v2_pair_created(
    raw_log: Dict[str, Any],
    cfg: FactoryConfig,
) -> Optional[NewPoolEvent]:
    """Parse Uniswap V2 / SushiSwap V2 / BaseSwap V2 PairCreated event.

    Log structure:
      topics[0]: keccak256("PairCreated(address,address,address,uint256)")
      topics[1]: token0  (indexed address)
      topics[2]: token1  (indexed address)
      data:      abi.encode(address pair, uint256 allPairs)
                 = word0: pair | word1: allPairs
    """
    topics = raw_log.get("topics") or []
    if len(topics) < 3:
        return None

    token0 = _topic_to_address(topics[1])
    token1 = _topic_to_address(topics[2])

    data = raw_log.get("data", "0x") or "0x"
    if len(_strip_0x(data)) < 64:
        return None

    pool = "0x" + _data_word(data, 0)[-40:].lower()

    block_number = _parse_block_number(raw_log)
    tx_hash = (raw_log.get("transactionHash") or "").lower()
    log_index = _parse_log_index(raw_log)

    event_id = make_event_id(cfg.chain, cfg.factory, tx_hash, log_index)
    return NewPoolEvent(
        event_id=event_id,
        chain=cfg.chain,
        dex=cfg.dex,
        adapter_type=cfg.adapter_type,
        factory=cfg.factory,
        event_name=cfg.event_name,
        pool=pool,
        token0=token0,
        token1=token1,
        fee=None,
        tick_spacing=None,
        stable=None,
        block_number=block_number,
        tx_hash=tx_hash,
        log_index=log_index,
    )


def _parse_v4_initialize(
    raw_log: Dict[str, Any],
    cfg: FactoryConfig,
) -> Optional[NewPoolEvent]:
    """Parse Uniswap V4 PoolManager Initialize event.

    Uniswap V4 pools are NOT individual contracts — they live inside the
    PoolManager singleton.  The unique pool identifier is a ``PoolId``
    (bytes32), which is keccak256 of (currency0, currency1, fee, tickSpacing,
    hooks).

    Log structure (PoolManager.sol):
      topics[0]: keccak256("Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)")
      topics[1]: id          (PoolId = bytes32, indexed) — stored as ``pool`` field
      topics[2]: currency0   (address, indexed)
      topics[3]: currency1   (address, indexed)
      data:      abi.encode(uint24 fee, int24 tickSpacing, address hooks,
                            uint160 sqrtPriceX96, int24 tick)
               = word0: fee | word1: tickSpacing | word2: hooks | word3: sqrtPriceX96 | word4: tick

    Note: ``pool`` is stored as the full 32-byte PoolId hex string (66 chars
    with 0x prefix) rather than a 20-byte contract address, since V4 has no
    per-pool contract.

    Source: https://github.com/Uniswap/v4-core (PoolManager.sol)
    topic0: keccak256("Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)")
            = 0xdd466e674ea557f56295e2d0218a125ea4b4f0f6f3307b95f85e6110838d6438
    """
    topics = raw_log.get("topics") or []
    if len(topics) < 4:
        return None

    # topics[1]: PoolId (bytes32) — use as unique pool identifier
    pool_id_raw = _strip_0x(topics[1]).zfill(64)
    pool = "0x" + pool_id_raw

    currency0 = _topic_to_address(topics[2])
    currency1 = _topic_to_address(topics[3])

    data = raw_log.get("data", "0x") or "0x"
    # data must have all 5 words: fee, tickSpacing, hooks, sqrtPriceX96, tick
    # (each word = 32 bytes = 64 hex chars; full Initialize data = 320 hex chars)
    if len(_strip_0x(data)) < 64 * 5:
        return None

    fee = _topic_to_uint(_data_word(data, 0))
    tick_spacing = _word_to_int24(_data_word(data, 1))
    # data word 2: hooks address (20-byte address in 32-byte word)
    hooks = _topic_to_address("0x" + _data_word(data, 2))

    block_number = _parse_block_number(raw_log)
    tx_hash = (raw_log.get("transactionHash") or "").lower()
    log_index = _parse_log_index(raw_log)

    event_id = make_event_id(cfg.chain, cfg.factory, tx_hash, log_index)
    return NewPoolEvent(
        event_id=event_id,
        chain=cfg.chain,
        dex=cfg.dex,
        adapter_type=cfg.adapter_type,
        factory=cfg.factory,
        event_name=cfg.event_name,
        pool=pool,
        token0=currency0,
        token1=currency1,
        fee=fee,
        tick_spacing=tick_spacing,
        stable=None,
        hooks=hooks,
        block_number=block_number,
        tx_hash=tx_hash,
        log_index=log_index,
    )


_LAYOUT_PARSERS = {
    LAYOUT_V3_POOL_CREATED: _parse_v3_pool_created,
    LAYOUT_SLIPSTREAM_POOL_CREATED: _parse_slipstream_pool_created,
    LAYOUT_VE33_POOL_CREATED: _parse_ve33_pool_created,
    LAYOUT_VE33_PAIR_CREATED: _parse_ve33_pair_created,
    LAYOUT_V2_PAIR_CREATED: _parse_v2_pair_created,
    LAYOUT_V4_INITIALIZE: _parse_v4_initialize,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_event_id(chain: str, factory: str, tx_hash: str, log_index: int) -> str:
    """Deterministic dedupe key.  Format: ``chain:factory:txhash:logindex``.

    Inputs are lowercased to prevent case-sensitivity mismatches between
    WS-primary and HTTP-secondary sources.
    """
    return f"{chain.lower()}:{factory.lower()}:{tx_hash.lower()}:{log_index}"


def parse_raw_log(
    raw_log: Dict[str, Any],
    cfg: FactoryConfig,
) -> Optional[NewPoolEvent]:
    """Parse a raw eth log dict into a ``NewPoolEvent`` using the given factory config.

    Returns ``None`` if the log cannot be parsed (wrong structure, short data, etc.).
    The caller is responsible for topic0 filtering before calling this function.

    The function never raises; malformed logs return ``None``.
    """
    try:
        raw_log = _normalize_raw_log(raw_log)
        parser = _LAYOUT_PARSERS.get(cfg.log_layout)
        if parser is None:
            return None
        return parser(raw_log, cfg)
    except Exception:  # noqa: BLE001 — never propagate parse errors
        return None


def dedup_events(events: Sequence[NewPoolEvent]) -> List[NewPoolEvent]:
    """Return a list of events with duplicate ``event_id``s removed.

    Preserves first-seen order.  Duplicates that arise from dual-source
    (WS primary + HTTP secondary) ingestion are expected and harmless.
    """
    seen: set[str] = set()
    result: List[NewPoolEvent] = []
    for ev in events:
        if ev.event_id not in seen:
            seen.add(ev.event_id)
            result.append(ev)
    return result
