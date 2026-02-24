"""
PR3 — Save/load doc_map.json for artifacts dir.
"""
import json
from pathlib import Path
from typing import Any, Optional


def save_doc_map(doc_map: dict[str, Any], path: Path) -> Path:
    """Write doc_map to path. Creates parent dirs. Returns path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc_map, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_doc_map(path: Path) -> Optional[dict[str, Any]]:
    """Load doc_map from path. Returns None if file missing or invalid."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
