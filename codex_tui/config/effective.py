from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from codex_tui.models import ConfigLayer, EffectiveValue, OverriddenValue


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
            path = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(item, path))
    else:
        result[prefix] = _plain(value)
    return result


def compute_effective_values(
    layer_documents: Sequence[tuple[ConfigLayer, Mapping[str, Any]]],
) -> dict[str, EffectiveValue]:
    effective: dict[str, EffectiveValue] = {}
    for layer, document in sorted(layer_documents, key=lambda item: item[0].precedence):
        for key_path, value in _flatten(document).items():
            previous = effective.get(key_path)
            overridden: list[OverriddenValue] = []
            if previous is not None:
                overridden.extend(previous.overridden_values)
                overridden.append(
                    OverriddenValue(
                        value=previous.value,
                        layer_id=previous.winning_layer,
                        source_path=previous.winning_path,
                    )
                )
            effective[key_path] = EffectiveValue(
                key_path=key_path,
                value=value,
                winning_layer=layer.layer_id,
                winning_path=layer.path,
                overridden_values=overridden,
            )
    return effective
