from __future__ import annotations

import json
import stat
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import tomlkit
import typer

from codex_tui.config.diff import semantic_diff
from codex_tui.config.validator import validate_config
from codex_tui.config.writer import apply_candidate, restore_from_manifest, validate_toml_bytes
from codex_tui.errors import CandidateValidationError, CodexTuiError
from codex_tui.history.backup import (
    create_backup,
    list_manifest_paths,
    load_backup_manifest,
    sha256_bytes,
    verify_backup_manifest,
)
from codex_tui.models import BackupOperation, LayerType
from codex_tui.paths import backup_root_dir, user_config_path
from codex_tui.schema.fetch import SchemaUnavailableError, acquire_schema
from codex_tui.security import display_value

BytesValidator = Callable[[bytes, Path], None]


def _target_path(config: Path | None) -> Path:
    return (config or user_config_path()).expanduser().absolute()


def _trusted_backup_root(backup_root: Path | None) -> Path:
    return (backup_root or backup_root_dir()).expanduser().absolute()


def _read_regular_candidate(path: Path) -> bytes:
    candidate = path.expanduser().absolute()
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise CandidateValidationError(f"Unable to inspect candidate {candidate}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise CandidateValidationError(f"Refusing symbolic-link candidate: {candidate}")
    if not stat.S_ISREG(metadata.st_mode):
        raise CandidateValidationError(f"Candidate is not a regular file: {candidate}")
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise CandidateValidationError(f"Unable to read candidate {candidate}: {exc}") from exc


def _mapping_from_bytes(content: bytes, source_path: Path) -> dict[str, Any]:
    validate_toml_bytes(content, source_path)
    document = tomlkit.parse(content.decode("utf-8"))
    return dict(document.unwrap())


def _load_schema(
    schema_file: Path | None,
    *,
    refresh_schema: bool,
) -> tuple[dict[str, Any], str]:
    if schema_file is not None:
        path = schema_file.expanduser().absolute()
        raw = path.read_bytes()
        parsed: Any = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("schema root must be an object")
        return parsed, sha256_bytes(raw)

    schema, snapshot, _ = acquire_schema(refresh=refresh_schema)
    return schema, snapshot.sha256


def _schema_bytes_validator(
    schema: Mapping[str, Any],
    *,
    layer_type: LayerType | None,
) -> BytesValidator:
    def validate(content: bytes, source_path: Path) -> None:
        mapping = _mapping_from_bytes(content, source_path)
        diagnostics = validate_config(mapping, schema, source_path, layer_type=layer_type)
        errors = [
            item
            for item in diagnostics
            if item.severity.value in {"error", "blocking"}
        ]
        if errors:
            summary = "; ".join(
                f"{item.kind.value}{f' [{item.key_path}]' if item.key_path else ''}: "
                f"{item.message}"
                for item in errors[:8]
            )
            if len(errors) > 8:
                summary += f"; ... {len(errors) - 8} more"
            raise CandidateValidationError(
                f"Candidate failed pinned Codex schema validation: {summary}"
            )

    return validate


def _confirm(message: str, *, yes: bool) -> None:
    if yes:
        return
    if not typer.confirm(message, default=False):
        raise typer.Abort()


def _print_semantic_preview(target: Path, candidate_bytes: bytes) -> int:
    try:
        before_bytes = target.read_bytes()
    except OSError as exc:
        raise CandidateValidationError(f"Unable to read current config {target}: {exc}") from exc
    before = _mapping_from_bytes(before_bytes, target)
    after = _mapping_from_bytes(candidate_bytes, Path("<candidate>"))
    diff = semantic_diff(target, before, Path("<candidate>"), after)
    if diff.is_empty:
        typer.echo("No semantic changes.")
        return 0

    typer.echo("Proposed semantic changes:")
    for change in diff.changes:
        before_value = display_value(change.key_path, change.before)
        after_value = display_value(change.key_path, change.after)
        if change.kind.value == "added":
            typer.echo(f"  + {change.key_path} = {after_value}")
        elif change.kind.value == "removed":
            typer.echo(f"  - {change.key_path} = {before_value}")
        else:
            typer.echo(f"  ~ {change.key_path}: {before_value} -> {after_value}")
    typer.echo(f"Semantic changes: {len(diff.changes)}")
    return len(diff.changes)


def backup_command(
    config: Path | None = typer.Option(None, "--config", help="Config to snapshot."),
    backup_root: Path | None = typer.Option(
        None,
        "--backup-root",
        help="Override backup root.",
    ),
    expected_sha: str | None = typer.Option(
        None,
        "--expected-sha",
        help="Optional concurrency guard; backup fails if the source hash differs.",
    ),
    checkpoint: str | None = typer.Option(
        None,
        "--checkpoint",
        help="Optional checkpoint name.",
    ),
) -> None:
    """Create an immutable byte-exact recovery snapshot."""
    target = _target_path(config)
    try:
        manifest, manifest_path = create_backup(
            target,
            backup_root=backup_root,
            expected_sha256=expected_sha,
            operation=BackupOperation.MANUAL,
            checkpoint_name=checkpoint,
        )
    except CodexTuiError as exc:
        typer.echo(f"ERROR backup: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Backup manifest: {manifest_path}")
    typer.echo(f"Source: {manifest.source_path}")
    typer.echo(f"Source SHA-256: {manifest.source_sha256}")
    typer.echo(f"Payload SHA-256: {manifest.backup_sha256}")
    if manifest.checkpoint_name:
        typer.echo(f"Checkpoint: {manifest.checkpoint_name}")


def history_command(
    backup_root: Path | None = typer.Option(
        None,
        "--backup-root",
        help="Override backup root.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Only show snapshots for this source.",
    ),
    verify: bool = typer.Option(
        True,
        "--verify/--no-verify",
        help="Verify payload integrity.",
    ),
) -> None:
    """List recovery manifests without modifying them."""
    wanted = _target_path(config) if config is not None else None
    trusted_root = _trusted_backup_root(backup_root)
    try:
        paths = list_manifest_paths(backup_root=trusted_root)
    except CodexTuiError as exc:
        typer.echo(f"ERROR history: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    shown = 0
    invalid = 0
    for path in paths:
        try:
            if verify:
                manifest = verify_backup_manifest(path, backup_root=trusted_root)
            else:
                manifest = load_backup_manifest(path, backup_root=trusted_root)
        except CodexTuiError as exc:
            invalid += 1
            typer.echo(f"INVALID {path}: {exc}")
            continue
        if wanted is not None and manifest.source_path.expanduser().absolute() != wanted:
            continue
        shown += 1
        checkpoint = f" checkpoint={manifest.checkpoint_name!r}" if manifest.checkpoint_name else ""
        rollback = f" rollback_of={manifest.rollback_of}" if manifest.rollback_of else ""
        typer.echo(
            f"{manifest.created_at.isoformat()} {manifest.operation.value} "
            f"sha256={manifest.source_sha256}{checkpoint}{rollback}"
        )
        typer.echo(f"  source: {manifest.source_path}")
        typer.echo(f"  manifest: {path}")

    typer.echo(f"History entries: {shown}; invalid: {invalid}")
    if invalid:
        raise typer.Exit(code=1)


def restore_command(
    manifest: Path = typer.Option(..., "--manifest", help="Verified manifest to restore."),
    config: Path | None = typer.Option(None, "--config", help="Target config to replace."),
    expected_sha: str = typer.Option(
        ...,
        "--expected-sha",
        help="Required SHA-256 of the target state reviewed before restore.",
    ),
    backup_root: Path | None = typer.Option(
        None,
        "--backup-root",
        help="Override backup root.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Confirm the destructive replacement.",
    ),
) -> None:
    """Restore a verified snapshot after protecting the current state."""
    target = _target_path(config)
    trusted_root = _trusted_backup_root(backup_root)
    try:
        historical = verify_backup_manifest(manifest, backup_root=trusted_root)
    except CodexTuiError as exc:
        typer.echo(f"ERROR restore: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Restore source SHA-256: {historical.source_sha256}")
    typer.echo(f"Target: {target}")
    _confirm("Replace the target with this verified snapshot?", yes=yes)

    try:
        result = restore_from_manifest(
            manifest,
            target,
            expected_target_sha256=expected_sha,
            backup_root=trusted_root,
        )
    except CodexTuiError as exc:
        typer.echo(f"ERROR restore: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Restored: {result.target_path}")
    typer.echo(f"Final SHA-256: {result.final_sha256}")
    typer.echo(f"Pre-restore backup: {result.backup_manifest_path}")


def apply_command(
    candidate: Path = typer.Option(..., "--candidate", help="Candidate TOML file to apply."),
    config: Path | None = typer.Option(None, "--config", help="Target config to replace."),
    expected_sha: str = typer.Option(
        ...,
        "--expected-sha",
        help="Required SHA-256 of the target state reviewed before apply.",
    ),
    schema_file: Path | None = typer.Option(
        None,
        "--schema-file",
        help="Pinned local Codex schema; otherwise use the cached official schema.",
    ),
    refresh_schema: bool = typer.Option(False, "--refresh-schema"),
    scope: LayerType | None = typer.Option(
        None,
        "--scope",
        help="Optional target layer scope for scope-specific validation.",
    ),
    backup_root: Path | None = typer.Option(
        None,
        "--backup-root",
        help="Override backup root.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Confirm the destructive replacement.",
    ),
) -> None:
    """Validate, preview, back up, atomically apply, verify, and rollback on failure."""
    target = _target_path(config)
    try:
        candidate_bytes = _read_regular_candidate(candidate)
        schema, schema_sha = _load_schema(schema_file, refresh_schema=refresh_schema)
        validator = _schema_bytes_validator(schema, layer_type=scope)
        validator(candidate_bytes, candidate)
        changes = _print_semantic_preview(target, candidate_bytes)
    except SchemaUnavailableError as exc:
        typer.echo(f"ERROR runtime: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except (CodexTuiError, OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        typer.echo(f"ERROR apply: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if changes == 0:
        return

    typer.echo(f"Target concurrency token: {expected_sha}")
    typer.echo(f"Schema SHA-256: {schema_sha}")
    _confirm("Apply these changes to the target config?", yes=yes)

    try:
        result = apply_candidate(
            target,
            candidate_bytes,
            expected_source_sha256=expected_sha,
            backup_root=backup_root,
            schema_sha256=schema_sha,
            candidate_validator=validator,
        )
    except CodexTuiError as exc:
        typer.echo(f"ERROR apply: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Applied: {result.target_path}")
    typer.echo(f"Before SHA-256: {result.before_sha256}")
    typer.echo(f"Final SHA-256: {result.final_sha256}")
    typer.echo(f"Recovery manifest: {result.backup_manifest_path}")
