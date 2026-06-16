"""Balancer Vault pool indexer — API/subgraph + on-chain verify + quote smoke."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from m8.discovery.specialized_index_rpc import eth_call, selector

_REPO = Path(__file__).resolve().parents[2]
_METADATA = _REPO / "config/adapter_metadata.yaml"
_GET_POOL_TOKENS = "f94d4668"
_BPT_SUFFIX_MARKERS = ("bpt", "linear", "wa")

_UNSUPPORTED_POOL_TYPES = frozenset({"", "unknown"})


def _contract_has_code(rpc_url: str, address: str) -> bool:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_getCode",
            "params": [address, "latest"],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        rpc_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    code = str(body.get("result") or "0x")
    return len(code) > 2


def _registry_balancer_pools(registry_path: Path, chain: str) -> List[Dict[str, Any]]:
    import json

    cfg = load_balancer_config(chain)
    vault = cfg["vault_address"]
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    out: List[Dict[str, Any]] = []
    for tok in (reg.get("tokens") or {}).values():
        for venue in (tok.get("venues") or {}).values():
            if venue.get("dex") != "balancer_vault":
                continue
            pool_addr = str(venue.get("pool") or "").lower()
            if not pool_addr.startswith("0x"):
                continue
            assets = sorted(
                a
                for a in (
                    str(venue.get("token0") or "").lower(),
                    str(venue.get("token1") or "").lower(),
                )
                if a.startswith("0x")
            )
            out.append(
                {
                    "pool_id": "",
                    "pool_address": pool_addr,
                    "pool_kind": "unknown",
                    "assets": assets,
                    "vault_address": vault,
                    "source": "registry_venue",
                }
            )
    return out


def load_balancer_config(chain: str = "base") -> Dict[str, Any]:
    raw = yaml.safe_load(_METADATA.read_text(encoding="utf-8")) or {}
    bal = raw.get("balancer") or {}
    chain_cfg = (bal.get(chain) or {})
    return {
        "vault_address": str(bal.get("vault_address") or "").lower(),
        "graphql_url": str(bal.get("graphql_url") or "https://api-v3.balancer.fi/graphql"),
        "graphql_user_agent": str(bal.get("graphql_user_agent") or "arby-m8-indexer/1.0"),
        "protocol_version_filter": list(bal.get("protocol_version_filter") or [2]),
        "pools": dict(chain_cfg.get("pools") or {}),
        "min_liquidity_usd": float(bal.get("min_liquidity_usd") or 500.0),
        "graphql_first": int(bal.get("graphql_first") or 80),
        "quote_smoke_sender": str(
            bal.get("quote_smoke_sender") or "0x000000000000000000000000000000000000dEaD"
        ).lower(),
        "quote_smoke_recipient": str(
            bal.get("quote_smoke_recipient") or "0x000000000000000000000000000000000000dEaD"
        ).lower(),
        "quote_debug_artifact": str(
            bal.get("quote_debug_artifact") or "data/tmp/m9_balancer_quote_debug_latest.json"
        ),
        "queries_address": str(
            chain_cfg.get("queries_address")
            or bal.get("queries_address")
            or "0xe39b5e3b6d74016b2f6a9673d7493b6df549d5"
        ).lower(),
    }


def _metadata_candidates(chain: str) -> List[Dict[str, Any]]:
    cfg = load_balancer_config(chain)
    vault = cfg["vault_address"]
    out: List[Dict[str, Any]] = []
    for pool_id, meta in cfg["pools"].items():
        if not isinstance(meta, dict):
            continue
        out.append(
            {
                "pool_id": str(pool_id).lower(),
                "pool_address": str(meta.get("pool_address") or pool_id[:42]).lower(),
                "pool_kind": str(meta.get("pool_kind") or "stable"),
                "pool_type": str(meta.get("pool_kind") or "stable"),
                "assets": [str(a).lower() for a in (meta.get("assets") or [])],
                "vault_address": vault,
                "source": "adapter_metadata",
                "create_time": meta.get("create_time"),
            }
        )
    return out


def fetch_graphql_pools(
    *,
    chain: str = "base",
    graphql_url: Optional[str] = None,
    first: int = 80,
    min_liquidity_usd: float = 500.0,
) -> List[Dict[str, Any]]:
    """Fetch pools from Balancer API v3 GraphQL (hint-only until Vault verify)."""
    cfg = load_balancer_config(chain)
    url = graphql_url or cfg["graphql_url"]
    gql_chain = "BASE" if chain == "base" else chain.upper()
    proto = ",".join(str(v) for v in cfg.get("protocol_version_filter") or [2])
    query = (
        "{ poolGetPools(first: %d, where: {chainIn: [%s], minTvl: %s, "
        "protocolVersionIn: [%s]}) "
        "{ id address type createTime poolTokens { address balance } } }"
    ) % (int(first), gql_chain, str(min_liquidity_usd), proto)
    payload = json.dumps({"query": query}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": str(cfg.get("graphql_user_agent") or "arby-m8-indexer/1.0"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, TimeoutError):
        return []
    rows = ((data.get("data") or {}).get("poolGetPools")) or []
    out: List[Dict[str, Any]] = []
    vault = cfg["vault_address"]
    for row in rows:
        if not isinstance(row, dict):
            continue
        pool_id = str(row.get("id") or "").lower()
        if not pool_id.startswith("0x") or len(pool_id) != 66:
            continue
        assets: List[str] = []
        balances: List[int] = []
        for tok in row.get("poolTokens") or []:
            if not isinstance(tok, dict):
                continue
            addr = str(tok.get("address") or "").lower()
            if addr.startswith("0x"):
                assets.append(addr)
                try:
                    balances.append(int(float(tok.get("balance") or 0)))
                except (TypeError, ValueError):
                    balances.append(0)
        if len(assets) < 2:
            continue
        out.append(
            {
                "pool_id": pool_id,
                "pool_address": str(row.get("address") or pool_id[:42]).lower(),
                "pool_kind": str(row.get("type") or "stable").lower(),
                "pool_type": str(row.get("type") or "stable"),
                "assets": [a.lower() for a in assets],
                "balances": balances,
                "vault_address": vault,
                "source": "balancer_graphql",
                "create_time": row.get("createTime"),
            }
        )
    return out


def filter_pools_for_watchlist(
    pools: List[Dict[str, Any]],
    watchlist_tokens: Set[str],
    *,
    connector_tokens: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Keep pools touching watchlist token (and optional connector universe)."""
    if not watchlist_tokens:
        return pools
    universe = set(watchlist_tokens)
    if connector_tokens:
        universe |= connector_tokens
    out: List[Dict[str, Any]] = []
    for pool in pools:
        assets = set(pool.get("assets") or [])
        if assets & watchlist_tokens:
            out.append(pool)
        elif connector_tokens and assets & connector_tokens:
            out.append(pool)
    return out


def _decode_get_pool_tokens(hex_result: str) -> Tuple[List[str], List[int]]:
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    words = [raw[i : i + 64] for i in range(0, len(raw), 64)]

    def _read_array(head_word_idx: int) -> List[str]:
        offset_bytes = int(words[head_word_idx], 16)
        base = offset_bytes // 32
        length = int(words[base], 16)
        return [words[base + 1 + k] for k in range(length)]

    token_words = _read_array(0)
    balance_words = _read_array(1)
    tokens = ["0x" + w[24:].lower() for w in token_words]
    balances = [int(w, 16) for w in balance_words]
    return tokens, balances


def verify_vault_pool(
    rpc_url: str,
    pool: Dict[str, Any],
    *,
    focus_tokens: Optional[Set[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Vault.getPoolTokens verify; optional focus token membership check."""
    pool_id = str(pool.get("pool_id") or "").lower()
    vault = str(pool.get("vault_address") or "").lower()
    if not pool_id or len(pool_id) != 66 or not vault:
        return None, "BALANCER_INVALID_POOL_ID"
    pool_type = str(pool.get("pool_type") or pool.get("pool_kind") or "").lower()
    if pool_type in _UNSUPPORTED_POOL_TYPES:
        return None, "BALANCER_POOL_TYPE_UNSUPPORTED"
    calldata = "0x" + _GET_POOL_TOKENS + pool_id[2:]
    try:
        result = eth_call(rpc_url, vault, calldata)
        tokens, balances = _decode_get_pool_tokens(result)
    except Exception:
        return None, "BALANCER_VAULT_CALL_FAILED"
    if len(tokens) < 2:
        return None, "BALANCER_TOKEN_MISMATCH"
    if focus_tokens and not (set(tokens) & focus_tokens):
        return None, "BALANCER_FOCUS_TOKEN_MISSING"
    if all(b <= 0 for b in balances):
        return None, "BALANCER_ZERO_BALANCES"
    assets = [t.lower() for t in tokens]
    verified = {
        **pool,
        "pool_id": pool_id,
        "pool_address": str(pool.get("pool_address") or pool_id[:42]).lower(),
        "vault_address": vault,
        "assets": assets,
        "balances": balances,
        "tokens_list": assets,
        "factory_verified": True,
        "verify_method": "vault_getPoolTokens",
    }
    return verified, "OK"


_DECIMALS_SEL = "313ce567"


def _token_decimals(rpc_url: str, token: str) -> int:
    try:
        raw = eth_call(rpc_url, token.lower(), "0x" + _DECIMALS_SEL)
        return int(raw, 16)
    except Exception:
        return 18


def _smoke_amounts_for_token(
    *,
    decimals: int,
    balance: int,
) -> List[int]:
    base = max(1, 10 ** max(decimals - 4, 0))
    candidates = [
        base,
        max(1, 10 ** max(decimals - 2, 0)),
        max(1, balance // 1_000),
        max(1, balance // 100),
    ]
    out: List[int] = []
    seen: Set[int] = set()
    for amt in candidates:
        if amt <= 0 or amt > balance or amt in seen:
            continue
        seen.add(amt)
        out.append(amt)
    return out or [1]


def _append_quote_debug(
    debug_rows: Optional[List[Dict[str, Any]]],
    row: Dict[str, Any],
) -> None:
    if debug_rows is not None:
        debug_rows.append(row)


def quote_smoke_balancer(
    rpc_url: str,
    pool: Dict[str, Any],
    *,
    debug_rows: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """Micro quote via Vault queryBatchSwap — all asset pairs, balance-aware."""
    import hashlib

    from dex.adapters.balancer_vault import _decode_query_batch_swap, _encode_query_batch_swap

    cfg = load_balancer_config()
    assets = [str(a).lower() for a in (pool.get("assets") or [])]
    balances = list(pool.get("balances") or [])
    if len(balances) < len(assets):
        balances = balances + [0] * (len(assets) - len(balances))
    pool_id = str(pool.get("pool_id") or "")
    if len(assets) < 2 or not pool_id:
        return "BALANCER_TOKEN_MISMATCH", "fail"
    vault = str(pool.get("vault_address") or cfg["vault_address"])
    sender = cfg["quote_smoke_sender"]
    recipient = cfg["quote_smoke_recipient"]
    last_debug: Dict[str, Any] = {}

    for i, token_in in enumerate(assets):
        if any(m in token_in for m in _BPT_SUFFIX_MARKERS):
            continue
        bal_in = int(balances[i]) if i < len(balances) else 0
        if bal_in <= 0:
            continue
        dec_in = _token_decimals(rpc_url, token_in)
        for j, token_out in enumerate(assets):
            if i == j or any(m in token_out for m in _BPT_SUFFIX_MARKERS):
                continue
            bal_out = int(balances[j]) if j < len(balances) else 0
            if bal_out <= 0:
                continue
            dec_out = _token_decimals(rpc_url, token_out)
            for amount_in in _smoke_amounts_for_token(decimals=dec_in, balance=bal_in):
                try:
                    data = _encode_query_batch_swap(
                        pool_id,
                        token_in,
                        token_out,
                        amount_in=amount_in,
                        sender=sender,
                        recipient=recipient,
                        all_assets=assets,
                    )
                    hex_data = "0x" + data.hex()
                    queries_addr = cfg.get("queries_address") or ""
                    targets: List[Tuple[str, str]] = []
                    if queries_addr and _contract_has_code(rpc_url, queries_addr):
                        targets.append(("balancer_queries", queries_addr))
                    if not targets:
                        targets.append(("vault", vault))
                    for contour, target in targets:
                        try:
                            result = eth_call(rpc_url, target, hex_data)
                            assets_lc = [str(a).lower() for a in assets]
                            asset_in_index = assets_lc.index(token_in.lower())
                            asset_out_index = assets_lc.index(token_out.lower())
                            _delta_in, delta_out = _decode_query_batch_swap(
                                result,
                                asset_in_index=asset_in_index,
                                asset_out_index=asset_out_index,
                            )
                            if abs(delta_out) > 0:
                                _append_quote_debug(
                                    debug_rows,
                                    {
                                        "status": "QUOTE_OK_BALANCER",
                                        "quote_contour": contour,
                                        "pool_id": pool_id,
                                        "pool_type": pool.get("pool_kind"),
                                        "assets": assets,
                                        "token_in": token_in,
                                        "token_out": token_out,
                                        "amount_in": amount_in,
                                        "decimals_in": dec_in,
                                        "decimals_out": dec_out,
                                        "calldata_hash": hashlib.sha256(
                                            hex_data.encode()
                                        ).hexdigest()[:16],
                                    },
                                )
                                return "QUOTE_OK_BALANCER", "ok"
                        except Exception as inner_exc:
                            err = inner_exc if isinstance(inner_exc, dict) else str(inner_exc)
                            last_debug = {
                                "status": "BALANCER_QUOTE_REVERT",
                                "quote_contour": contour,
                                "pool_id": pool_id,
                                "pool_type": pool.get("pool_kind"),
                                "assets": assets,
                                "token_in": token_in,
                                "token_out": token_out,
                                "amount_in": amount_in,
                                "decimals_in": dec_in,
                                "decimals_out": dec_out,
                                "raw_error": err,
                            }
                            continue
                    if last_debug:
                        continue
                    last_debug = {
                        "status": "BALANCER_ZERO_OUT",
                        "pool_id": pool_id,
                        "token_in": token_in,
                        "token_out": token_out,
                        "amount_in": amount_in,
                        "decimals_in": dec_in,
                        "decimals_out": dec_out,
                    }
                except Exception as exc:
                    err = exc if isinstance(exc, dict) else str(exc)
                    last_debug = {
                        "status": "BALANCER_QUOTE_REVERT",
                        "pool_id": pool_id,
                        "token_in": token_in,
                        "token_out": token_out,
                        "amount_in": amount_in,
                        "decimals_in": dec_in,
                        "decimals_out": dec_out,
                        "raw_error": err,
                        "calldata_hash": hashlib.sha256(
                            ("0x" + _encode_query_batch_swap(
                                pool_id,
                                token_in,
                                token_out,
                                amount_in=amount_in,
                                sender=sender,
                                recipient=recipient,
                                all_assets=assets,
                            ).hex()).encode()
                        ).hexdigest()[:16]
                        if pool_id
                        else "",
                    }
    if last_debug:
        _append_quote_debug(debug_rows, last_debug)
    return "BALANCER_QUOTE_REVERT", "fail"


def synthesize_token_presence_routes(pool: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Virtual T-C edges for multi-token Balancer pools."""
    assets = list(pool.get("assets") or [])
    pool_id = str(pool.get("pool_id") or "")
    if len(assets) < 2:
        return []
    routes: List[Dict[str, Any]] = []
    probe = str(pool.get("probe_status") or "")
    for i, focus in enumerate(assets):
        for j, conn in enumerate(assets):
            if i == j:
                continue
            conn_l = str(conn).lower()
            if any(m in conn_l for m in _BPT_SUFFIX_MARKERS):
                continue
            routes.append(
                {
                    "dex_id": "balancer_vault",
                    "pool_address": pool.get("pool_address"),
                    "pool_id": pool_id,
                    "vault_address": pool.get("vault_address"),
                    "pool_kind": pool.get("pool_kind"),
                    "token0_addr": focus,
                    "token1_addr": conn,
                    "connector_addr": conn,
                    "connector_token": conn[:10],
                    "expansion_route_kind": "token_presence",
                    "quote_smoke_status": probe,
                    "resolve_source": "balancer_pool_index",
                }
            )
    return routes


def build_balancer_index(
    *,
    chain: str,
    rpc_url: str,
    watchlist_tokens: Set[str],
    connector_tokens: Optional[Set[str]] = None,
    registry_path: Optional[Path] = None,
    use_graphql: bool = True,
    verify_vault: bool = True,
    quote_smoke: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Build verified Balancer pool index entries."""
    cfg = load_balancer_config(chain)
    metrics: Dict[str, int] = {
        "discovered": 0,
        "verified": 0,
        "quoteable": 0,
        "rejected": 0,
    }
    meta_rows = _metadata_candidates(chain)
    graphql_rows = fetch_graphql_pools(chain=chain) if use_graphql else []
    registry_rows: List[Dict[str, Any]] = []
    if registry_path and registry_path.exists():
        registry_rows = _registry_balancer_pools(registry_path, chain)

    focus = watchlist_tokens | (connector_tokens or set())
    if watchlist_tokens:
        graphql_rows = filter_pools_for_watchlist(
            graphql_rows, watchlist_tokens, connector_tokens=connector_tokens
        )
        registry_rows = filter_pools_for_watchlist(
            registry_rows, watchlist_tokens, connector_tokens=connector_tokens
        )

    candidates: List[Dict[str, Any]] = meta_rows + graphql_rows + registry_rows

    seen: Set[str] = set()
    deduped: List[Dict[str, Any]] = []
    for cand in candidates:
        pid = str(cand.get("pool_id") or "").lower()
        paddr = str(cand.get("pool_address") or "").lower()
        key = pid if pid.startswith("0x") and len(pid) == 66 else paddr
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(cand)
    metrics["discovered"] = len(deduped)
    filtered = deduped

    quote_debug_rows: List[Dict[str, Any]] = []
    verified: List[Dict[str, Any]] = []
    for cand in filtered:
        if not verify_vault:
            verified.append({**cand, "probe_status": "QUOTE_OK_VAULT_SKIPPED"})
            metrics["verified"] += 1
            continue
        focus_verify = None if cand.get("source") == "adapter_metadata" else (focus or None)
        row, reason = verify_vault_pool(
            rpc_url, cand, focus_tokens=focus_verify
        )
        if not row:
            metrics["rejected"] += 1
            continue
        verify_probe = "QUOTE_OK_VAULT_VERIFY"
        quote_probe = verify_probe
        if quote_smoke:
            quote_probe, ok = quote_smoke_balancer(
                rpc_url, row, debug_rows=quote_debug_rows
            )
            if ok == "ok":
                metrics["quoteable"] += 1
        row["probe_status"] = verify_probe
        row["quote_smoke_status"] = quote_probe
        verified.append(row)
        metrics["verified"] += 1
    if quote_smoke:
        metrics["quote_debug_rows"] = len(quote_debug_rows)
        dbg_path = Path(cfg.get("quote_debug_artifact", ""))
        if str(dbg_path):
            dbg_path.parent.mkdir(parents=True, exist_ok=True)
            payload = quote_debug_rows or [
                {
                    "status": "BALANCER_QUOTE_NO_ATTEMPTS",
                    "verified_pools": len(verified),
                }
            ]
            dbg_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return verified, metrics
