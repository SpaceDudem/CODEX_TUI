from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_tui.models import SchemaSnapshot


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def write_immutable_snapshot(
    content: bytes,
    *,
    snapshot_dir: Path,
    source_url: str,
) -> SchemaSnapshot:
    digest = sha256_bytes(content)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{digest}.json"
    if not path.exists():
        path.write_bytes(content)
    return SchemaSnapshot(
        sha256=digest,
        path=path,
        source_url=source_url,
        acquired_at=datetime.now(UTC).isoformat(),
        size_bytes=len(content),
    )


def load_schema(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Schema root must be an object: {path}")
    return data


def newest_snapshot(snapshot_dir: Path) -> Path | None:
    if not snapshot_dir.exists():
        return None
    candidates = [path for path in snapshot_dir.glob("*.json") if path.is_file()]
    return max(candidates, key=lambda path: path.stat().st_mtime_ns, default=None)
