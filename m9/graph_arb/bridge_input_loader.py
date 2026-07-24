"""Bridge builder JSON input loaders (extracted module)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def load_json(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None
