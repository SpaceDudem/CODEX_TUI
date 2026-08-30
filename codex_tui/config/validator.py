from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from codex_tui.config.diagnostics import detect_legacy_profiles
from codex_tui.models import Diagnostic, DiagnosticKind, Severity


def _format_json_path(parts: list[Any]) -> str:
    return ".".join(str(part) for part in parts)


def validate_config(
    config: Mapping[str, Any],
    schema: Mapping[str, Any],
    source_path: Path,
) -> list[Diagnostic]:
    diagnostics = detect_legacy_profiles(config, source_path)

    try:
        validator = Draft202012Validator(schema)
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
                kind=DiagnosticKind.SCHEMA_MISMATCH,
                message=error.message,
                source_path=source_path,
                key_path=key_path,
            )
        )
    return diagnostics
