from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from codex_tui.codex.version import codex_version_at_least
from codex_tui.models import Diagnostic, DiagnosticKind, Severity

PROFILE_FILE_CUTOFF = (0, 134, 0)

# Current Codex documentation marks these keys as machine/user-owned and ignored
# when they appear in project-local .codex/config.toml layers.
PROJECT_LOCAL_IGNORED_ROOT_KEYS = frozenset(
    {
        "openai_base_url",
        "chatgpt_base_url",
        "apps_mcp_product_sku",
        "model_provider",
        "model_providers",
        "notify",
        "profile",
        "profiles",
        "experimental_realtime_ws_base_url",
        "otel",
    }
)


def detect_legacy_profiles(
    config: Mapping[str, Any],
    source_path: Path,
    *,
    codex_version: str | None = None,
) -> list[Diagnostic]:
    """Warn about embedded profiles only when the installed Codex is new enough.

    Codex 0.134.0+ selects sibling `$CODEX_HOME/<name>.config.toml` files and no
    longer uses `[profiles.<name>]` tables for `--profile`. Older versions remain
    relevant to the historical catalog, so the diagnostic is version-gated.
    """

    if not codex_version_at_least(codex_version, PROFILE_FILE_CUTOFF):
        return []

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
                    f"Codex {codex_version} ignores profiles.{name!s} for --profile. "
                    f"Move its overrides to $CODEX_HOME/{name!s}.config.toml."
                ),
                source_path=source_path,
                key_path=f"profiles.{name}",
            )
        )
    return diagnostics


def detect_ignored_project_scope(
    config: Mapping[str, Any], source_path: Path
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for key in sorted(PROJECT_LOCAL_IGNORED_ROOT_KEYS.intersection(config.keys())):
        diagnostics.append(
            Diagnostic(
                severity=Severity.WARNING,
                kind=DiagnosticKind.IGNORED_SCOPE,
                message=(
                    f"Codex ignores top-level {key!r} in project-local .codex/config.toml; "
                    "place it in the user-level config or select profiles with --profile."
                ),
                source_path=source_path,
                key_path=str(key),
            )
        )
    return diagnostics
