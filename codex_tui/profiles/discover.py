from __future__ import annotations

from pathlib import Path

from codex_tui.config.parser import load_config
from codex_tui.models import Diagnostic, DiagnosticKind, Severity
from codex_tui.paths import codex_home
from codex_tui.profiles.models import ProfileInfo
from codex_tui.profiles.names import BASE_CONFIG_NAME, PROFILE_SUFFIX, profile_name_from_filename


def discover_profiles(home: Path | None = None) -> tuple[list[ProfileInfo], list[Diagnostic]]:
    """Discover direct-child Codex profile-v2 files under CODEX_HOME."""
    root = (home or codex_home()).expanduser().absolute()
    profiles: list[ProfileInfo] = []
    diagnostics: list[Diagnostic] = []

    try:
        entries = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except OSError as exc:
        diagnostics.append(
            Diagnostic(
                severity=Severity.ERROR,
                kind=DiagnosticKind.UNREACHABLE_PATH,
                message=f"Unable to inspect CODEX_HOME for profiles: {exc}",
                source_path=root,
            )
        )
        return profiles, diagnostics

    for path in entries:
        if path.name == BASE_CONFIG_NAME or not path.name.endswith(PROFILE_SUFFIX):
            continue
        name = profile_name_from_filename(path.name)
        if name is None:
            diagnostics.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    kind=DiagnosticKind.PROFILE_INVALID_NAME,
                    message=(
                        "Profile-like filename is not selectable by Codex; "
                        "profile names allow only ASCII letters, digits, '_' and '-'."
                    ),
                    source_path=path,
                )
            )
            continue
        if not path.is_file():
            diagnostics.append(
                Diagnostic(
                    severity=Severity.WARNING,
                    kind=DiagnosticKind.UNREACHABLE_PATH,
                    message="Profile path is not a regular file.",
                    source_path=path,
                )
            )
            continue

        parsed = load_config(path)
        profile_diagnostics = list(parsed.diagnostics)
        profiles.append(
            ProfileInfo(
                name=name,
                path=path,
                valid_toml=parsed.valid_toml,
                diagnostics=profile_diagnostics,
            )
        )

    return profiles, diagnostics
