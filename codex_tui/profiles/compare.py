from __future__ import annotations

from pathlib import Path
from typing import Any

from codex_tui.config.diff import semantic_diff
from codex_tui.config.merge import overlay_mapping
from codex_tui.config.parser import load_config
from codex_tui.profiles.models import ProfileComparison
from codex_tui.profiles.names import validate_profile_name


class ProfileComparisonError(RuntimeError):
    pass


def _mapping(path: Path) -> dict[str, Any]:
    parsed = load_config(path)
    if not parsed.valid_toml or parsed.document is None:
        details = "; ".join(item.message for item in parsed.diagnostics) or "invalid TOML"
        raise ProfileComparisonError(f"Unable to load {path}: {details}")
    return dict(parsed.document.unwrap())


def compare_profile(base_path: Path, profile_path: Path, *, name: str) -> ProfileComparison:
    """Compare base config with the effective base+profile overlay."""
    validate_profile_name(name)
    base = base_path.expanduser().absolute()
    profile = profile_path.expanduser().absolute()
    base_mapping = _mapping(base)
    overlay = _mapping(profile)
    effective = overlay_mapping(base_mapping, overlay)
    diff = semantic_diff(base, base_mapping, profile, effective)
    return ProfileComparison(name=name, base_path=base, profile_path=profile, diff=diff)
