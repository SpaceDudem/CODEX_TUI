from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from codex_tui.config.writer import apply_candidate, restore_from_manifest
from codex_tui.errors import BackupIntegrityError, TargetLockError, UnsafePathError
from codex_tui.fs_safety import fsync_directory, target_lock
from codex_tui.history.backup import create_backup, sha256_bytes


def _write(path: Path, text: str, mode: int = 0o600) -> bytes:
    content = text.encode("utf-8")
    path.write_bytes(content)
    path.chmod(mode)
    return content


def test_apply_uses_single_descriptor_safe_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "config.toml"
    before = _write(target, 'model = "gpt-a"\n')

    def forbidden_read_bytes(_: Path) -> bytes:
        raise AssertionError("Path.read_bytes must not be used for managed target snapshots")

    monkeypatch.setattr(Path, "read_bytes", forbidden_read_bytes)
    result = apply_candidate(
        target,
        b'model = "gpt-b"\n',
        expected_source_sha256=sha256_bytes(before),
        backup_root=tmp_path / "history",
    )
    assert result.final_sha256 == sha256_bytes(b'model = "gpt-b"\n')


def test_target_lock_blocks_competing_managed_writer(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    before = _write(target, 'model = "gpt-a"\n')

    with target_lock(target), pytest.raises(TargetLockError):
        apply_candidate(
            target,
            b'model = "gpt-b"\n',
            expected_source_sha256=sha256_bytes(before),
            backup_root=tmp_path / "history",
            lock_timeout_seconds=0.01,
        )

    assert target.read_bytes() == before


def test_temp_file_mode_falls_back_when_fchmod_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "config.toml"
    before = _write(target, 'model = "gpt-a"\n', 0o640)
    monkeypatch.delattr(os, "fchmod", raising=False)

    apply_candidate(
        target,
        b'model = "gpt-b"\n',
        expected_source_sha256=sha256_bytes(before),
        backup_root=tmp_path / "history",
    )
    assert target.stat().st_mode & 0o777 == 0o640


def test_directory_fsync_propagates_real_io_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_: int) -> None:
        raise OSError(errno.EIO, "injected I/O failure")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError) as caught:
        fsync_directory(tmp_path)
    assert caught.value.errno == errno.EIO


def test_directory_fsync_suppresses_only_unsupported_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unsupported(_: int) -> None:
        raise OSError(errno.EINVAL, "directory fsync unsupported")

    monkeypatch.setattr(os, "fsync", unsupported)
    fsync_directory(tmp_path)


def test_restore_rejects_permission_broadening(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    _write(target, 'model = "gpt-historical"\n', 0o644)
    backup_root = tmp_path / "history"
    _, manifest_path = create_backup(target, backup_root=backup_root)

    current = _write(target, 'model = "gpt-current"\n', 0o600)
    with pytest.raises(UnsafePathError, match="permission broadening"):
        restore_from_manifest(
            manifest_path,
            target,
            expected_target_sha256=sha256_bytes(current),
            backup_root=backup_root,
        )

    assert target.read_bytes() == current
    assert target.stat().st_mode & 0o777 == 0o600


def test_restore_rejects_manifest_outside_trusted_backup_root(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    historical = _write(target, 'model = "gpt-historical"\n')
    actual_root = tmp_path / "actual-history"
    _, manifest_path = create_backup(target, backup_root=actual_root)

    trusted_root = tmp_path / "trusted-history"
    trusted_root.mkdir(mode=0o700)
    current = _write(target, 'model = "gpt-current"\n')

    with pytest.raises(BackupIntegrityError, match="outside the trusted backup root"):
        restore_from_manifest(
            manifest_path,
            target,
            expected_target_sha256=sha256_bytes(current),
            backup_root=trusted_root,
        )

    assert target.read_bytes() == current
    assert historical != current


def test_restore_rejects_cross_target_manifest(tmp_path: Path) -> None:
    source = tmp_path / "source.toml"
    _write(source, 'model = "gpt-source"\n')
    backup_root = tmp_path / "history"
    _, manifest_path = create_backup(source, backup_root=backup_root)

    target = tmp_path / "target.toml"
    current = _write(target, 'model = "gpt-target"\n')
    with pytest.raises(UnsafePathError, match="cross-target restore"):
        restore_from_manifest(
            manifest_path,
            target,
            expected_target_sha256=sha256_bytes(current),
            backup_root=backup_root,
        )

    assert target.read_bytes() == current
