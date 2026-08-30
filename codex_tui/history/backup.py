from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from codex_tui.errors import BackupIntegrityError, StaleSourceError, UnsafePathError
from codex_tui.fs_safety import fsync_directory, read_regular_file_nofollow
from codex_tui.models import BackupManifest, BackupOperation
from codex_tui.paths import backup_root_dir

_MANIFEST_NAME = "manifest.json"


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_exclusive(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def _source_bucket(source: Path) -> str:
    normalized = str(source.expanduser().absolute()).encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:24]


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise UnsafePathError(f"Backup directory is not a real directory: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise UnsafePathError(
            f"Backup directory permits group/world access; require mode 0700: {path}"
        )


def _assert_manifest_under_root(path: Path, backup_root: Path | None) -> None:
    if backup_root is None:
        return
    root = backup_root.expanduser().absolute()
    try:
        resolved_root = root.resolve(strict=True)
        resolved_manifest = path.resolve(strict=True)
    except OSError as exc:
        raise BackupIntegrityError(f"Unable to resolve backup history path: {exc}") from exc
    if not resolved_manifest.is_relative_to(resolved_root):
        raise BackupIntegrityError(
            "Backup manifest is outside the trusted backup root "
            f"{resolved_root}: {resolved_manifest}"
        )


def create_backup(
    source_path: Path,
    *,
    backup_root: Path | None = None,
    expected_sha256: str | None = None,
    operation: BackupOperation = BackupOperation.MANUAL,
    schema_sha256: str | None = None,
    checkpoint_name: str | None = None,
    rollback_of: str | None = None,
) -> tuple[BackupManifest, Path]:
    """Create immutable backup bytes plus a self-contained JSON manifest."""

    source = source_path.expanduser().absolute()
    content, source_stat = read_regular_file_nofollow(source, role="backup source")
    source_sha = sha256_bytes(content)
    if expected_sha256 is not None and source_sha != expected_sha256:
        raise StaleSourceError(
            f"Source changed before backup: expected {expected_sha256}, observed {source_sha}"
        )

    root = (backup_root or backup_root_dir()).expanduser().absolute()
    _ensure_private_directory(root)

    bucket = root / _source_bucket(source)
    _ensure_private_directory(bucket)

    operation_id = uuid.uuid4().hex
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    record_dir = bucket / f"{stamp}-{operation_id}"
    record_dir.mkdir(mode=0o700)

    suffix = source.suffix if source.suffix else ".bin"
    backup_path = record_dir / f"source{suffix}"
    manifest_path = record_dir / _MANIFEST_NAME

    try:
        _write_exclusive(backup_path, content)
        backup_bytes, backup_stat = read_regular_file_nofollow(
            backup_path,
            role="backup payload",
        )
        backup_sha = sha256_bytes(backup_bytes)
        if backup_sha != source_sha or backup_bytes != content:
            raise BackupIntegrityError(
                f"Backup verification failed: source {source_sha}, backup {backup_sha}"
            )
        if stat.S_IMODE(backup_stat.st_mode) & 0o077:
            raise BackupIntegrityError("Backup payload permissions are broader than 0600")

        manifest = BackupManifest(
            operation_id=operation_id,
            operation=operation,
            created_at=datetime.now(UTC),
            source_path=source,
            backup_path=backup_path,
            source_sha256=source_sha,
            backup_sha256=backup_sha,
            source_size_bytes=len(content),
            source_mode=stat.S_IMODE(source_stat.st_mode),
            schema_sha256=schema_sha256,
            checkpoint_name=checkpoint_name,
            rollback_of=rollback_of,
        )
        serialized = (manifest.model_dump_json(indent=2) + "\n").encode("utf-8")
        _write_exclusive(manifest_path, serialized)

        fsync_directory(record_dir)
        fsync_directory(bucket)
        fsync_directory(root)
        return manifest, manifest_path
    except Exception:
        # Cleanup only artifacts created by this failed operation. Existing history is untouched.
        for path in (manifest_path, backup_path):
            with suppress(OSError):
                path.unlink(missing_ok=True)
        with suppress(OSError):
            record_dir.rmdir()
        raise


def load_backup_manifest(manifest_path: Path, *, backup_root: Path | None = None) -> BackupManifest:
    path = manifest_path.expanduser().absolute()
    _assert_manifest_under_root(path, backup_root)
    try:
        content, metadata = read_regular_file_nofollow(path, role="backup manifest")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise BackupIntegrityError("Backup manifest permissions permit group/world access")
        raw: Any = json.loads(content.decode("utf-8"))
        manifest = BackupManifest.model_validate(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise BackupIntegrityError(f"Invalid backup manifest {path}: {exc}") from exc

    if manifest.source_mode < 0 or manifest.source_mode & ~0o777:
        raise BackupIntegrityError(
            f"Backup manifest contains unsafe source permission bits: {oct(manifest.source_mode)}"
        )
    return manifest


def _read_and_verify_backup(
    manifest_path: Path,
    *,
    backup_root: Path | None = None,
) -> tuple[BackupManifest, bytes]:
    path = manifest_path.expanduser().absolute()
    manifest = load_backup_manifest(path, backup_root=backup_root)
    backup_path = manifest.backup_path.expanduser().absolute()

    try:
        manifest_dir = path.parent.resolve(strict=True)
        resolved_backup = backup_path.resolve(strict=True)
    except OSError as exc:
        raise BackupIntegrityError(f"Backup payload is unavailable: {backup_path}: {exc}") from exc

    if resolved_backup.parent != manifest_dir:
        raise BackupIntegrityError("Manifest backup path escapes its immutable record directory")

    try:
        backup_bytes, backup_stat = read_regular_file_nofollow(
            resolved_backup,
            role="backup payload",
        )
    except UnsafePathError as exc:
        raise BackupIntegrityError(str(exc)) from exc

    if stat.S_IMODE(backup_stat.st_mode) & 0o077:
        raise BackupIntegrityError("Backup payload permissions permit group/world access")

    observed = sha256_bytes(backup_bytes)
    if observed != manifest.backup_sha256:
        raise BackupIntegrityError(
            f"Backup hash mismatch: expected {manifest.backup_sha256}, observed {observed}"
        )
    if manifest.backup_sha256 != manifest.source_sha256:
        raise BackupIntegrityError("Backup manifest source and payload hashes disagree")
    if len(backup_bytes) != manifest.source_size_bytes:
        raise BackupIntegrityError("Backup payload size does not match manifest")
    return manifest, backup_bytes


def verify_backup_manifest(
    manifest_path: Path,
    *,
    backup_root: Path | None = None,
) -> BackupManifest:
    manifest, _ = _read_and_verify_backup(manifest_path, backup_root=backup_root)
    return manifest


def read_verified_backup(
    manifest_path: Path,
    *,
    backup_root: Path | None = None,
) -> tuple[BackupManifest, bytes]:
    return _read_and_verify_backup(manifest_path, backup_root=backup_root)


def list_manifest_paths(*, backup_root: Path | None = None) -> list[Path]:
    root = (backup_root or backup_root_dir()).expanduser().absolute()
    if not root.exists():
        return []
    metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise UnsafePathError(f"Refusing unsafe backup root: {root}")
    return sorted(root.rglob(_MANIFEST_NAME), reverse=True)
