#!/usr/bin/env python3
# PATH: scripts/validate_universe.py
"""
Validate Universe - dry-run validation of config pairs/pools.

Checks that:
- All tokens in config are in core_tokens.yaml
- All DEXes in config are in dexes.yaml
- Pool addresses can be resolved (if specified)
- Chain configuration is valid

Usage:
    py -3.11 scripts/validate_universe.py --config config/real_minimal.yaml
    py -3.11 scripts/validate_universe.py --config config/real_scan_linea_smoke.yaml --json

Exit codes:
  0 = PASS (all validations pass)
  1 = FAIL (validation errors found)
  2 = ERROR (config not found or invalid)

v3.2.9: Initial implementation for multi-chain readiness.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).parent.parent


def load_yaml(path: Path) -> dict:
    """Load YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def validate_universe(config_path: Path) -> dict:
    """
    Validate a config's universe against registry files.
    
    Returns dict with validation results.
    """
    result = {
        "config_path": str(config_path),
        "status": "PASS",
        "errors": [],
        "warnings": [],
        "summary": {},
    }
    
    # Load config
    try:
        config = load_yaml(config_path)
    except Exception as e:
        result["status"] = "ERROR"
        result["errors"].append(f"Failed to load config: {e}")
        return result
    
    # Load registry files
    try:
        chains_config = load_yaml(PROJECT_ROOT / "config" / "chains.yaml")
        dexes_config = load_yaml(PROJECT_ROOT / "config" / "dexes.yaml")
        tokens_config = load_yaml(PROJECT_ROOT / "config" / "core_tokens.yaml")
    except Exception as e:
        result["status"] = "ERROR"
        result["errors"].append(f"Failed to load registry: {e}")
        return result
    
    # Extract config values
    chain_key = config.get("chain", "unknown")
    chain_id = config.get("chain_id", 0)
    dexes = config.get("dexes", [])
    pairs = config.get("pairs", [])
    
    result["summary"]["chain_key"] = chain_key
    result["summary"]["chain_id"] = chain_id
    result["summary"]["dexes_count"] = len(dexes)
    result["summary"]["pairs_count"] = len(pairs)
    
    # 1. Validate chain
    if chain_key not in chains_config:
        result["errors"].append(f"Chain '{chain_key}' not in chains.yaml")
    else:
        chain_def = chains_config[chain_key]
        expected_chain_id = chain_def.get("chain_id", 0)
        if chain_id != expected_chain_id:
            result["errors"].append(
                f"chain_id mismatch: config={chain_id}, chains.yaml={expected_chain_id}"
            )
        result["summary"]["chain_name"] = chain_def.get("name", "Unknown")
    
    # 2. Validate DEXes
    chain_dexes = dexes_config.get(chain_key, {})
    for dex in dexes:
        if dex not in chain_dexes:
            result["errors"].append(f"DEX '{dex}' not in dexes.yaml for chain '{chain_key}'")
        else:
            dex_def = chain_dexes[dex]
            # Check essential fields
            if not dex_def.get("factory"):
                result["warnings"].append(f"DEX '{dex}' missing factory address")
            adapter_type = dex_def.get("adapter_type", "unknown")
            result["summary"].setdefault("dex_adapters", {})[dex] = adapter_type
            
            # v3.2.19: Validate required anchors per adapter_type for executable quotes
            # Different adapters require different contract addresses to produce quotes
            missing_anchors = []
            if adapter_type == "uniswap_v3":
                # V3 requires factory (pool lookup) + quoter_v2 (executable quotes)
                if not dex_def.get("factory"):
                    missing_anchors.append("factory")
                if not dex_def.get("quoter_v2"):
                    missing_anchors.append("quoter_v2")
            elif adapter_type == "algebra":
                # Algebra requires factory + quoter for dynamic-fee pools
                if not dex_def.get("factory"):
                    missing_anchors.append("factory")
                if not dex_def.get("quoter"):
                    missing_anchors.append("quoter (Algebra needs quoter for executable quotes)")
            elif adapter_type in ("ve33", "uniswap_v2", "solidly"):
                # V2/ve33 requires router for swaps
                if not dex_def.get("router"):
                    missing_anchors.append("router")
            
            if missing_anchors:
                result["warnings"].append(
                    f"DEX '{dex}' ({adapter_type}) missing anchors: {', '.join(missing_anchors)}"
                )
    
    # 3. Validate tokens
    chain_tokens = tokens_config.get(chain_key, {})
    unique_tokens = set()
    for pair in pairs:
        if isinstance(pair, dict):
            token_in = pair.get("token_in")
            token_out = pair.get("token_out")
            if token_in:
                unique_tokens.add(token_in)
            if token_out:
                unique_tokens.add(token_out)
    
    result["summary"]["unique_tokens"] = list(sorted(unique_tokens))
    
    for token in unique_tokens:
        if token not in chain_tokens:
            result["errors"].append(
                f"Token '{token}' not in core_tokens.yaml for chain '{chain_key}'"
            )
        else:
            token_def = chain_tokens[token]
            if not token_def.get("address"):
                result["warnings"].append(f"Token '{token}' missing address")
    
    # 4. Validate pairs structure
    unique_pairs = set()
    for pair in pairs:
        if isinstance(pair, dict):
            token_in = pair.get("token_in", "")
            token_out = pair.get("token_out", "")
            if token_in and token_out:
                unique_pairs.add(f"{token_in}/{token_out}")
    
    result["summary"]["unique_pairs"] = list(sorted(unique_pairs))
    result["summary"]["unique_pairs_count"] = len(unique_pairs)
    
    # v3.2.18: Check for non-canonical keys (config contract violations)
    non_canonical_keys = []
    if "run_kind_hint" in config:
        non_canonical_keys.append(("run_kind_hint", "run_kind", "determines rolling policy"))
    if "max_pairs" in config:
        non_canonical_keys.append(("max_pairs", "discovery_runtime_max_pairs", "discovery contract"))
    if "max_deviation_bps" in config:
        non_canonical_keys.append(("max_deviation_bps", "price_sanity_max_deviation_bps", "price sanity contract"))
    
    for old_key, canonical_key, reason in non_canonical_keys:
        result["warnings"].append(
            f"NON_CANONICAL_KEY: '{old_key}' should be '{canonical_key}' ({reason})"
        )
    
    # v3.2.18: Check universe_source=discovery_runtime
    universe_source = config.get("universe_source", "config")
    result["summary"]["universe_source"] = universe_source
    is_discovery_runtime = (universe_source == "discovery_runtime")
    
    # R27.3: Forbid intent/intent_forced for NORMAL/COVERAGE runs.
    # intent paths skip on-chain verification and violate the "dynamic + verify" contract.
    if universe_source in ("intent", "intent_forced") and is_strict_run:
        result["errors"].append(
            f"VIABILITY_FAIL: universe_source='{universe_source}' is forbidden for "
            f"run_kind={run_kind}. Intent-based universes lack on-chain verification. "
            "Use 'config' or 'discovery_runtime' for NORMAL/COVERAGE runs."
        )
    
    # v3.2.18: Check explicit run_kind for strict runs (no defaulting)
    has_explicit_run_kind = ("run_kind" in config)
    run_kind = config.get("run_kind", "NORMAL")
    result["summary"]["run_kind"] = run_kind
    result["summary"]["has_explicit_run_kind"] = has_explicit_run_kind
    
    # 5. Check for potential issues
    # v3.2.12: run_kind-aware viability gating
    # - NORMAL/COVERAGE runs: FAIL on misconfig (prevents NO_DATA/LOW_SAMPLE)
    # - SMOKE/other: WARN only (allow special test configs)
    strict_run_kinds = ("NORMAL", "COVERAGE")
    is_strict_run = (run_kind in strict_run_kinds)
    
    # v3.2.13: chain validation - FAIL if chain missing/unknown for strict runs
    # This prevents CHAIN_KEY_UNKNOWN warning and legacy cache path usage
    if chain_key in (None, "", "unknown"):
        if is_strict_run:
            result["errors"].append(
                "VIABILITY_FAIL: 'chain' field missing or unknown in config - "
                "required for chain-scoped cache isolation"
            )
        else:
            result["warnings"].append(
                f"'chain' field missing/unknown (run_kind={run_kind})"
            )
    
    # v3.2.11 FIX: require_cross_dex=true with <2 DEX
    # Cross-DEX arbitrage requires at least 2 DEXes to function
    if len(dexes) < 2 and config.get("require_cross_dex", True):
        if is_strict_run:
            result["errors"].append(
                "VIABILITY_FAIL: require_cross_dex=true but <2 DEXes configured - "
                "cross-DEX arbitrage not possible"
            )
        else:
            result["warnings"].append(
                f"require_cross_dex=true but <2 DEXes (run_kind={run_kind}, allowed as warning)"
            )
    
    # v3.2.18: For discovery_runtime, validate max_pairs instead of pairs
    if is_discovery_runtime:
        discovery_max_pairs = config.get("discovery_runtime_max_pairs", 0)
        result["summary"]["discovery_runtime_max_pairs"] = discovery_max_pairs
        
        if discovery_max_pairs <= 0 and is_strict_run:
            result["errors"].append(
                "VIABILITY_FAIL: universe_source=discovery_runtime but "
                "discovery_runtime_max_pairs not set or <=0"
            )
        
        # For discovery_runtime, pairs from config are not used, so skip pairs check
        # But still require explicit run_kind
        if not has_explicit_run_kind and is_strict_run:
            result["errors"].append(
                "VIABILITY_FAIL: discovery_runtime config missing explicit 'run_kind' - "
                "required for rolling policy enforcement"
            )
    else:
        # v3.2.11: pairs_count==0 is a FAIL for strict runs (misconfig)
        if not pairs:
            if is_strict_run:
                result["errors"].append(
                    "VIABILITY_FAIL: no pairs configured - cannot generate quotes"
                )
            else:
                result["warnings"].append(f"No pairs configured (run_kind={run_kind})")
    
    # v3.2.10: Check for pool resolution capability (NO_QUOTES prevention)
    # If pairs_count > 0 but dexes is empty, quotes can't be fetched
    if len(pairs) > 0 and len(dexes) == 0:
        result["warnings"].append(
            "POOL_RESOLUTION_UNLIKELY: pairs configured but no DEXes - expect NO_QUOTES"
        )
    
    # Check if any pair has explicit pool address (alternative to DEX discovery)
    explicit_pools = []
    for pair in pairs:
        if isinstance(pair, dict):
            pool_addr = pair.get("pool_address") or pair.get("pool")
            if pool_addr:
                explicit_pools.append(pool_addr)
    
    if len(pairs) > 0 and len(dexes) == 0 and not explicit_pools:
        result["warnings"].append(
            "NO_POOL_MAPPING: no DEXes and no explicit pool_address in pairs - "
            "quotes will fail with POOL_MISSING"
        )
    
    # Check run_kind for rolling-related warnings
    if run_kind == "SMOKE":
        result["warnings"].append(
            "run_kind=SMOKE: this run will NOT update rolling artifacts (NORM-only policy)"
        )
    
    # R27.3: Strategy mode encoding — warn when same-DEX fallback is active for NORMAL
    require_cross_dex = config.get("require_cross_dex", True)
    result["summary"]["require_cross_dex"] = require_cross_dex
    result["summary"]["same_dex_only"] = not require_cross_dex
    if not require_cross_dex and is_strict_run:
        result["warnings"].append(
            "SAME_DEX_MODE: require_cross_dex=false — signals are fee-tier arbitrage, "
            "not cross-DEX. Ensure this is intentional for NORMAL runs."
        )
    
    # Finalize status
    if result["errors"]:
        result["status"] = "FAIL"
    
    return result


def print_summary(result: dict, as_json: bool = False):
    """Print validation summary."""
    if as_json:
        print(json.dumps(result, indent=2))
        return
    
    print("=" * 60)
    print(f"Universe Validation: {result['config_path']}")
    print("=" * 60)
    
    summary = result.get("summary", {})
    
    print(f"\nCHAIN:")
    print(f"  chain_key: {summary.get('chain_key', 'N/A')}")
    print(f"  chain_id: {summary.get('chain_id', 0)}")
    print(f"  chain_name: {summary.get('chain_name', 'N/A')}")
    print(f"  run_kind: {summary.get('run_kind', 'NORMAL')}")
    
    print(f"\nDEXes ({summary.get('dexes_count', 0)}):")
    for dex, adapter in summary.get("dex_adapters", {}).items():
        print(f"  - {dex} ({adapter})")
    
    print(f"\nTOKENS ({len(summary.get('unique_tokens', []))}):")
    for token in summary.get("unique_tokens", []):
        print(f"  - {token}")
    
    print(f"\nPAIRS ({summary.get('unique_pairs_count', 0)}):")
    for pair in summary.get("unique_pairs", []):
        print(f"  - {pair}")
    
    # Errors
    if result["errors"]:
        print(f"\nERRORS ({len(result['errors'])}):")
        for err in result["errors"]:
            print(f"  [X] {err}")
    
    # Warnings
    if result["warnings"]:
        print(f"\nWARNINGS ({len(result['warnings'])}):")
        for warn in result["warnings"]:
            print(f"  [!] {warn}")
    
    print(f"\nSTATUS: {result['status']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Validate config universe")
    parser.add_argument("--config", required=True, help="Path to config YAML")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    
    if not config_path.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(2)
    
    result = validate_universe(config_path)
    print_summary(result, as_json=args.json)
    
    if result["status"] == "FAIL":
        sys.exit(1)
    elif result["status"] == "ERROR":
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
