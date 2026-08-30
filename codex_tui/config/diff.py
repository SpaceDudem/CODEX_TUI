from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from codex_tui.models import SemanticChange, SemanticChangeKind, SemanticDiff


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(item) for item in value]
    return value


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, Mapping):
        if not value and prefix:
            result[prefix] = {}
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(item, next_prefix))
        return result
    result[prefix] = _plain(value)
    return result


def semantic_diff(
    left_path: Path,
    left: Mapping[str, Any],
    right_path: Path,
    right: Mapping[str, Any],
) -> SemanticDiff:
    left_flat = _flatten(left)
    right_flat = _flatten(right)
    changes: list[SemanticChange] = []

    for key in sorted(left_flat.keys() | right_flat.keys()):
        in_left = key in left_flat
        in_right = key in right_flat
        if not in_left:
            changes.append(
                SemanticChange(
                    key_path=key,
                    kind=SemanticChangeKind.ADDED,
                    after=right_flat[key],
                )
            )
        elif not in_right:
            changes.append(
                SemanticChange(
                    key_path=key,
                    kind=SemanticChangeKind.REMOVED,
                    before=left_flat[key],
                )
            )
        elif left_flat[key] != right_flat[key]:
            changes.append(
                SemanticChange(
                    key_path=key,
                    kind=SemanticChangeKind.CHANGED,
                    before=left_flat[key],
                    after=right_flat[key],
                )
            )

    return SemanticDiff(left_path=left_path, right_path=right_path, changes=changes)
