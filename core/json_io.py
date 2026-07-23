# PATH: core/json_io.py
"""Atomic JSON I/O utilities.

Provides safe atomic file writing to prevent partial/corrupt artifacts.
Uses tempfile + os.replace pattern for crash-safe writes.

v3.2.7: Initial implementation for rolling artifact consistency.
"""

from __future__ import annotations

import json
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional, Union


def _default_serializer(obj: Any) -> Any:
    """Default JSON serializer for non-standard types."""
    if isinstance(obj, Decimal):
        return float(obj)
    if hasattr(obj, "isoformat"):  # datetime-like
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


def _exact_decimal_serializer(obj: Any) -> Any:
    """Money-safe serializer: Decimal is emitted as an exact string.

    Canonical money artifacts (amounts, PnL, gas, slippage) must not lose
    precision through binary float conversion (Roadmap В§3.2: no float
    money).  ``Decimal`` values serialize as exact decimal strings; large
    wei integers already serialize exactly via JSON int.  Float telemetry
    stays allowed only in UI-facing payloads, never in canonical money
    artifacts вЂ” those must use this mode.
    """
    if isinstance(obj, Decimal):
        # Fixed-point notation: exact and free of scientific-notation
        # surprises for consumers ("0.000000000000000001", not "1E-18").
        return format(obj, "f")
    if hasattr(obj, "isoformat"):  # datetime-like
        return obj.isoformat()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return str(obj)


DECIMAL_MODES = frozenset({"float", "str"})


def atomic_write_json(
    path: Union[str, Path],
    data: Any,
    indent: int = 2,
    default: Optional[Callable[[Any], Any]] = None,
    ensure_ascii: bool = False,
    decimal_mode: str = "float",
) -> Path:
    """
    Write JSON data atomically using tempfile + os.replace.

    This ensures that:
    1. The file is never partially written
    2. Concurrent readers always see complete data
    3. Interruptions (crash, Ctrl+C) leave no corrupt files

    The atomic write pattern:
    1. Write to a temp file in the same directory
    2. Flush and sync to disk
    3. os.replace() atomically replaces the target file

    Args:
        path: Target file path (will be created/replaced atomically)
        data: Data to serialize to JSON
        indent: JSON indentation (default: 2)
        default: Custom serializer for non-JSON types (default: _default_serializer)
        ensure_ascii: If True, escape non-ASCII characters (default: False)
        decimal_mode: ``"float"`` (legacy: Decimal -> float) or ``"str"``
            (money-safe: Decimal -> exact string).  Use ``"str"`` for
            canonical money artifacts (amounts, PnL, gas, slippage).

    Returns:
        Path to the written file

    Raises:
        OSError: If atomic write fails
        TypeError: If data cannot be serialized to JSON
        ValueError: If decimal_mode is unknown
    """
    path = Path(path)

    if decimal_mode not in DECIMAL_MODES:
        raise ValueError(
            f"unknown decimal_mode {decimal_mode!r}; expected one of {sorted(DECIMAL_MODES)}"
        )

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    # Use provided default or fall back to our serializer
    if default is not None:
        serializer = default
    elif decimal_mode == "str":
        serializer = _exact_decimal_serializer
    else:
        serializer = _default_serializer

    # Create temp file in same directory (required for atomic os.replace)
    fd, temp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=f".{path.name}.",
        dir=path.parent,
    )

    try:
        # Write JSON to temp file
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, default=serializer, ensure_ascii=ensure_ascii)
            f.write("\n")  # Trailing newline for POSIX compliance
            f.flush()
            os.fsync(f.fileno())  # Force write to disk

        # Atomic replace вЂ” on Windows, antivirus can briefly lock the .tmp
        # file between write and rename, causing PermissionError; retry.
        import time as _time

        for _attempt in range(6):
            try:
                os.replace(temp_path, path)
                break
            except PermissionError:
                if _attempt < 5:
                    _time.sleep(0.5 * (_attempt + 1))
                else:
                    raise

        return path

    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def read_json(path: Union[str, Path]) -> Any:
    """
    Read JSON from file with proper error handling.

    Args:
        path: File path to read

    Returns:
        Parsed JSON data

    Raises:
        FileNotFoundError: If file doesn't exist
        json.JSONDecodeError: If file contains invalid JSON
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def safe_read_json(path: Union[str, Path], default: Any = None) -> Any:
    """
    Read JSON with fallback to default on any error.

    Args:
        path: File path to read
        default: Value to return on error (default: None)

    Returns:
        Parsed JSON data or default
    """
    try:
        return read_json(path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def write_money_json(
    path: Union[str, Path],
    data: Any,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> Path:
    """Atomic JSON write for canonical money artifacts.

    Forces ``decimal_mode="str"`` so ``Decimal`` amounts/PnL/gas/slippage
    keep exact precision (no float money, Roadmap В§3.2).
    """
    return atomic_write_json(
        path,
        data,
        indent=indent,
        ensure_ascii=ensure_ascii,
        decimal_mode="str",
    )


__all__ = [
    "atomic_write_json",
    "write_money_json",
    "read_json",
    "safe_read_json",
    "DECIMAL_MODES",
]
