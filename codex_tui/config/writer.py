from __future__ import annotations

import os
import stat
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

import tomlkit
from tomlkit.exceptions import ParseError

from codex_tui.errors import (
    CandidateValidationError,
    CreateRollbackError,
    PostWriteVerificationError,
    RollbackError,
    StaleSourceError,
    TargetExistsError,
    UnsafePathError,
    WriteRolledBackError,
)
from codex_tui.fs_safety import fsync_directory, read_regular_file_nofollow, target_lock
from codex_tui.history.backup import create_backup, read_verified_backup, sha256_bytes
from codex_tui.models import BackupOperation, CreateResult, WriteResult
from codex_tui.paths import backup_root_dir

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
    return read_regular_file_nofollow(target, role="managed target")


def _target_hash(target: Path) -> str:
    content, _ = _read_target_snapshot(target)
    return sha256_bytes(content)


def _write_temp_file(directory: Path, target_name: str, content: bytes, mode: int) -> Path:
    fd, temp_name = tempfile.mkstemp(prefix=f".{target_name}.codex-tui-", dir=directory)
    temp_path = Path(temp_name)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, mode)
        else:
            os.chmod(temp_path, mode)
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
        fsync_directory(target.parent)
    finally:
        temp_path.unlink(missing_ok=True)


def _assert_create_parent(parent: Path) -> None:
    try:
        metadata = parent.lstat()
    except OSError as exc:
        raise UnsafePathError(f"Unable to inspect create destination directory {parent}: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise UnsafePathError(f"Create destination parent is not a real directory: {parent}")


def _assert_target_absent(target: Path) -> None:
    try:
        target.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise UnsafePathError(f"Unable to inspect create-only target {target}: {exc}") from exc
    raise TargetExistsError(f"Create-only target already exists: {target}")


def _remove_created_target_if_same(
    target: Path,
    *,
    expected_identity: tuple[int, int],
) -> None:
    try:
        metadata = target.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise CreateRollbackError(f"Unable to inspect newly created target: {exc}") from exc

    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CreateRollbackError(
            "Newly created target changed type before create rollback; refusing to unlink it"
        )
    observed_identity = (metadata.st_dev, metadata.st_ino)
    if observed_identity != expected_identity:
        raise CreateRollbackError(
            "Newly created target changed identity before create rollback; refusing to unlink it"
        )

    try:
        target.unlink()
        fsync_directory(target.parent)
    except OSError as exc:
        raise CreateRollbackError(f"Unable to remove failed create target: {exc}") from exc

    try:
        target.lstat()
    except FileNotFoundError:
        return
    raise CreateRollbackError("Create rollback could not verify target removal")


def create_candidate(
    target_path: Path,
    candidate_bytes: bytes,
    *,
    candidate_validator: BytesValidator = validate_toml_bytes,
    post_create_validator: PathValidator | None = None,
    mode: int = 0o600,
    lock_timeout_seconds: float = 5.0,
) -> CreateResult:
    """Create a new config atomically without ever overwriting an existing target."""

    target = target_path.expanduser().absolute()
    if mode < 0 or mode & ~0o777:
        raise UnsafePathError(f"Refusing unsafe create mode: {oct(mode)}")
    if mode & 0o077:
        raise UnsafePathError(
            f"Create-only config mode must not permit group/world access: {oct(mode)}"
        )

    with target_lock(target, timeout_seconds=lock_timeout_seconds):
        _assert_create_parent(target.parent)
        _assert_target_absent(target)
        candidate_validator(candidate_bytes, target)
        candidate_sha = sha256_bytes(candidate_bytes)

        temp_path = _write_temp_file(target.parent, target.name, candidate_bytes, mode)
        linked = False
        temp_identity: tuple[int, int] | None = None
        try:
            temp_bytes, temp_stat = read_regular_file_nofollow(
                temp_path,
                role="create candidate temporary file",
            )
            temp_identity = (temp_stat.st_dev, temp_stat.st_ino)
            if sha256_bytes(temp_bytes) != candidate_sha or temp_bytes != candidate_bytes:
                raise CandidateValidationError("Temporary create candidate bytes changed before link")
            if stat.S_IMODE(temp_stat.st_mode) != mode:
                raise CandidateValidationError("Temporary create candidate mode changed before link")
            candidate_validator(temp_bytes, temp_path)

            _assert_target_absent(target)
            try:
                os.link(temp_path, target, follow_symlinks=False)
            except FileExistsError as exc:
                raise TargetExistsError(f"Create-only target appeared before link: {target}") from exc
            linked = True
            fsync_directory(target.parent)

            final_bytes, final_stat = _read_target_snapshot(target)
            final_identity = (final_stat.st_dev, final_stat.st_ino)
            if final_identity != temp_identity:
                raise PostWriteVerificationError(
                    "Create-only target identity does not match the prepared candidate"
                )
            final_sha = sha256_bytes(final_bytes)
            if final_sha != candidate_sha or final_bytes != candidate_bytes:
                raise PostWriteVerificationError("Create-only target bytes failed exact verification")
            if stat.S_IMODE(final_stat.st_mode) != mode:
                raise PostWriteVerificationError("Create-only target mode failed verification")
            candidate_validator(final_bytes, target)
            if post_create_validator is not None:
                post_create_validator(target)

            temp_path.unlink()
            fsync_directory(target.parent)
            return CreateResult(
                operation_id=uuid.uuid4().hex,
                target_path=target,
                candidate_sha256=candidate_sha,
                final_sha256=final_sha,
                mode=mode,
            )
        except Exception as exc:
            if linked and temp_identity is not None:
                try:
                    _remove_created_target_if_same(target, expected_identity=temp_identity)
                except CreateRollbackError as rollback_exc:
                    raise CreateRollbackError(
                        f"Create failed and rollback could not safely remove the new target: "
                        f"{rollback_exc}"
                    ) from exc
            raise
        finally:
            temp_path.unlink(missing_ok=True)


def _apply_candidate_locked(
    target: Path,
    candidate_bytes: bytes,
    *,
    expected_source_sha256: str,
    backup_root: Path | None,
    schema_sha256: str | None,
    candidate_validator: BytesValidator,
    post_replace_validator: PathValidator | None,
    backup_operation: BackupOperation,
    rollback_of: str | None,
    mode_override: int | None,
) -> WriteResult:
    before_bytes, before_stat = _read_target_snapshot(target)
    before_sha = sha256_bytes(before_bytes)
    if before_sha != expected_source_sha256:
        raise StaleSourceError(
            f"Target changed before write: expected {expected_source_sha256}, observed {before_sha}"
        )

    candidate_validator(candidate_bytes, target)
    candidate_sha = sha256_bytes(candidate_bytes)

    current_mode = stat.S_IMODE(before_stat.st_mode)
    if mode_override is not None:
        if mode_override < 0 or mode_override & ~0o777:
            raise UnsafePathError(f"Refusing unsafe requested mode: {oct(mode_override)}")
        broadened_bits = mode_override & ~current_mode
        if broadened_bits:
            raise UnsafePathError(
                "Refusing permission broadening during restore; "
                f"current={oct(current_mode)} requested={oct(mode_override)}"
            )
    mode = mode_override if mode_override is not None else current_mode

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

    temp_path = _write_temp_file(target.parent, target.name, candidate_bytes, mode)
    replaced = False
    operation_id = uuid.uuid4().hex
    trusted_backup_root = (backup_root or backup_root_dir()).expanduser().absolute()
    try:
        temp_bytes, _ = read_regular_file_nofollow(temp_path, role="candidate temporary file")
        candidate_validator(temp_bytes, temp_path)
        if sha256_bytes(temp_bytes) != candidate_sha:
            raise CandidateValidationError("Temporary candidate bytes changed before replacement")

        observed_immediately_before_replace = _target_hash(target)
        if observed_immediately_before_replace != before_sha:
            raise StaleSourceError(
                "Target changed immediately before atomic replacement; write aborted"
            )

        os.replace(temp_path, target)
        replaced = True
        fsync_directory(target.parent)

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
                verified_manifest, rollback_bytes = read_verified_backup(
                    backup_manifest_path,
                    backup_root=trusted_backup_root,
                )
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
    lock_timeout_seconds: float = 5.0,
) -> WriteResult:
    """Atomically replace an existing config with verified rollback protection."""

    target = target_path.expanduser().absolute()
    with target_lock(target, timeout_seconds=lock_timeout_seconds):
        return _apply_candidate_locked(
            target,
            candidate_bytes,
            expected_source_sha256=expected_source_sha256,
            backup_root=backup_root,
            schema_sha256=schema_sha256,
            candidate_validator=candidate_validator,
            post_replace_validator=post_replace_validator,
            backup_operation=backup_operation,
            rollback_of=rollback_of,
            mode_override=mode_override,
        )


def restore_from_manifest(
    manifest_path: Path,
    target_path: Path,
    *,
    expected_target_sha256: str,
    backup_root: Path | None = None,
    candidate_validator: BytesValidator = validate_toml_bytes,
    post_replace_validator: PathValidator | None = None,
    lock_timeout_seconds: float = 5.0,
) -> WriteResult:
    """Restore a verified snapshot while first backing up the current target state."""

    target = target_path.expanduser().absolute()
    trusted_backup_root = (backup_root or backup_root_dir()).expanduser().absolute()
    manifest, backup_bytes = read_verified_backup(
        manifest_path,
        backup_root=trusted_backup_root,
    )
    if manifest.source_path.expanduser().absolute() != target:
        raise UnsafePathError(
            "Refusing cross-target restore: manifest source does not match the requested target"
        )

    return apply_candidate(
        target,
        backup_bytes,
        expected_source_sha256=expected_target_sha256,
        backup_root=trusted_backup_root,
        schema_sha256=manifest.schema_sha256,
        candidate_validator=candidate_validator,
        post_replace_validator=post_replace_validator,
        backup_operation=BackupOperation.PRE_RESTORE,
        rollback_of=manifest.operation_id,
        mode_override=manifest.source_mode,
        lock_timeout_seconds=lock_timeout_seconds,
    )
