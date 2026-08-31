from __future__ import annotations

import re

_PROFILE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
PROFILE_SUFFIX = ".config.toml"
BASE_CONFIG_NAME = "config.toml"


class InvalidProfileNameError(ValueError):
    pass


def validate_profile_name(value: str) -> str:
    """Match Codex ProfileV2Name: non-empty ASCII alphanumeric, underscore, or hyphen."""
    if not value or _PROFILE_NAME.fullmatch(value) is None:
        raise InvalidProfileNameError(
            f"invalid profile name {value!r}; use only ASCII letters, digits, '_' or '-'"
        )
    return value


def profile_name_from_filename(filename: str) -> str | None:
    if filename == BASE_CONFIG_NAME or not filename.endswith(PROFILE_SUFFIX):
        return None
    name = filename[: -len(PROFILE_SUFFIX)]
    try:
        return validate_profile_name(name)
    except InvalidProfileNameError:
        return None
