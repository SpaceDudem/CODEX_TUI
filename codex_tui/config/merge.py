from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def overlay_mapping(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively overlay TOML-shaped mappings; tables merge and other values replace."""
    result: dict[str, Any] = deepcopy(dict(base))
    for key, value in overlay.items():
        current = result.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            result[key] = overlay_mapping(current, value)
        else:
            result[key] = deepcopy(value)
    return result
