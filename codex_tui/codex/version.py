from __future__ import annotations

import subprocess
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 5.0


class CodexVersionError(RuntimeError):
    pass


def get_codex_version(binary: Path, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS) -> str:
    try:
        completed = subprocess.run(
            [str(binary), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodexVersionError(f"Unable to query Codex version: {exc}") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise CodexVersionError(
            f"Codex version command exited with {completed.returncode}: {detail or 'no output'}"
        )
    version = completed.stdout.strip() or completed.stderr.strip()
    if not version:
        raise CodexVersionError("Codex version command returned no version text")
    return version
