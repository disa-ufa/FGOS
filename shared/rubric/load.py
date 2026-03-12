from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict

def load_rubric(version: str = "noo_v1") -> Dict[str, Any]:
    base = Path(__file__).resolve().parent
    path = base / f"rubric_{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"Rubric not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
