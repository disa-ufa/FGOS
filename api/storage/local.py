from __future__ import annotations
from pathlib import Path

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)

def path_for_doc(storage_dir: str, doc_id: str) -> Path:
    return Path(storage_dir) / "docs" / doc_id

def path_for_artifacts(storage_dir: str, doc_id: str) -> Path:
    return Path(storage_dir) / "docs" / doc_id / "artifacts"
