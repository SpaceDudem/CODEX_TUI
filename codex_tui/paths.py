from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "codex-tui"


def codex_home(env: dict[str, str] | None = None) -> Path:
    environment = os.environ if env is None else env
    configured = environment.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


def user_config_path(env: dict[str, str] | None = None) -> Path:
    return codex_home(env) / "config.toml"


def xdg_config_home(env: dict[str, str] | None = None) -> Path:
    environment = os.environ if env is None else env
    return Path(environment.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser()


def xdg_data_home(env: dict[str, str] | None = None) -> Path:
    environment = os.environ if env is None else env
    return Path(environment.get("XDG_DATA_HOME", Path.home() / ".local" / "share")).expanduser()


def xdg_cache_home(env: dict[str, str] | None = None) -> Path:
    environment = os.environ if env is None else env
    return Path(environment.get("XDG_CACHE_HOME", Path.home() / ".cache")).expanduser()


def app_config_dir(env: dict[str, str] | None = None) -> Path:
    return xdg_config_home(env) / APP_DIR_NAME


def app_data_dir(env: dict[str, str] | None = None) -> Path:
    return xdg_data_home(env) / APP_DIR_NAME


def app_cache_dir(env: dict[str, str] | None = None) -> Path:
    return xdg_cache_home(env) / APP_DIR_NAME


def schema_snapshot_dir(env: dict[str, str] | None = None) -> Path:
    return app_data_dir(env) / "schemas"


def backup_root_dir(env: dict[str, str] | None = None) -> Path:
    return app_data_dir(env) / "backups"
