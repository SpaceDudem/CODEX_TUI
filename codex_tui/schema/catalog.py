from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from codex_tui.models import SettingDefinition


def _resolve_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any] | None:
    if not ref.startswith("#/"):
        return None
    current: Any = root
    for token in ref[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, Mapping) or token not in current:
            return None
        current = current[token]
    return current if isinstance(current, Mapping) else None


def _merged_node(root: Mapping[str, Any], node: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(node)
    ref = node.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_ref(root, ref)
        if resolved is not None:
            merged = {**resolved, **{key: value for key, value in node.items() if key != "$ref"}}
    return merged


def _infer_type(node: Mapping[str, Any]) -> str | None:
    declared = node.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(declared, list):
        return " | ".join(str(item) for item in declared)
    if "enum" in node:
        return "enum"
    if "properties" in node or "additionalProperties" in node:
        return "object"
    return None


def _walk(
    root: Mapping[str, Any],
    node: Mapping[str, Any],
    *,
    prefix: str,
    output: list[SettingDefinition],
    visited_refs: frozenset[str],
) -> None:
    ref = node.get("$ref")
    if isinstance(ref, str) and ref in visited_refs:
        return
    next_visited = visited_refs | ({ref} if isinstance(ref, str) else set())
    merged = _merged_node(root, node)

    properties = merged.get("properties")
    if isinstance(properties, Mapping):
        for name, child in properties.items():
            if not isinstance(child, Mapping):
                continue
            path = f"{prefix}.{name}" if prefix else str(name)
            child_node = _merged_node(root, child)
            allowed = child_node.get("enum")
            allowed_values = list(allowed) if isinstance(allowed, list) else []
            output.append(
                SettingDefinition(
                    key_path=path,
                    section=prefix or None,
                    value_type=_infer_type(child_node),
                    allowed_values=allowed_values,
                    default_value=child_node.get("default"),
                    description=child_node.get("description")
                    if isinstance(child_node.get("description"), str)
                    else None,
                    maturity="deprecated" if child_node.get("deprecated") is True else "stable",
                    source_reference=child.get("$ref")
                    if isinstance(child.get("$ref"), str)
                    else None,
                )
            )
            _walk(
                root,
                child,
                prefix=path,
                output=output,
                visited_refs=next_visited,
            )


def build_catalog(schema: Mapping[str, Any]) -> list[SettingDefinition]:
    output: list[SettingDefinition] = []
    _walk(schema, schema, prefix="", output=output, visited_refs=frozenset())
    deduped: dict[str, SettingDefinition] = {}
    for item in output:
        deduped.setdefault(item.key_path, item)
    return [deduped[key] for key in sorted(deduped)]
