from __future__ import annotations

import hashlib
import json
import os
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from codex_tui.errors import BackupIntegrityError, StaleSourceError, UnsafePathError
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


def _read_regular_file(path: Path) -> tuple[bytes, os.stat_result]:
    target = path.expanduser().absolute()
    try:
        initial = target.lstat()
    except OSError as exc:
        raise UnsafePathError(f"Unable to inspect source {target}: {exc}") from exc
    if stat.S_ISLNK(initial.st_mode):
        raise UnsafePathError(f"Refusing symbolic-link source: {target}")
    if not stat.S_ISREG(initial.st_mode):
        raise UnsafePathError(f"Managed source is not a regular file: {target}")

    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise UnsafePathError(f"Unable to open source safely {target}: {exc}") from exc

    try:
        current = os.fstat(fd)
        if not stat.S_ISREG(current.st_mode):
            raise UnsafePathError(f"Managed source changed type while opening: {target}")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            content = handle.read()
    finally:
        os.close(fd)
    return content, current


def _write_exclusive(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
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
    content, source_stat = _read_regular_file(source)
    source_sha = sha256_bytes(content)
    if expected_sha256 is not None and source_sha != expected_sha256:
        raise StaleSourceError(
            f"Source changed before backup: expected {expected_sha256}, observed {source_sha}"
        )

    root = (backup_root or backup_root_dir()).expanduser().absolute()
    if root.exists() and root.is_symlink():
        raise UnsafePathError(f"Refusing symbolic-link backup root: {root}")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)

    bucket = root / _source_bucket(source)
    bucket.mkdir(parents=True, exist_ok=True, mode=0o700)

    operation_id = uuid.uuid4().hex
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    record_dir = bucket / f"{stamp}-{operation_id}"
    record_dir.mkdir(mode=0o700)

    suffix = source.suffix if source.suffix else ".bin"
    backup_path = record_dir / f"source{suffix}"
    manifest_path = record_dir / _MANIFEST_NAME

    try:
        _write_exclusive(backup_path, content)
        backup_sha = sha256_file(backup_path)
        if backup_sha != source_sha:
            raise BackupIntegrityError(
                f"Backup verification failed: source {source_sha}, backup {backup_sha}"
            )

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
        return manifest, manifest_path
    except Exception:
        # Cleanup only artifacts created by this failed operation. Existing history is untouched.
        for path in (manifest_path, backup_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            record_dir.rmdir()
        except OSError:
            pass
        raise


def load_backup_manifest(manifest_path: Path) -> BackupManifest:
    path = manifest_path.expanduser().absolute()
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
        return BackupManifest.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise BackupIntegrityError(f"Invalid backup manifest {path}: {exc}") from exc


def verify_backup_manifest(manifest_path: Path) -> BackupManifest:
    path = manifest_path.expanduser().absolute()
    manifest = load_backup_manifest(path)
    backup_path = manifest.backup_path.expanduser().absolute()

    try:
        manifest_dir = path.parent.resolve(strict=True)
        if backup_path.is_symlink():
            raise BackupIntegrityError(f"Backup payload is a symbolic link: {backup_path}")
        resolved_backup = backup_path.resolve(strict=True)
    except OSError as exc:
        raise BackupIntegrityError(f"Backup payload is unavailable: {backup_path}: {exc}") from exc

    if resolved_backup.parent != manifest_dir:
        raise BackupIntegrityError(
            "Manifest backup path escapes its immutable record directory"
        )
    if not resolved_backup.is_file():
        raise BackupIntegrityError(f"Backup payload is not a regular file: {resolved_backup}")

    observed = sha256_file(resolved_backup)
    if observed != manifest.backup_sha256:
        raise BackupIntegrityError(
            f"Backup hash mismatch: expected {manifest.backup_sha256}, observed {observed}"
        )
    if manifest.backup_sha256 != manifest.source_sha256:
        raise BackupIntegrityError(
            "Backup manifest source and payload hashes disagree"
        )
    if resolved_backup.stat().st_size != manifest.source_size_bytes:
        raise BackupIntegrityError("Backup payload size does not match manifest")
    return manifest


def read_verified_backup(manifest_path: Path) -> tuple[BackupManifest, bytes]:
    manifest = verify_backup_manifest(manifest_path)
    return manifest, manifest.backup_path.read_bytes()


def list_manifest_paths(*, backup_root: Path | None = None) -> list[Path]:
    root = (backup_root or backup_root_dir()).expanduser().absolute()
    if not root.exists():
        return []
    if root.is_symlink():
        raise UnsafePathError(f"Refusing symbolic-link backup root: {root}")
    return sorted(root.rglob(_MANIFEST_NAME), reverse=True)
