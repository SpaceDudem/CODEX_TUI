from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for

from codex_tui.config.diagnostics import detect_ignored_project_scope, detect_legacy_profiles
from codex_tui.models import Diagnostic, DiagnosticKind, LayerType, Severity
from codex_tui.security import display_validation_message


def _format_json_path(parts: list[Any]) -> str:
    return ".".join(str(part) for part in parts)


def _kind_for_validator(name: Any) -> DiagnosticKind:
    if name == "type":
        return DiagnosticKind.INVALID_TYPE
    if name in {"enum", "const"}:
        return DiagnosticKind.INVALID_ENUM
    if name == "additionalProperties":
        return DiagnosticKind.UNKNOWN_KEY
    return DiagnosticKind.SCHEMA_MISMATCH


def validate_config(
    config: Mapping[str, Any],
    schema: Mapping[str, Any],
    source_path: Path,
    *,
    codex_version: str | None = None,
    layer_type: LayerType | None = None,
) -> list[Diagnostic]:
    diagnostics = detect_legacy_profiles(
        config,
        source_path,
        codex_version=codex_version,
    )
    if layer_type is LayerType.PROJECT:
        diagnostics.extend(detect_ignored_project_scope(config, source_path))

    try:
        validator_class = validator_for(schema)
        validator_class.check_schema(schema)
        validator = validator_class(schema)
    except SchemaError as exc:
        diagnostics.append(
            Diagnostic(
                severity=Severity.BLOCKING,
                kind=DiagnosticKind.SCHEMA_MISMATCH,
                message=f"Invalid schema snapshot: {exc.message}",
                source_path=source_path,
            )
        )
        return diagnostics

    for error in sorted(validator.iter_errors(config), key=lambda item: list(item.absolute_path)):
        key_path = _format_json_path(list(error.absolute_path)) or None
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                kind=_kind_for_validator(error.validator),
                message=display_validation_message(key_path, error.message),
                source_path=source_path,
                key_path=key_path,
            )
        )
    return diagnostics
