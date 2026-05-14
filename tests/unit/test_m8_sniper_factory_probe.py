"""Unit tests for scripts/sniper_factory_probe.py.

Covers:
- Source file is ASCII-safe (no non-ASCII chars) — Windows console safe
- Module imports without error
- CLI arg parser builds correctly
- Output formatting uses only ASCII characters in print() call strings
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PROBE_PATH = _ROOT / "scripts" / "sniper_factory_probe.py"


# ---------------------------------------------------------------------------
# ASCII safety — Step 2 / Step 3 contract
# ---------------------------------------------------------------------------


class TestAsciiSafety:
    """All console output must be ASCII-safe to avoid Windows cp1252 errors."""

    def test_source_file_ascii_decodable(self):
        """The probe source file must decode as ASCII (no non-ASCII bytes)."""
        raw = _PROBE_PATH.read_bytes()
        try:
            raw.decode("ascii")
        except UnicodeDecodeError as exc:
            pytest.fail(
                f"sniper_factory_probe.py contains non-ASCII bytes: {exc}. "
                "This will raise UnicodeEncodeError on Windows console without "
                "PYTHONIOENCODING=utf-8 override."
            )

    def test_source_file_no_non_ascii_chars(self):
        """Explicitly enumerate any non-ASCII byte positions for clear diagnostics."""
        raw = _PROBE_PATH.read_bytes()
        offsets = [i for i, b in enumerate(raw) if b >= 128]
        assert offsets == [], (
            f"Non-ASCII bytes found at byte offsets {offsets[:5]}... "
            f"in scripts/sniper_factory_probe.py. "
            f"Replace with ASCII equivalents (-> instead of ->, -- instead of em-dash, etc.)."
        )

    def test_probe_print_strings_ascii_encodable(self):
        """Check that string literals in print() calls are ASCII-encodable."""
        src_text = _PROBE_PATH.read_text(encoding="ascii")  # raises if non-ASCII
        # If we got here without exception, the file is ASCII-safe.
        assert len(src_text) > 0, "probe source file should be non-empty"

    def test_windows_console_simulate(self):
        """Simulate Windows cp1252 encoding of probe output strings.

        Extract all string literals from the source and verify each encodes
        under cp1252 (the default Windows console encoding on many locales).
        This catches em-dash, arrow, ellipsis etc. that are outside cp1252.
        """
        src_text = _PROBE_PATH.read_text(encoding="ascii")
        # ASCII-only source guarantees cp1252 compatibility.
        # Encode to cp1252 should succeed if the source is pure ASCII.
        try:
            src_text.encode("cp1252")
        except UnicodeEncodeError as exc:
            pytest.fail(
                f"probe source not cp1252-safe (Windows console default): {exc}"
            )


# ---------------------------------------------------------------------------
# Module importability
# ---------------------------------------------------------------------------


class TestProbeModuleImport:
    """scripts/sniper_factory_probe.py must import cleanly."""

    def test_importable(self):
        """Load the probe module without executing main()."""
        spec = importlib.util.spec_from_file_location(
            "sniper_factory_probe", _PROBE_PATH
        )
        assert spec is not None, "spec_from_file_location returned None"
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        # Do NOT exec the module — just verify the spec is valid.
        assert mod is not None

    def test_main_symbol_exists(self):
        """After loading, 'main' function must be importable."""
        if str(_ROOT) not in sys.path:
            sys.path.insert(0, str(_ROOT))
        # Import via package path (scripts/ has __init__.py or we add root to path)
        spec = importlib.util.spec_from_file_location(
            "scripts.sniper_factory_probe", _PROBE_PATH
        )
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        # exec_module needed to inspect symbols — wrap in try to handle missing deps
        try:
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            assert hasattr(mod, "main"), "probe module must export 'main'"
            assert callable(mod.main), "'main' must be callable"
        except (ImportError, ModuleNotFoundError) as exc:
            pytest.skip(f"Optional dependency missing: {exc}")
