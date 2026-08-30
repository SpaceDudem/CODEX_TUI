from __future__ import annotations

import re
from typing import Any

_SENSITIVE_TOKEN_RE = re.compile(
    r"(?:^|[.\[\]_-])(?:api[_-]?key|bearer|credential(?:s)?|password|private[_-]?key|secret|token)(?:$|[.\[\]_-])",
    re.IGNORECASE,
)


def is_sensitive_key_path(key_path: str | None) -> bool:
    """Return True when a config path may contain credential material.

    This intentionally errs on the side of redaction. Some matching Codex keys hold
    environment-variable names rather than secret values; hiding those names is safer
    than accidentally printing a newly introduced credential-bearing setting.
    """

    if not key_path:
        return False
    return _SENSITIVE_TOKEN_RE.search(key_path) is not None


def display_value(key_path: str | None, value: Any) -> str:
    if is_sensitive_key_path(key_path):
        return "<redacted>"
    return repr(value)


def display_validation_message(key_path: str | None, message: str) -> str:
    if is_sensitive_key_path(key_path):
        return "Value failed validation; detail redacted because the key may be sensitive."
    return message
