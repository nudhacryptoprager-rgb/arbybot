"""Unified DEX capability registry — single contract for M8/M9 discovery and quote."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

__all__ = [
    "DexCapability",
    "DexCapabilityRegistry",
    "load_dex_capability_registry",
]


@dataclass(frozen=True)
class DexCapability:
    dex_id: str
    adapter_family: str
    registry_status: str
    discovery_method: str
    depth_probe: str
    quote_backend: str
    mirror_support: bool
    enabled: bool = True
    quote_supported: bool = False
    depth_supported: bool = False
    discovery_supported: bool = False
    factory: Optional[str] = None
    config_dex_id: Optional[str] = None
    quarantine_reason: Optional[str] = None
    external_aliases: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dex_id": self.dex_id,
            "adapter_family": self.adapter_family,
            "registry_status": self.registry_status,
            "discovery_method": self.discovery_method,
            "depth_probe": self.depth_probe,
            "quote_backend": self.quote_backend,
            "mirror_support": self.mirror_support,
            "enabled": self.enabled,
            "quote_supported": self.quote_supported,
            "depth_supported": self.depth_supported,
            "discovery_supported": self.discovery_supported,
            "factory": self.factory,
            "config_dex_id": self.config_dex_id,
            "quarantine_reason": self.quarantine_reason,
            "external_aliases": list(self.external_aliases),
        }


class DexCapabilityRegistry:
    """Read-only registry indexed by dex_id and external alias."""

    def __init__(self, capabilities: Iterable[DexCapability]) -> None:
        self._by_id: Dict[str, DexCapability] = {}
        self._alias_index: Dict[str, str] = {}
        for cap in capabilities:
            self._by_id[cap.dex_id] = cap
            for alias in cap.external_aliases:
                self._alias_index[str(alias).lower()] = cap.dex_id

    def get(self, dex_id: str) -> Optional[DexCapability]:
        return self._by_id.get(dex_id) or self._by_id.get(
            self._alias_index.get(str(dex_id).lower(), "")
        )

    def configured(self) -> List[DexCapability]:
        return [
            c
            for c in self._by_id.values()
            if c.enabled and c.registry_status in ("configured", "verified")
        ]

    def all(self) -> List[DexCapability]:
        return list(self._by_id.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": "dex_capability_registry.2",
            "capabilities": [c.to_dict() for c in self.all()],
        }


def _adapter_family(adapter_type: str) -> str:
    mapping = {
        "uniswap_v2": "uniswap_v2",
        "uniswap_v3": "uniswap_v3",
        "algebra": "algebra",
        "iziswap": "iziswap",
        "curve": "curve",
        "balancer_v2": "balancer_v2",
    }
    return mapping.get(adapter_type, adapter_type or "unknown")


def _capability_from_exotic_row(dex_id: str, row: Dict[str, Any]) -> DexCapability:
    adapter = str(row.get("adapter") or row.get("adapter_type") or "unknown")
    enabled = bool(row.get("enabled", True))
    quarantine_reason = str(row.get("quarantine_reason") or "").strip() or None
    quote_backend = str(row.get("quote_backend") or "raw_http")
    quote_supported = enabled and quote_backend not in ("unknown", "none", "")
    depth_supported = enabled and bool(row.get("factory"))
    discovery_supported = enabled and bool(row.get("factory"))
    status = "configured" if enabled and not quarantine_reason else "quarantine"
    return DexCapability(
        dex_id=dex_id,
        adapter_family=_adapter_family(adapter),
        registry_status=status,
        discovery_method="factory_listener" if discovery_supported else "disabled",
        depth_probe="on_chain_reserve" if depth_supported else "unsupported",
        quote_backend=quote_backend,
        mirror_support=enabled and bool(row.get("mirror_support", False)),
        enabled=enabled,
        quote_supported=quote_supported,
        depth_supported=depth_supported,
        discovery_supported=discovery_supported,
        factory=str(row.get("factory") or "") or None,
        config_dex_id=dex_id,
        quarantine_reason=quarantine_reason,
    )


def load_dex_capability_registry(
    *,
    exotic_config_path: str = "config/exotic_base_anchor.yaml",
    candidate_registry_path: str = "config/m8_2_candidate_dex_registry.yaml",
) -> DexCapabilityRegistry:
    caps: Dict[str, DexCapability] = {}

    exotic_path = Path(exotic_config_path)
    if exotic_path.is_file():
        with exotic_path.open(encoding="utf-8") as fh:
            exotic = yaml.safe_load(fh) or {}
        for dex_id, row in (exotic.get("dexes") or {}).items():
            if isinstance(row, dict):
                caps[dex_id] = _capability_from_exotic_row(dex_id, row)

    candidate_path = Path(candidate_registry_path)
    if candidate_path.is_file():
        with candidate_path.open(encoding="utf-8") as fh:
            reg = yaml.safe_load(fh) or {}
        for dex_id, row in (reg.get("candidates") or {}).items():
            if not isinstance(row, dict):
                continue
            cfg_id = str(row.get("config_dex_id") or dex_id)
            base = caps.get(cfg_id)
            if base is not None:
                aliases = tuple(str(a) for a in (row.get("external_aliases") or []))
                caps[dex_id] = (
                    replace(base, external_aliases=aliases) if aliases else base
                )
                continue
            adapter = str(row.get("adapter_type") or "unknown")
            status = str(row.get("registry_status") or "hint_only")
            enabled = status in ("configured", "verified")
            caps[dex_id] = DexCapability(
                dex_id=dex_id,
                adapter_family=_adapter_family(adapter),
                registry_status=status,
                discovery_method="radar_hint" if status != "configured" else "factory_listener",
                depth_probe="unsupported",
                quote_backend="unknown",
                mirror_support=enabled,
                enabled=enabled,
                quote_supported=False,
                depth_supported=False,
                discovery_supported=enabled,
                config_dex_id=cfg_id if cfg_id != dex_id else None,
                quarantine_reason=str(row.get("unsupported_reason") or "") or None,
                external_aliases=tuple(str(a) for a in (row.get("external_aliases") or [])),
            )

    return DexCapabilityRegistry(caps.values())


def export_registry_json(path: str, registry: DexCapabilityRegistry) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(registry.to_dict(), indent=2), encoding="utf-8")
    return str(out)
