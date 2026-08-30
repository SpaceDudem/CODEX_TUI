from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from codex_tui.codex.binary import CodexBinaryNotFoundError, discover_codex_binary
from codex_tui.config.validator import validate_config
from codex_tui.models import Diagnostic, Severity
from codex_tui.paths import codex_home, user_config_path
from codex_tui.profiles.compare import ProfileComparisonError, compare_profile
from codex_tui.profiles.discover import discover_profiles
from codex_tui.profiles.launch import ProfileLaunchError, build_profile_argv, launch_profile
from codex_tui.profiles.migrate import plan_legacy_profile_migration
from codex_tui.profiles.names import InvalidProfileNameError, PROFILE_SUFFIX, validate_profile_name
from codex_tui.schema.fetch import SchemaUnavailableError, acquire_schema
from codex_tui.security import display_validation_message, display_value

profiles_app = typer.Typer(
    name="profiles",
    no_args_is_help=True,
    help="Discover, compare, migrate, and launch Codex profile-v2 configurations.",
)


def _print_diagnostic(diagnostic: Diagnostic) -> None:
    key = f" [{diagnostic.key_path}]" if diagnostic.key_path else ""
    source = f" {diagnostic.source_path}" if diagnostic.source_path else ""
    message = display_validation_message(diagnostic.key_path, diagnostic.message)
    typer.echo(f"{diagnostic.severity.value.upper()} {diagnostic.kind.value}{key}{source}: {message}")


def _schema(schema_file: Path | None) -> dict[str, Any]:
    if schema_file is not None:
        raw: Any = json.loads(schema_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("schema root must be an object")
        return raw
    schema, _, _ = acquire_schema()
    return schema


@profiles_app.command("list")
def list_profiles(
    home: Path | None = typer.Option(None, "--codex-home", help="Override CODEX_HOME."),
) -> None:
    """List profile-v2 files directly under CODEX_HOME."""
    root = (home or codex_home()).expanduser().absolute()
    profiles, diagnostics = discover_profiles(root)
    for diagnostic in diagnostics:
        _print_diagnostic(diagnostic)

    for profile in profiles:
        state = "valid" if profile.valid_toml else "invalid-toml"
        typer.echo(f"{profile.name}: {state} {profile.path}")
        for diagnostic in profile.diagnostics:
            _print_diagnostic(diagnostic)
    typer.echo(f"Profiles: {len(profiles)}; discovery diagnostics: {len(diagnostics)}")


@profiles_app.command("diff")
def diff_profile(
    name: str = typer.Argument(..., help="Profile name."),
    home: Path | None = typer.Option(None, "--codex-home", help="Override CODEX_HOME."),
) -> None:
    """Show the semantic changes introduced by one profile over base config."""
    root = (home or codex_home()).expanduser().absolute()
    try:
        validate_profile_name(name)
        comparison = compare_profile(
            root / "config.toml",
            root / f"{name}{PROFILE_SUFFIX}",
            name=name,
        )
    except (InvalidProfileNameError, ProfileComparisonError) as exc:
        typer.echo(f"ERROR profile diff: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if comparison.diff.is_empty:
        typer.echo("Profile introduces no semantic changes.")
        return

    for change in comparison.diff.changes:
        before = display_value(change.key_path, change.before)
        after = display_value(change.key_path, change.after)
        if change.kind.value == "added":
            typer.echo(f"+ {change.key_path} = {after}")
        elif change.kind.value == "removed":
            typer.echo(f"- {change.key_path} = {before}")
        else:
            typer.echo(f"~ {change.key_path}: {before} -> {after}")
    typer.echo(f"Profile changes: {len(comparison.diff.changes)}")


@profiles_app.command("plan-migration")
def plan_migration(
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Legacy base config; defaults to $CODEX_HOME/config.toml.",
    ),
    schema_file: Path | None = typer.Option(
        None,
        "--schema-file",
        help="Pinned schema for candidate validation; otherwise use cached official schema.",
    ),
    validate_schema: bool = typer.Option(
        True,
        "--validate-schema/--no-validate-schema",
        help="Validate each generated candidate against the selected Codex schema.",
    ),
) -> None:
    """Plan legacy [profiles.*] conversion without writing candidate files."""
    source = (config or user_config_path()).expanduser().absolute()
    plan = plan_legacy_profile_migration(source)
    for diagnostic in plan.diagnostics:
        _print_diagnostic(diagnostic)

    schema: dict[str, Any] | None = None
    if validate_schema and plan.candidates:
        try:
            schema = _schema(schema_file)
        except (SchemaUnavailableError, OSError, ValueError, json.JSONDecodeError) as exc:
            typer.echo(f"ERROR schema: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    errors = sum(1 for item in plan.diagnostics if item.severity is Severity.ERROR)
    for candidate in plan.candidates:
        typer.echo(f"{candidate.name} -> {candidate.target_path}")
        for diagnostic in candidate.diagnostics:
            _print_diagnostic(diagnostic)
            if diagnostic.severity is Severity.ERROR:
                errors += 1

        if schema is not None:
            import tomlkit

            mapping = dict(tomlkit.parse(candidate.content).unwrap())
            diagnostics = validate_config(mapping, schema, candidate.target_path)
            for diagnostic in diagnostics:
                _print_diagnostic(diagnostic)
                if diagnostic.severity.value in {"error", "blocking"}:
                    errors += 1

    typer.echo(
        f"Migration candidates: {len(plan.candidates)}; errors: {errors}; writes performed: 0"
    )
    if errors:
        raise typer.Exit(code=1)


@profiles_app.command("launch")
def launch(
    name: str = typer.Argument(..., help="Profile name."),
    home: Path | None = typer.Option(None, "--codex-home", help="Override CODEX_HOME."),
    cwd: Path | None = typer.Option(None, "--cwd", help="Working directory for launched Codex."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print argv without launching Codex."),
) -> None:
    """Launch Codex using an existing valid profile-v2 file."""
    root = (home or codex_home()).expanduser().absolute()
    try:
        validate_profile_name(name)
    except InvalidProfileNameError as exc:
        typer.echo(f"ERROR profile launch: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    matches, discovery_diagnostics = discover_profiles(root)
    for diagnostic in discovery_diagnostics:
        _print_diagnostic(diagnostic)
    selected = next((profile for profile in matches if profile.name == name), None)
    if selected is None:
        typer.echo(f"ERROR profile launch: profile {name!r} was not found under {root}", err=True)
        raise typer.Exit(code=1)
    if not selected.valid_toml:
        for diagnostic in selected.diagnostics:
            _print_diagnostic(diagnostic)
        raise typer.Exit(code=1)

    try:
        binary = discover_codex_binary()
        argv = build_profile_argv(binary, name)
    except (CodexBinaryNotFoundError, InvalidProfileNameError) as exc:
        typer.echo(f"ERROR profile launch: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if dry_run:
        typer.echo("argv: " + " ".join(json.dumps(part) for part in argv))
        return

    try:
        returncode = launch_profile(binary, name, cwd=cwd)
    except ProfileLaunchError as exc:
        typer.echo(f"ERROR profile launch: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if returncode:
        raise typer.Exit(code=returncode)
