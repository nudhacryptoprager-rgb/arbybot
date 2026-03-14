# PATH: tests/unit/test_suspect_provenance.py
"""
Regression tests for suspect-metric provenance.

Ensures suspect_examples and raw_bps come ONLY from real rejected quotes,
not from synthetic fabrication (the removed _compute_sanity_rejects path).
"""

import ast
from pathlib import Path

from strategy.jobs.run_scan_real import _extract_suspect_from_rejects


# ---------------------------------------------------------------------------
# Unit tests for _extract_suspect_from_rejects
# ---------------------------------------------------------------------------

def test_extract_empty_rejects():
    """No rejects → no suspect examples, raw_bps=0."""
    examples, raw_bps = _extract_suspect_from_rejects([])
    assert examples == []
    assert raw_bps == 0


def test_extract_single_reject():
    """Single reject produces one suspect example with correct fields."""
    reject = {
        "pair": "WETH/USDC",
        "price_exact": "2500.0",
        "anchor_price": "2600.0",
        "reason": "PRICE_SANITY_FAILED",
        "deviation_bps": 385,
    }
    examples, raw_bps = _extract_suspect_from_rejects([reject])

    assert len(examples) == 1
    assert examples[0]["pair"] == "WETH/USDC"
    assert examples[0]["implied_price"] == "2500.0"
    assert examples[0]["expected_price"] == "2600.0"
    assert examples[0]["reason"] == "PRICE_SANITY_FAILED"
    assert raw_bps == 385


def test_extract_picks_max_deviation():
    """raw_bps is the maximum deviation across all rejects."""
    rejects = [
        {"pair": "A/B", "deviation_bps": 100, "reason": "QUOTE_ZERO_OUT"},
        {"pair": "C/D", "deviation_bps": 500, "reason": "PRICE_SANITY_FAILED"},
        {"pair": "E/F", "deviation_bps": 200, "reason": "NO_ONCHAIN_PRICE"},
    ]
    examples, raw_bps = _extract_suspect_from_rejects(rejects)

    assert len(examples) == 3
    assert raw_bps == 500


def test_extract_handles_none_deviation():
    """Reject with deviation_bps=None doesn't crash."""
    reject = {"pair": "X/Y", "deviation_bps": None, "reason": "PRICE_CALC_FAILED"}
    examples, raw_bps = _extract_suspect_from_rejects([reject])

    assert len(examples) == 1
    assert raw_bps == 0


# ---------------------------------------------------------------------------
# Purity / contract tests
# ---------------------------------------------------------------------------

def test_no_synthetic_sanity_function():
    """run_scan_real.py must NOT contain _compute_sanity_rejects (removed)."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    content = path.read_text(encoding="utf-8")

    assert "_compute_sanity_rejects" not in content, (
        "Synthetic suspect generation (_compute_sanity_rejects) must be removed. "
        "Suspect metrics must come from real rejected_quotes only."
    )


def test_extract_suspect_from_rejects_exists():
    """The real-data extraction function must exist in run_scan_real."""
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    func_names = {
        node.name for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    }
    assert "_extract_suspect_from_rejects" in func_names


def test_no_hardcoded_way_below_expected_default():
    """Stats must not inject synthetic 'way_below_expected' count from nowhere.

    Previous code had: reasons.setdefault("way_below_expected", 0)
    This inserted a synthetic reason key even when no real rejects existed.
    """
    path = Path(__file__).parent.parent.parent / "strategy" / "jobs" / "run_scan_real.py"
    content = path.read_text(encoding="utf-8")

    assert 'setdefault("way_below_expected"' not in content, (
        "Suspect reasons must only contain entries from real rejects. "
        "Do not inject synthetic keys like 'way_below_expected'."
    )
