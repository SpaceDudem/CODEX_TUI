from __future__ import annotations

from pathlib import Path

from codex_tui.models import ConfigLayer, LayerType
from codex_tui.paths import codex_home, user_config_path


def discover_user_layers(
    *,
    working_directory: Path | None = None,
    profile: str | None = None,
) -> list[ConfigLayer]:
    layers: list[ConfigLayer] = []
    base = user_config_path()
    if base.exists():
        layers.append(
            ConfigLayer(
                layer_id="user",
                layer_type=LayerType.USER,
                path=base,
                precedence=100,
                writable=False,
            )
        )

    if profile:
        profile_path = codex_home() / f"{profile}.config.toml"
        if profile_path.exists():
            layers.append(
                ConfigLayer(
                    layer_id=f"profile:{profile}",
                    layer_type=LayerType.USER_PROFILE,
                    path=profile_path,
                    precedence=200,
                    writable=False,
                    profile_name=profile,
                )
            )

    cwd = (working_directory or Path.cwd()).resolve()
    parents = list(reversed([cwd, *cwd.parents]))
    project_precedence = 300
    for directory in parents:
        candidate = directory / ".codex" / "config.toml"
        if candidate.exists():
            layers.append(
                ConfigLayer(
                    layer_id=f"project:{directory}",
                    layer_type=LayerType.PROJECT,
                    path=candidate,
                    precedence=project_precedence,
                    writable=False,
                )
            )
            project_precedence += 10

    return sorted(layers, key=lambda layer: layer.precedence)
