from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from codex_tui.cli import app
from codex_tui.history.backup import create_backup, list_manifest_paths, sha256_bytes

FIXTURES = Path(__file__).parents[1] / "fixtures"
RUNNER = CliRunner()


def _write(path: Path, text: str) -> bytes:
    content = text.encode("utf-8")
    path.write_bytes(content)
    return content


def test_cli_backup_and_history_round_trip(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    original = _write(config, 'model = "gpt-a"\n')
    backup_root = tmp_path / "history"

    backup = RUNNER.invoke(
        app,
        [
            "backup",
            "--config",
            str(config),
            "--backup-root",
            str(backup_root),
            "--checkpoint",
            "baseline",
        ],
    )
    assert backup.exit_code == 0
    assert sha256_bytes(original) in backup.output
    assert "Checkpoint: baseline" in backup.output

    history = RUNNER.invoke(
        app,
        [
            "history",
            "--backup-root",
            str(backup_root),
            "--config",
            str(config),
        ],
    )
    assert history.exit_code == 0
    assert "manual-backup" in history.output
    assert "checkpoint='baseline'" in history.output
    assert "History entries: 1; invalid: 0" in history.output


def test_cli_apply_valid_candidate_creates_recovery_manifest(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    before = _write(config, 'model = "gpt-a"\n')
    candidate = tmp_path / "candidate.toml"
    _write(candidate, 'model = "gpt-b"\n')
    backup_root = tmp_path / "history"

    result = RUNNER.invoke(
        app,
        [
            "apply",
            "--config",
            str(config),
            "--candidate",
            str(candidate),
            "--expected-sha",
            sha256_bytes(before),
            "--schema-file",
            str(FIXTURES / "schema.minimal.json"),
            "--backup-root",
            str(backup_root),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert "Proposed semantic changes:" in result.output
    assert "Applied:" in result.output
    assert config.read_text(encoding="utf-8") == 'model = "gpt-b"\n'
    assert len(list_manifest_paths(backup_root=backup_root)) == 1


def test_cli_apply_rejects_schema_invalid_candidate_before_backup(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    before = _write(config, 'model = "gpt-a"\n')
    candidate = tmp_path / "candidate.toml"
    _write(candidate, 'model_reasoning_effort = "ultra"\n')
    backup_root = tmp_path / "history"

    result = RUNNER.invoke(
        app,
        [
            "apply",
            "--config",
            str(config),
            "--candidate",
            str(candidate),
            "--expected-sha",
            sha256_bytes(before),
            "--schema-file",
            str(FIXTURES / "schema.minimal.json"),
            "--backup-root",
            str(backup_root),
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert "Candidate failed pinned Codex schema validation" in result.output
    assert config.read_bytes() == before
    assert list_manifest_paths(backup_root=backup_root) == []


def test_cli_apply_rejects_stale_expected_sha(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    original = _write(config, 'model = "gpt-a"\n')
    expected = sha256_bytes(original)
    _write(config, 'model = "changed-elsewhere"\n')
    candidate = tmp_path / "candidate.toml"
    _write(candidate, 'model = "gpt-b"\n')
    backup_root = tmp_path / "history"

    result = RUNNER.invoke(
        app,
        [
            "apply",
            "--config",
            str(config),
            "--candidate",
            str(candidate),
            "--expected-sha",
            expected,
            "--schema-file",
            str(FIXTURES / "schema.minimal.json"),
            "--backup-root",
            str(backup_root),
            "--yes",
        ],
    )

    assert result.exit_code == 1
    assert "Target changed before write" in result.output
    assert config.read_text(encoding="utf-8") == 'model = "changed-elsewhere"\n'
    assert list_manifest_paths(backup_root=backup_root) == []


def test_cli_apply_requires_confirmation_and_redacts_preview(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    before = _write(config, 'api_token = "secret-a"\n')
    candidate = tmp_path / "candidate.toml"
    _write(candidate, 'api_token = "secret-b"\n')

    result = RUNNER.invoke(
        app,
        [
            "apply",
            "--config",
            str(config),
            "--candidate",
            str(candidate),
            "--expected-sha",
            sha256_bytes(before),
            "--schema-file",
            str(FIXTURES / "schema.minimal.json"),
            "--backup-root",
            str(tmp_path / "history"),
        ],
        input="n\n",
    )

    assert result.exit_code == 1
    assert "<redacted>" in result.output
    assert "secret-a" not in result.output
    assert "secret-b" not in result.output
    assert config.read_bytes() == before


def test_cli_restore_requires_hash_and_preserves_pre_restore_snapshot(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    historical = _write(config, 'model = "gpt-a"\n')
    backup_root = tmp_path / "history"
    historical_manifest, historical_manifest_path = create_backup(
        config,
        backup_root=backup_root,
        checkpoint_name="known-good",
    )
    current = _write(config, 'model = "gpt-new"\n')

    result = RUNNER.invoke(
        app,
        [
            "restore",
            "--manifest",
            str(historical_manifest_path),
            "--config",
            str(config),
            "--expected-sha",
            sha256_bytes(current),
            "--backup-root",
            str(backup_root),
            "--yes",
        ],
    )

    assert result.exit_code == 0
    assert config.read_bytes() == historical
    assert historical_manifest.source_sha256 in result.output
    assert "Pre-restore backup:" in result.output
    assert len(list_manifest_paths(backup_root=backup_root)) == 2
