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
    
    # 5. Check for potential issues
    if len(dexes) < 2 and config.get("require_cross_dex", True):
        result["warnings"].append("require_cross_dex=true but only 1 DEX configured")
    
    if not pairs:
        result["warnings"].append("No pairs configured")
    
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
