from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomlkit
from tomlkit import TOMLDocument
from tomlkit.exceptions import ParseError

from codex_tui.models import Diagnostic, DiagnosticKind, Severity


@dataclass(frozen=True, slots=True)
class ParsedConfig:
    path: Path
    document: TOMLDocument | None
    diagnostics: tuple[Diagnostic, ...]
    raw_text: str

    @property
    def valid_toml(self) -> bool:
        return self.document is not None


def _parse_error_position(error: ParseError) -> tuple[int | None, int | None]:
    line = getattr(error, "line", None)
    column = getattr(error, "col", None)
    if isinstance(line, int):
        line += 1
    if isinstance(column, int):
        column += 1
    return line, column


def load_config(path: Path) -> ParsedConfig:
    resolved = path.expanduser()
    try:
        raw = resolved.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostic = Diagnostic(
            severity=Severity.BLOCKING,
            kind=DiagnosticKind.UNREACHABLE_PATH,
            message=f"Unable to read config: {exc}",
            source_path=resolved,
        )
        return ParsedConfig(resolved, None, (diagnostic,), "")

    try:
        document = tomlkit.parse(raw)
    except ParseError as exc:
        line, column = _parse_error_position(exc)
        diagnostic = Diagnostic(
            severity=Severity.BLOCKING,
            kind=DiagnosticKind.PARSE_ERROR,
            message=str(exc),
            source_path=resolved,
            line=line,
            column=column,
        )
        return ParsedConfig(resolved, None, (diagnostic,), raw)

    return ParsedConfig(resolved, document, (), raw)
