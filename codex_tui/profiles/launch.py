from __future__ import annotations

import subprocess
from pathlib import Path

from codex_tui.profiles.names import validate_profile_name


class ProfileLaunchError(RuntimeError):
    pass


def build_profile_argv(binary: Path, name: str) -> list[str]:
    validate_profile_name(name)
    return [str(binary), "--profile", name]


def launch_profile(binary: Path, name: str, *, cwd: Path | None = None) -> int:
    """Launch interactive Codex with a selected profile and inherited terminal I/O."""
    argv = build_profile_argv(binary, name)
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            check=False,
            shell=False,
        )
    except OSError as exc:
        raise ProfileLaunchError(f"Unable to launch Codex profile {name!r}: {exc}") from exc
    return completed.returncode
