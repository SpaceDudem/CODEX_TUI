from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from codex_tui.models import Diagnostic, DiagnosticKind, Severity


def detect_legacy_profiles(config: Mapping[str, Any], source_path: Path) -> list[Diagnostic]:
    profiles = config.get("profiles")
    if not isinstance(profiles, Mapping):
        return []

    diagnostics: list[Diagnostic] = []
    for name in profiles:
        diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                kind=DiagnosticKind.PROFILE_LEGACY,
                message=(
                    f"Legacy profile table profiles.{name!s} detected. Current profile-v2 "
                    f"layout uses $CODEX_HOME/{name!s}.config.toml selected with "
                    f"`codex --profile {name!s}`."
                ),
                source_path=source_path,
                key_path=f"profiles.{name}",
            )
        )
    return diagnostics
