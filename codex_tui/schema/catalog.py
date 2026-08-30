from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from codex_tui.models import SettingDefinition
from codex_tui.security import is_sensitive_key_path

_COMPOSITION_KEYS = ("oneOf", "anyOf")


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


def _deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if key == "properties" and isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _normalize_node(
    root: Mapping[str, Any],
    node: Mapping[str, Any],
    *,
    visited_refs: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Resolve local refs and flatten allOf for catalog inspection.

    `oneOf` and `anyOf` are preserved because they represent alternatives rather
    than fields that should be blindly merged together.
    """

    merged: dict[str, Any] = {}
    next_visited = visited_refs

    ref = node.get("$ref")
    if isinstance(ref, str) and ref not in visited_refs:
        resolved = _resolve_ref(root, ref)
        if resolved is not None:
            next_visited = visited_refs | {ref}
            merged = _deep_merge(
                merged,
                _normalize_node(root, resolved, visited_refs=next_visited),
            )

    all_of = node.get("allOf")
    if isinstance(all_of, list):
        for branch in all_of:
            if isinstance(branch, Mapping):
                merged = _deep_merge(
                    merged,
                    _normalize_node(root, branch, visited_refs=next_visited),
                )

    local = {key: value for key, value in node.items() if key not in {"$ref", "allOf"}}
    return _deep_merge(merged, local)


def _composition_nodes(root: Mapping[str, Any], node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    normalized = _normalize_node(root, node)
    output: list[Mapping[str, Any]] = []
    for key in _COMPOSITION_KEYS:
        branches = normalized.get(key)
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if isinstance(branch, Mapping):
                output.append(_normalize_node(root, branch))
    return output


def _infer_type(root: Mapping[str, Any], node: Mapping[str, Any]) -> str | None:
    normalized = _normalize_node(root, node)
    types: list[str] = []

    def add(value: str | None) -> None:
        if value and value not in types:
            types.append(value)

    declared = normalized.get("type")
    if isinstance(declared, str):
        add(declared)
    elif isinstance(declared, list):
        for item in declared:
            if isinstance(item, str):
                add(item)

    if declared is None and (
        isinstance(normalized.get("properties"), Mapping)
        or isinstance(normalized.get("additionalProperties"), Mapping)
    ):
        add("object")

    for branch in _composition_nodes(root, node):
        add(_infer_type(root, branch))

    if not types and "enum" in normalized:
        add("enum")
    return " | ".join(types) if types else None


def _allowed_values(
    root: Mapping[str, Any],
    node: Mapping[str, Any],
    *,
    depth: int = 0,
) -> list[Any]:
    if depth > 32:
        return []

    normalized = _normalize_node(root, node)
    output: list[Any] = []
    enum = normalized.get("enum")
    if isinstance(enum, list):
        for value in enum:
            if value not in output:
                output.append(value)
    if "const" in normalized and normalized["const"] not in output:
        output.append(normalized["const"])

    for branch in _composition_nodes(root, node):
        for value in _allowed_values(root, branch, depth=depth + 1):
            if value not in output:
                output.append(value)
    return output


def _first_ref(node: Mapping[str, Any]) -> str | None:
    direct = node.get("$ref")
    if isinstance(direct, str):
        return direct
    for key in ("allOf", "oneOf", "anyOf"):
        branches = node.get(key)
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if isinstance(branch, Mapping):
                ref = _first_ref(branch)
                if ref:
                    return ref
    return None


def _maturity(path: str, node: Mapping[str, Any]) -> str:
    if node.get("deprecated") is True:
        return "deprecated"
    description = node.get("description")
    if (
        path.startswith("experimental_")
        or ".experimental_" in path
        or (isinstance(description, str) and "experimental" in description.casefold())
    ):
        return "experimental"
    return "stable"


def _definition(
    root: Mapping[str, Any],
    raw_node: Mapping[str, Any],
    path: str,
    section: str | None,
) -> SettingDefinition:
    node = _normalize_node(root, raw_node)
    description = node.get("description")
    return SettingDefinition(
        key_path=path,
        section=section,
        value_type=_infer_type(root, raw_node),
        allowed_values=_allowed_values(root, raw_node),
        default_value=node.get("default"),
        description=description if isinstance(description, str) else None,
        maturity=_maturity(path, node),
        source_reference=_first_ref(raw_node),
        schema_version=root.get("$schema") if isinstance(root.get("$schema"), str) else None,
        sensitive=is_sensitive_key_path(path),
    )


def _walk(
    root: Mapping[str, Any],
    node: Mapping[str, Any],
    *,
    prefix: str,
    output: list[SettingDefinition],
    visited_refs: frozenset[str],
) -> None:
    direct_ref = node.get("$ref")
    if isinstance(direct_ref, str) and direct_ref in visited_refs:
        return
    next_visited = visited_refs | ({direct_ref} if isinstance(direct_ref, str) else set())
    normalized = _normalize_node(root, node, visited_refs=visited_refs)

    properties = normalized.get("properties")
    if isinstance(properties, Mapping):
        for name, child in properties.items():
            if not isinstance(child, Mapping):
                continue
            path = f"{prefix}.{name}" if prefix else str(name)
            output.append(_definition(root, child, path, prefix or None))
            _walk(
                root,
                child,
                prefix=path,
                output=output,
                visited_refs=next_visited,
            )

    additional = normalized.get("additionalProperties")
    if prefix and isinstance(additional, Mapping):
        path = f"{prefix}.<name>"
        output.append(_definition(root, additional, path, prefix))
        _walk(
            root,
            additional,
            prefix=path,
            output=output,
            visited_refs=next_visited,
        )

    for key in _COMPOSITION_KEYS:
        branches = normalized.get(key)
        if not isinstance(branches, list):
            continue
        for branch in branches:
            if isinstance(branch, Mapping):
                _walk(
                    root,
                    branch,
                    prefix=prefix,
                    output=output,
                    visited_refs=next_visited,
                )


def build_catalog(schema: Mapping[str, Any]) -> list[SettingDefinition]:
    output: list[SettingDefinition] = []
    _walk(schema, schema, prefix="", output=output, visited_refs=frozenset())
    deduped: dict[str, SettingDefinition] = {}
    for item in output:
        existing = deduped.get(item.key_path)
        if existing is None:
            deduped[item.key_path] = item
            continue
        # Prefer a richer definition when the same path appears through multiple union branches.
        existing_score = sum(
            [
                bool(existing.description),
                bool(existing.allowed_values),
                bool(existing.value_type),
                bool(existing.source_reference),
            ]
        )
        item_score = sum(
            [
                bool(item.description),
                bool(item.allowed_values),
                bool(item.value_type),
                bool(item.source_reference),
            ]
        )
        if item_score > existing_score:
            deduped[item.key_path] = item
    return [deduped[key] for key in sorted(deduped)]
