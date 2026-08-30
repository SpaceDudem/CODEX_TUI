from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from codex_tui.models import SchemaSnapshot
from codex_tui.paths import schema_snapshot_dir
from codex_tui.schema.snapshot import load_schema, newest_snapshot, write_immutable_snapshot

OFFICIAL_SCHEMA_URL = "https://developers.openai.com/codex/config-schema.json"
DEFAULT_TIMEOUT_SECONDS = 10.0


class SchemaUnavailableError(RuntimeError):
    pass


def _validate_json_object(content: bytes) -> None:
    parsed = json.loads(content.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Codex config schema root is not a JSON object")


def acquire_schema(
    *,
    snapshot_dir: Path | None = None,
    source_url: str = OFFICIAL_SCHEMA_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    refresh: bool = False,
    client: httpx.Client | None = None,
) -> tuple[dict[str, Any], SchemaSnapshot, bool]:
    directory = snapshot_dir or schema_snapshot_dir()
    cached = newest_snapshot(directory)

    if cached is not None and not refresh:
        schema = load_schema(cached)
        content = cached.read_bytes()
        snapshot = write_immutable_snapshot(content, snapshot_dir=directory, source_url=source_url)
        return schema, snapshot, True

    owned_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=timeout_seconds)
    try:
        response = http.get(
            source_url,
            headers={"Accept": "application/schema+json, application/json"},
        )
        response.raise_for_status()
        content = response.content
        _validate_json_object(content)
        snapshot = write_immutable_snapshot(content, snapshot_dir=directory, source_url=source_url)
        return load_schema(snapshot.path), snapshot, False
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as exc:
        fallback = newest_snapshot(directory)
        if fallback is None:
            raise SchemaUnavailableError(
                f"Unable to acquire Codex config schema and no cached snapshot exists: {exc}"
            ) from exc
        schema = load_schema(fallback)
        content = fallback.read_bytes()
        snapshot = write_immutable_snapshot(content, snapshot_dir=directory, source_url=source_url)
        return schema, snapshot, True
    finally:
        if owned_client:
            http.close()
