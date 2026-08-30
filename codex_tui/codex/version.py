from __future__ import annotations

import re
import subprocess
from pathlib import Path

DEFAULT_TIMEOUT_SECONDS = 5.0
_VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")


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


def parse_codex_version(version_text: str) -> tuple[int, int, int] | None:
    """Extract a semantic Codex CLI version from arbitrary `codex --version` text."""

    match = _VERSION_RE.search(version_text)
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return major, minor, patch


def codex_version_at_least(version_text: str | None, minimum: tuple[int, int, int]) -> bool:
    if not version_text:
        return False
    parsed = parse_codex_version(version_text)
    return parsed is not None and parsed >= minimum
