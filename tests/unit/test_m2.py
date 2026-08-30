from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from codex_tui.config.writer import apply_candidate, restore_from_manifest
from codex_tui.errors import (
    BackupIntegrityError,
    CandidateValidationError,
    StaleSourceError,
    UnsafePathError,
    WriteRolledBackError,
)
from codex_tui.history.backup import (
    create_backup,
    list_manifest_paths,
    read_verified_backup,
    sha256_bytes,
    verify_backup_manifest,
)
from codex_tui.models import BackupOperation


def _write_config(path: Path, text: str, mode: int = 0o640) -> bytes:
    content = text.encode("utf-8")
    path.write_bytes(content)
    path.chmod(mode)
    return content


def test_backup_is_byte_exact_and_manifest_is_verifiable(tmp_path: Path) -> None:
    source = tmp_path / "config.toml"
    original = _write_config(source, '# retained comment\nmodel = "gpt-a"\n', 0o640)
    backup_root = tmp_path / "history"

    manifest, manifest_path = create_backup(
        source,
        backup_root=backup_root,
        checkpoint_name="baseline",
    )

    assert manifest.source_sha256 == sha256_bytes(original)
    assert manifest.backup_sha256 == manifest.source_sha256
    assert manifest.source_mode == 0o640
    assert manifest.checkpoint_name == "baseline"
    assert manifest.backup_path.read_bytes() == original
    assert stat.S_IMODE(manifest.backup_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o600
    assert verify_backup_manifest(manifest_path) == manifest
    assert list_manifest_paths(backup_root=backup_root) == [manifest_path]


def test_tampered_backup_fails_integrity_verification(tmp_path: Path) -> None:
    source = tmp_path / "config.toml"
    _write_config(source, 'model = "gpt-a"\n')
    manifest, manifest_path = create_backup(source, backup_root=tmp_path / "history")
    manifest.backup_path.write_bytes(b"tampered\n")

    with pytest.raises(BackupIntegrityError):
        verify_backup_manifest(manifest_path)


def test_manifest_cannot_redirect_payload_outside_record_directory(tmp_path: Path) -> None:
    source = tmp_path / "config.toml"
    _write_config(source, 'model = "gpt-a"\n')
    _, manifest_path = create_backup(source, backup_root=tmp_path / "history")
    outside = tmp_path / "outside.toml"
    outside.write_text('model = "gpt-evil"\n', encoding="utf-8")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["backup_path"] = str(outside)
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BackupIntegrityError):
        verify_backup_manifest(manifest_path)


def test_backup_rejects_symbolic_link_source(tmp_path: Path) -> None:
    source = tmp_path / "real.toml"
    _write_config(source, 'model = "gpt-a"\n')
    link = tmp_path / "config.toml"
    link.symlink_to(source)

    with pytest.raises(UnsafePathError):
        create_backup(link, backup_root=tmp_path / "history")


def test_atomic_apply_preserves_mode_and_backs_up_old_bytes(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    before = _write_config(target, 'model = "gpt-a"\n', 0o640)
    candidate = b'model = "gpt-b"\n'
    backup_root = tmp_path / "history"

    result = apply_candidate(
        target,
        candidate,
        expected_source_sha256=sha256_bytes(before),
        backup_root=backup_root,
    )

    assert target.read_bytes() == candidate
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert result.before_sha256 == sha256_bytes(before)
    assert result.candidate_sha256 == sha256_bytes(candidate)
    assert result.final_sha256 == result.candidate_sha256
    manifest, backup_bytes = read_verified_backup(result.backup_manifest_path)
    assert manifest.operation is BackupOperation.PRE_WRITE
    assert backup_bytes == before
    assert list(target.parent.glob(f".{target.name}.codex-tui-*")) == []


def test_apply_rejects_stale_source_before_backup(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    original = _write_config(target, 'model = "gpt-a"\n')
    prepared_sha = sha256_bytes(original)
    _write_config(target, 'model = "changed-elsewhere"\n')
    backup_root = tmp_path / "history"

    with pytest.raises(StaleSourceError):
        apply_candidate(
            target,
            b'model = "gpt-b"\n',
            expected_source_sha256=prepared_sha,
            backup_root=backup_root,
        )

    assert target.read_text(encoding="utf-8") == 'model = "changed-elsewhere"\n'
    assert list_manifest_paths(backup_root=backup_root) == []


def test_invalid_candidate_never_creates_backup_or_changes_target(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    before = _write_config(target, 'model = "gpt-a"\n')
    backup_root = tmp_path / "history"

    with pytest.raises(CandidateValidationError):
        apply_candidate(
            target,
            b"approval_policy =\n",
            expected_source_sha256=sha256_bytes(before),
            backup_root=backup_root,
        )

    assert target.read_bytes() == before
    assert list_manifest_paths(backup_root=backup_root) == []


def test_apply_rejects_symbolic_link_target(tmp_path: Path) -> None:
    real = tmp_path / "real.toml"
    before = _write_config(real, 'model = "gpt-a"\n')
    target = tmp_path / "config.toml"
    target.symlink_to(real)

    with pytest.raises(UnsafePathError):
        apply_candidate(
            target,
            b'model = "gpt-b"\n',
            expected_source_sha256=sha256_bytes(before),
            backup_root=tmp_path / "history",
        )

    assert real.read_bytes() == before


def test_post_replace_failure_rolls_back_exact_bytes_and_mode(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    before = _write_config(target, '# old\nmodel = "gpt-a"\n', 0o600)
    backup_root = tmp_path / "history"

    def fail_after_replace(_: Path) -> None:
        raise RuntimeError("injected post-write verifier failure")

    with pytest.raises(WriteRolledBackError) as caught:
        apply_candidate(
            target,
            b'model = "gpt-b"\n',
            expected_source_sha256=sha256_bytes(before),
            backup_root=backup_root,
            post_replace_validator=fail_after_replace,
        )

    assert target.read_bytes() == before
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    manifest, backup_bytes = read_verified_backup(caught.value.backup_manifest_path)
    assert manifest.source_sha256 == sha256_bytes(before)
    assert backup_bytes == before
    assert list(target.parent.glob(f".{target.name}.codex-tui-*")) == []


def test_restore_first_backs_up_current_state_and_restores_historical_mode(tmp_path: Path) -> None:
    target = tmp_path / "config.toml"
    historical = _write_config(target, '# historical\nmodel = "gpt-a"\n', 0o600)
    backup_root = tmp_path / "history"
    historical_manifest, historical_manifest_path = create_backup(
        target,
        backup_root=backup_root,
        checkpoint_name="known-good",
    )

    current = _write_config(target, 'model = "gpt-new"\n', 0o640)
    result = restore_from_manifest(
        historical_manifest_path,
        target,
        expected_target_sha256=sha256_bytes(current),
        backup_root=backup_root,
    )

    assert target.read_bytes() == historical
    assert stat.S_IMODE(target.stat().st_mode) == historical_manifest.source_mode == 0o600

    pre_restore_manifest, pre_restore_bytes = read_verified_backup(result.backup_manifest_path)
    assert pre_restore_manifest.operation is BackupOperation.PRE_RESTORE
    assert pre_restore_manifest.rollback_of == historical_manifest.operation_id
    assert pre_restore_bytes == current

    # The historical recovery artifact remains intact after restoration.
    assert read_verified_backup(historical_manifest_path)[1] == historical
