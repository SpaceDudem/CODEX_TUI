from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from codex_tui.codex.binary import CodexBinaryNotFoundError, discover_codex_binary
from codex_tui.codex.version import CodexVersionError, get_codex_version
from codex_tui.config.diff import semantic_diff
from codex_tui.config.layers import discover_user_layers
from codex_tui.config.parser import ParsedConfig, load_config
from codex_tui.config.validator import validate_config
from codex_tui.paths import codex_home, user_config_path
from codex_tui.schema.catalog import build_catalog
from codex_tui.schema.fetch import SchemaUnavailableError, acquire_schema

app = typer.Typer(
    name="codex-tui",
    no_args_is_help=True,
    help="Read-only Codex configuration inspector for M1.",
)


def _progress(message: str) -> None:
    typer.echo(f"[codex-tui] {message}", err=True)


def _parsed_mapping(parsed: ParsedConfig) -> dict[str, Any]:
    if parsed.document is None:
        return {}
    return dict(parsed.document.unwrap())


def _print_diagnostics(parsed: ParsedConfig) -> None:
    for diagnostic in parsed.diagnostics:
        where = str(diagnostic.source_path) if diagnostic.source_path else "<unknown>"
        location = ""
        if diagnostic.line is not None:
            location = f":{diagnostic.line}"
            if diagnostic.column is not None:
                location += f":{diagnostic.column}"
        typer.echo(
            f"{diagnostic.severity.value.upper()} {diagnostic.kind.value} "
            f"{where}{location}: {diagnostic.message}"
        )


@app.command()
def inspect(
    config: Path | None = typer.Option(None, "--config", help="Config path to inspect."),
    profile: str | None = typer.Option(None, "--profile", help="Named profile to include."),
) -> None:
    """Inspect Codex, CODEX_HOME, config layers, and basic diagnostics."""
    target = config.expanduser() if config else user_config_path()
    typer.echo(f"CODEX_HOME: {codex_home()}")
    typer.echo(f"Config: {target}")

    try:
        binary = discover_codex_binary()
        typer.echo(f"Codex binary: {binary}")
        try:
            typer.echo(f"Codex version: {get_codex_version(binary)}")
        except CodexVersionError as exc:
            typer.echo(f"Codex version: unavailable ({exc})")
    except CodexBinaryNotFoundError as exc:
        typer.echo(f"Codex binary: unavailable ({exc})")

    layers = discover_user_layers(profile=profile)
    typer.echo(f"Discovered layers: {len(layers)}")
    for layer in layers:
        typer.echo(f"  {layer.precedence:03d} {layer.layer_type.value}: {layer.path}")

    parsed = load_config(target)
    if not parsed.valid_toml:
        _print_diagnostics(parsed)
        raise typer.Exit(code=1)

    config_map = _parsed_mapping(parsed)
    profiles = config_map.get("profiles")
    legacy_count = len(profiles) if isinstance(profiles, dict) else 0
    typer.echo("TOML: valid")
    typer.echo(f"Legacy profile tables: {legacy_count}")


@app.command()
def validate(
    config: Path = typer.Option(..., "--config", exists=False, help="Config file to validate."),
    schema_file: Path | None = typer.Option(
        None, "--schema-file", help="Pinned local schema; skips network acquisition."
    ),
    refresh_schema: bool = typer.Option(False, "--refresh-schema"),
) -> None:
    """Validate a Codex config against a pinned or cached official schema."""
    parsed = load_config(config)
    if not parsed.valid_toml:
        _print_diagnostics(parsed)
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

    diagnostics = validate_config(_parsed_mapping(parsed), schema, parsed.path)
    for diagnostic in diagnostics:
        key = f" [{diagnostic.key_path}]" if diagnostic.key_path else ""
        typer.echo(
            f"{diagnostic.severity.value.upper()} {diagnostic.kind.value}{key}: "
            f"{diagnostic.message}"
        )

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
        typer.echo(f"{item.key_path} type={item.value_type or 'unknown'}{enum}{default}")
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
            _print_diagnostics(parsed)
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
        if change.kind.value == "added":
            typer.echo(f"+ {change.key_path} = {change.after!r}")
        elif change.kind.value == "removed":
            typer.echo(f"- {change.key_path} = {change.before!r}")
        else:
            typer.echo(f"~ {change.key_path}: {change.before!r} -> {change.after!r}")
    typer.echo(f"Semantic changes: {len(result.changes)}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
