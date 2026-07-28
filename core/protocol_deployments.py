"""Load chain-scoped protocol deployments and anchor policy from config."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

_DEFAULT_PATH = Path("config/protocol_deployments.yaml")


def load_protocol_deployments(
    path: str | Path = _DEFAULT_PATH,
) -> Dict[str, Any]:
    cfg_path = Path(path)
    if not cfg_path.is_file():
        return {}
    try:
        import yaml

        with cfg_path.open(encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return dict(raw) if isinstance(raw, dict) else {}
    except Exception:
        return {}


def chain_deployments(
    chain: str = "base",
    *,
    path: str | Path = _DEFAULT_PATH,
) -> Dict[str, Any]:
    doc = load_protocol_deployments(path)
    chains = doc.get("chains") or {}
    entry = chains.get(chain) or {}
    return dict(entry) if isinstance(entry, dict) else {}


def anchor_addr_to_symbol(
    chain: str = "base",
    *,
    path: str | Path = _DEFAULT_PATH,
) -> Dict[str, str]:
    entry = chain_deployments(chain, path=path)
    anchors = entry.get("anchor_tokens") or {}
    out: Dict[str, str] = {}
    for addr, sym in anchors.items():
        out[str(addr).lower()] = str(sym)
    return out


def protocol_address(
    name: str,
    *,
    chain: str = "base",
    path: str | Path = _DEFAULT_PATH,
) -> Optional[str]:
    entry = chain_deployments(chain, path=path)
    protocols = entry.get("protocols") or {}
    val = protocols.get(name)
    return str(val) if val else None
