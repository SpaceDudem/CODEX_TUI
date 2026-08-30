from __future__ import annotations

import os
import stat
import tempfile
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import tomlkit
from tomlkit.exceptions import ParseError

from codex_tui.errors import (
    CandidateValidationError,
    PostWriteVerificationError,
    RollbackError,
    StaleSourceError,
    UnsafePathError,
    WriteRolledBackError,
)
from codex_tui.history.backup import (
    create_backup,
    read_verified_backup,
    sha256_bytes,
)
from codex_tui.models import BackupOperation, WriteResult

BytesValidator = Callable[[bytes, Path], None]
PathValidator = Callable[[Path], None]


def validate_toml_bytes(content: bytes, source_path: Path) -> None:
    try:
        text = content.decode("utf-8")
        tomlkit.parse(text)
    except (UnicodeDecodeError, ParseError) as exc:
        raise CandidateValidationError(
            f"Candidate TOML is invalid for {source_path}: {exc}"
        ) from exc


def _read_target_snapshot(target: Path) -> tuple[bytes, os.stat_result]:
    path = target.expanduser().absolute()
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise UnsafePathError(f"Unable to inspect target {path}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode):
        raise UnsafePathError(f"Refusing symbolic-link target: {path}")
    if not stat.S_ISREG(metadata.st_mode):
        raise UnsafePathError(f"Managed target is not a regular file: {path}")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise UnsafePathError(f"Unable to read target {path}: {exc}") from exc
    return content, metadata


def _target_hash(target: Path) -> str:
    content, _ = _read_target_snapshot(target)
    return sha256_bytes(content)


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
    except OSError:
        return
    try:
        with suppress(OSError):
            os.fsync(fd)
    finally:
        os.close(fd)


def _write_temp_file(directory: Path, target_name: str, content: bytes, mode: int) -> Path:
    fd, temp_name = tempfile.mkstemp(prefix=f".{target_name}.codex-tui-", dir=directory)
    temp_path = Path(temp_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        os.close(fd)
        temp_path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)
    return temp_path


def _atomic_replace_raw(target: Path, content: bytes, *, mode: int) -> None:
    temp_path = _write_temp_file(target.parent, target.name, content, mode)
    try:
        os.replace(temp_path, target)
        _fsync_directory(target.parent)
    finally:
        temp_path.unlink(missing_ok=True)


def apply_candidate(
    target_path: Path,
    candidate_bytes: bytes,
    *,
    expected_source_sha256: str,
    backup_root: Path | None = None,
    schema_sha256: str | None = None,
    candidate_validator: BytesValidator = validate_toml_bytes,
    post_replace_validator: PathValidator | None = None,
    backup_operation: BackupOperation = BackupOperation.PRE_WRITE,
    rollback_of: str | None = None,
    mode_override: int | None = None,
) -> WriteResult:
    """Atomically replace an existing config with verified rollback protection."""

    target = target_path.expanduser().absolute()
    before_bytes, before_stat = _read_target_snapshot(target)
    before_sha = sha256_bytes(before_bytes)
    if before_sha != expected_source_sha256:
        raise StaleSourceError(
            f"Target changed before write: expected {expected_source_sha256}, observed {before_sha}"
        )

    candidate_validator(candidate_bytes, target)
    candidate_sha = sha256_bytes(candidate_bytes)

    backup_manifest, backup_manifest_path = create_backup(
        target,
        backup_root=backup_root,
        expected_sha256=before_sha,
        operation=backup_operation,
        schema_sha256=schema_sha256,
        rollback_of=rollback_of,
    )

    observed_before_replace = _target_hash(target)
    if observed_before_replace != before_sha:
        raise StaleSourceError(
            "Target changed while backup was being prepared; write aborted before replacement"
        )

    mode = mode_override if mode_override is not None else stat.S_IMODE(before_stat.st_mode)
    temp_path = _write_temp_file(target.parent, target.name, candidate_bytes, mode)
    replaced = False
    operation_id = uuid.uuid4().hex
    try:
        # Validate exactly what was flushed to the same filesystem before replacement.
        candidate_validator(temp_path.read_bytes(), temp_path)

        observed_immediately_before_replace = _target_hash(target)
        if observed_immediately_before_replace != before_sha:
            raise StaleSourceError(
                "Target changed immediately before atomic replacement; write aborted"
            )

        os.replace(temp_path, target)
        replaced = True
        _fsync_directory(target.parent)

        final_bytes, final_stat = _read_target_snapshot(target)
        final_sha = sha256_bytes(final_bytes)
        if final_sha != candidate_sha:
            raise PostWriteVerificationError(
                f"Post-write hash mismatch: expected {candidate_sha}, observed {final_sha}"
            )
        if stat.S_IMODE(final_stat.st_mode) != mode:
            raise PostWriteVerificationError(
                "Post-write permission mode differs from the requested mode"
            )
        candidate_validator(final_bytes, target)
        if post_replace_validator is not None:
            post_replace_validator(target)

        return WriteResult(
            operation_id=operation_id,
            target_path=target,
            backup_manifest_path=backup_manifest_path,
            before_sha256=before_sha,
            candidate_sha256=candidate_sha,
            final_sha256=final_sha,
        )
    except Exception as exc:
        if replaced:
            try:
                verified_manifest, rollback_bytes = read_verified_backup(backup_manifest_path)
                _atomic_replace_raw(
                    target,
                    rollback_bytes,
                    mode=verified_manifest.source_mode,
                )
                restored_bytes, restored_stat = _read_target_snapshot(target)
                restored_sha = sha256_bytes(restored_bytes)
                if restored_sha != before_sha or restored_bytes != before_bytes:
                    raise RollbackError("Rollback bytes failed exact verification")
                if stat.S_IMODE(restored_stat.st_mode) != backup_manifest.source_mode:
                    raise RollbackError("Rollback permission mode failed verification")
            except Exception as rollback_exc:
                raise RollbackError(
                    f"Write failed and automatic rollback could not be verified: {rollback_exc}"
                ) from rollback_exc
            raise WriteRolledBackError(
                f"Write failed after replacement; original bytes restored: {exc}",
                backup_manifest_path=backup_manifest_path,
            ) from exc
        raise
    finally:
        temp_path.unlink(missing_ok=True)


def restore_from_manifest(
    manifest_path: Path,
    target_path: Path,
    *,
    expected_target_sha256: str,
    backup_root: Path | None = None,
    candidate_validator: BytesValidator = validate_toml_bytes,
    post_replace_validator: PathValidator | None = None,
) -> WriteResult:
    """Restore a verified snapshot while first backing up the current target state."""

    manifest, backup_bytes = read_verified_backup(manifest_path)
    return apply_candidate(
        target_path,
        backup_bytes,
        expected_source_sha256=expected_target_sha256,
        backup_root=backup_root,
        schema_sha256=manifest.schema_sha256,
        candidate_validator=candidate_validator,
        post_replace_validator=post_replace_validator,
        backup_operation=BackupOperation.PRE_RESTORE,
        rollback_of=manifest.operation_id,
        mode_override=manifest.source_mode,
    )
