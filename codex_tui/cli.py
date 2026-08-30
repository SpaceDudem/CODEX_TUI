from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import typer

from codex_tui.codex.binary import CodexBinaryNotFoundError, discover_codex_binary
from codex_tui.codex.version import CodexVersionError, get_codex_version
from codex_tui.config.diagnostics import detect_ignored_project_scope, detect_legacy_profiles
from codex_tui.config.diff import semantic_diff
from codex_tui.config.effective import compute_effective_values
from codex_tui.config.layers import discover_user_layers
from codex_tui.config.parser import ParsedConfig, load_config
from codex_tui.config.validator import validate_config
from codex_tui.models import ConfigLayer, Diagnostic, LayerType
from codex_tui.mutation_cli import (
    apply_command,
    backup_command,
    history_command,
    restore_command,
)
from codex_tui.paths import codex_home
from codex_tui.schema.catalog import build_catalog
from codex_tui.schema.fetch import SchemaUnavailableError, acquire_schema
from codex_tui.security import display_validation_message, display_value

app = typer.Typer(
    name="codex-tui",
    no_args_is_help=True,
    help="Schema-driven Codex configuration inspector and safety-first manager.",
)

_DEFAULT_EFFECTIVE_KEYS = (
    "model",
    "model_reasoning_effort",
    "model_reasoning_summary",
    "model_verbosity",
    "approval_policy",
    "approvals_reviewer",
    "sandbox_mode",
)


def _progress(message: str) -> None:
    typer.echo(f"[codex-tui] {message}", err=True)


def _parsed_mapping(parsed: ParsedConfig) -> dict[str, Any]:
    if parsed.document is None:
        return {}
    return dict(parsed.document.unwrap())


def _print_diagnostics(diagnostics: Iterable[Diagnostic]) -> None:
    for diagnostic in diagnostics:
        where = str(diagnostic.source_path) if diagnostic.source_path else "<unknown>"
        location = ""
        if diagnostic.line is not None:
            location = f":{diagnostic.line}"
            if diagnostic.column is not None:
                location += f":{diagnostic.column}"
        key = f" [{diagnostic.key_path}]" if diagnostic.key_path else ""
        message = display_validation_message(diagnostic.key_path, diagnostic.message)
        typer.echo(
            f"{diagnostic.severity.value.upper()} {diagnostic.kind.value}{key} "
            f"{where}{location}: {message}"
        )


def _installed_codex_version() -> tuple[Path | None, str | None, str | None]:
    try:
        binary = discover_codex_binary()
    except CodexBinaryNotFoundError as exc:
        return None, None, str(exc)
    try:
        return binary, get_codex_version(binary), None
    except CodexVersionError as exc:
        return binary, None, str(exc)


def _explicit_layers(config: Path, profile: str | None) -> list[ConfigLayer]:
    target = config.expanduser()
    layers = [
        ConfigLayer(
            layer_id="explicit",
            layer_type=LayerType.USER,
            path=target,
            precedence=100,
            writable=False,
        )
    ]
    if profile:
        profile_path = target.parent / f"{profile}.config.toml"
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
    return layers


@app.command()
def inspect(
    config: Path | None = typer.Option(None, "--config", help="Config path to inspect."),
    profile: str | None = typer.Option(None, "--profile", help="Named profile to include."),
    working_directory: Path | None = typer.Option(
        None, "--cwd", help="Working directory used for project-layer discovery."
    ),
    effective_key: list[str] = typer.Option(
        [], "--effective", "-e", help="Effective key to display; repeat for multiple keys."
    ),
    all_effective: bool = typer.Option(
        False, "--all-effective", help="Display every effective leaf value with provenance."
    ),
) -> None:
    """Inspect Codex, config layers, diagnostics, and effective-value provenance."""
    typer.echo(f"CODEX_HOME: {codex_home()}")

    binary, version, version_error = _installed_codex_version()
    if binary is None:
        typer.echo(f"Codex binary: unavailable ({version_error})")
    else:
        typer.echo(f"Codex binary: {binary}")
        if version is None:
            typer.echo(f"Codex version: unavailable ({version_error})")
        else:
            typer.echo(f"Codex version: {version}")

    layers = (
        _explicit_layers(config, profile)
        if config is not None
        else discover_user_layers(working_directory=working_directory, profile=profile)
    )
    typer.echo(f"Discovered layers: {len(layers)}")
    for layer in layers:
        typer.echo(f"  {layer.precedence:03d} {layer.layer_type.value}: {layer.path}")

    layer_documents: list[tuple[ConfigLayer, dict[str, Any]]] = []
    invalid = False
    for layer in layers:
        parsed = load_config(layer.path)
        if not parsed.valid_toml:
            _print_diagnostics(parsed.diagnostics)
            invalid = True
            continue
        mapping = _parsed_mapping(parsed)
        layer_documents.append((layer, mapping))
        diagnostics = detect_legacy_profiles(mapping, parsed.path, codex_version=version)
        if layer.layer_type is LayerType.PROJECT:
            diagnostics.extend(detect_ignored_project_scope(mapping, parsed.path))
        _print_diagnostics(diagnostics)

    if invalid:
        raise typer.Exit(code=1)
    if not layer_documents:
        typer.echo("No readable config layers discovered.")
        return

    effective = compute_effective_values(layer_documents)
    if all_effective:
        keys = sorted(effective)
    elif effective_key:
        keys = effective_key
    else:
        keys = [key for key in _DEFAULT_EFFECTIVE_KEYS if key in effective]

    typer.echo("Effective values:")
    for key in keys:
        current = effective.get(key)
        if current is None:
            typer.echo(f"  {key}: <unset>")
            continue
        typer.echo(
            f"  {key} = {display_value(key, current.value)} "
            f"<- {current.winning_layer} ({current.winning_path})"
        )
        for overridden in current.overridden_values:
            typer.echo(
                f"    overrides {display_value(key, overridden.value)} "
                f"from {overridden.layer_id} ({overridden.source_path})"
            )


@app.command()
def validate(
    config: Path = typer.Option(..., "--config", exists=False, help="Config file to validate."),
    schema_file: Path | None = typer.Option(
        None, "--schema-file", help="Pinned local schema; skips network acquisition."
    ),
    refresh_schema: bool = typer.Option(False, "--refresh-schema"),
    scope: LayerType | None = typer.Option(
        None,
        "--scope",
        help="Optional config layer scope for scope-specific diagnostics (for example project).",
    ),
) -> None:
    """Validate a Codex config against a pinned or cached official schema."""
    parsed = load_config(config)
    if not parsed.valid_toml:
        _print_diagnostics(parsed.diagnostics)
        raise typer.Exit(code=1)

    try:
        if schema_file:
            _progress(f"loading schema {schema_file}")
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            if not isinstance(schema, dict):
                raise ValueError("schema root must be an object")
            snapshot_label = str(schema_file)
        else:
            _progress("acquiring Codex config schema")
            schema, snapshot, from_cache = acquire_schema(refresh=refresh_schema)
            snapshot_label = f"{snapshot.sha256} ({'cache' if from_cache else 'network'})"
        _progress(f"validating against schema {snapshot_label}")
    except (SchemaUnavailableError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"ERROR runtime: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    _, codex_version, _ = _installed_codex_version()
    diagnostics = validate_config(
        _parsed_mapping(parsed),
        schema,
        parsed.path,
        codex_version=codex_version,
        layer_type=scope,
    )
    _print_diagnostics(diagnostics)

    errors = [item for item in diagnostics if item.severity.value in {"error", "blocking"}]
    typer.echo(f"Diagnostics: {len(diagnostics)} total, {len(errors)} error/blocking")
    if errors:
        raise typer.Exit(code=1)


@app.command()
def catalog(
    schema_file: Path | None = typer.Option(None, "--schema-file"),
    search: str | None = typer.Option(None, "--search", "-s"),
    refresh_schema: bool = typer.Option(False, "--refresh-schema"),
) -> None:
    """Build and display the schema-derived setting catalog."""
    try:
        if schema_file:
            _progress(f"loading schema {schema_file}")
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
            if not isinstance(schema, dict):
                raise ValueError("schema root must be an object")
        else:
            _progress("acquiring Codex config schema")
            schema, _, _ = acquire_schema(refresh=refresh_schema)
    except (SchemaUnavailableError, OSError, ValueError, json.JSONDecodeError) as exc:
        typer.echo(f"ERROR runtime: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    _progress("building setting catalog")
    items = build_catalog(schema)
    if search:
        needle = search.casefold()
        items = [
            item
            for item in items
            if needle in item.key_path.casefold()
            or needle in (item.description or "").casefold()
            or any(needle in str(value).casefold() for value in item.allowed_values)
        ]

    for item in items:
        enum = f" enum={item.allowed_values}" if item.allowed_values else ""
        default = f" default={item.default_value!r}" if item.default_value is not None else ""
        maturity = f" maturity={item.maturity}" if item.maturity != "stable" else ""
        typer.echo(
            f"{item.key_path} type={item.value_type or 'unknown'}{enum}{default}{maturity}"
        )
    typer.echo(f"Catalog entries: {len(items)}")


@app.command("diff")
def diff_command(
    config_a: Path = typer.Argument(...),
    config_b: Path = typer.Argument(...),
) -> None:
    """Produce a semantic diff between two TOML configurations."""
    left = load_config(config_a)
    right = load_config(config_b)
    invalid = False
    for parsed in (left, right):
        if not parsed.valid_toml:
            _print_diagnostics(parsed.diagnostics)
            invalid = True
    if invalid:
        raise typer.Exit(code=1)

    result = semantic_diff(
        left.path,
        _parsed_mapping(left),
        right.path,
        _parsed_mapping(right),
    )
    if result.is_empty:
        typer.echo("No semantic changes.")
        return

    for change in result.changes:
        before = display_value(change.key_path, change.before)
        after = display_value(change.key_path, change.after)
        if change.kind.value == "added":
            typer.echo(f"+ {change.key_path} = {after}")
        elif change.kind.value == "removed":
            typer.echo(f"- {change.key_path} = {before}")
        else:
            typer.echo(f"~ {change.key_path}: {before} -> {after}")
    typer.echo(f"Semantic changes: {len(result.changes)}")


app.command("backup")(backup_command)
app.command("history")(history_command)
app.command("restore")(restore_command)
app.command("apply")(apply_command)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
