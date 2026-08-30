from __future__ import annotations

import shutil
from pathlib import Path


class CodexBinaryNotFoundError(RuntimeError):
    pass


def discover_codex_binary() -> Path:
    located = shutil.which("codex")
    if located is None:
        raise CodexBinaryNotFoundError("Codex executable was not found on PATH")
    return Path(located).resolve()
