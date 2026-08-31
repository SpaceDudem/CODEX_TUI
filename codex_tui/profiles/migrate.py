from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import Table

from codex_tui.config.parser import load_config
from codex_tui.models import Diagnostic, DiagnosticKind, Severity
from codex_tui.profiles.models import LegacyProfileCandidate, ProfileMigrationPlan
from codex_tui.profiles.names import PROFILE_SUFFIX, InvalidProfileNameError, validate_profile_name


def _render_profile_table(table: Table) -> str:
    """Re-root one legacy profile table while retaining its comments and nested tables."""
    candidate = tomlkit.document()
    for key, item in table.value.body:
        if key is None:
            candidate.add(deepcopy(item))
        else:
            candidate.append(deepcopy(key), deepcopy(item))
    rendered = candidate.as_string()
    # Treat successful reparse as an invariant before exposing a candidate.
    tomlkit.parse(rendered)
    return rendered


def plan_legacy_profile_migration(source_path: Path) -> ProfileMigrationPlan:
    """Build profile-v2 candidates without writing or modifying the source config."""
    source = source_path.expanduser().absolute()
    parsed = load_config(source)
    if not parsed.valid_toml or parsed.document is None:
        return ProfileMigrationPlan(
            source_path=source,
            diagnostics=list(parsed.diagnostics),
        )

    profiles_value: Any = parsed.document.get("profiles")
    if profiles_value is None:
        return ProfileMigrationPlan(source_path=source)
    if not isinstance(profiles_value, Table):
        diagnostic = Diagnostic(
            severity=Severity.ERROR,
            kind=DiagnosticKind.INVALID_TYPE,
            message="Legacy `profiles` value is not a TOML table.",
            source_path=source,
            key_path="profiles",
        )
        return ProfileMigrationPlan(source_path=source, diagnostics=[diagnostic])

    candidates: list[LegacyProfileCandidate] = []
    diagnostics: list[Diagnostic] = []
    seen_targets: set[Path] = set()

    for raw_name, profile_value in profiles_value.items():
        name = str(raw_name)
        key_path = f"profiles.{name}"
        try:
            validate_profile_name(name)
        except InvalidProfileNameError as exc:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    kind=DiagnosticKind.PROFILE_INVALID_NAME,
                    message=str(exc),
                    source_path=source,
                    key_path=key_path,
                )
            )
            continue

        if not isinstance(profile_value, Table):
            diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    kind=DiagnosticKind.INVALID_TYPE,
                    message="Legacy profile is not a TOML table.",
                    source_path=source,
                    key_path=key_path,
                )
            )
            continue

        target = source.parent / f"{name}{PROFILE_SUFFIX}"
        candidate_diagnostics: list[Diagnostic] = []
        if target in seen_targets or target.exists():
            candidate_diagnostics.append(
                Diagnostic(
                    severity=Severity.ERROR,
                    kind=DiagnosticKind.PROFILE_COLLISION,
                    message=(
                        "Migration target already exists; CODEX_TUI will not plan an implicit "
                        "overwrite. Compare or choose an explicit resolution first."
                    ),
                    source_path=target,
                    key_path=key_path,
                )
            )
        seen_targets.add(target)

        content = _render_profile_table(profile_value)
        candidates.append(
            LegacyProfileCandidate(
                name=name,
                source_key=key_path,
                target_path=target,
                content=content,
                diagnostics=candidate_diagnostics,
            )
        )

    return ProfileMigrationPlan(
        source_path=source,
        candidates=candidates,
        diagnostics=diagnostics,
    )
