from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from codex_tui.cli import app
from codex_tui.models import DiagnosticKind
from codex_tui.profiles.compare import compare_profile
from codex_tui.profiles.discover import discover_profiles
from codex_tui.profiles.launch import build_profile_argv, launch_profile
from codex_tui.profiles.migrate import plan_legacy_profile_migration
from codex_tui.profiles.names import InvalidProfileNameError, validate_profile_name

FIXTURES = Path(__file__).parents[1] / "fixtures"
RUNNER = CliRunner()


def test_profile_name_matches_codex_profile_v2_rules() -> None:
    for value in ("work", "work-2", "local_model", "A1"):
        assert validate_profile_name(value) == value

    for value in ("", "../work", "work.name", "work/name", "space name", "café"):
        with pytest.raises(InvalidProfileNameError):
            validate_profile_name(value)


def test_discovery_lists_valid_and_invalid_toml_profiles(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('model = "base"\n', encoding="utf-8")
    (tmp_path / "work.config.toml").write_text('model = "work"\n', encoding="utf-8")
    (tmp_path / "broken.config.toml").write_text("approval_policy =\n", encoding="utf-8")
    (tmp_path / "bad.name.config.toml").write_text('model = "ignored"\n', encoding="utf-8")
    (tmp_path / "other.toml").write_text('model = "ignored"\n', encoding="utf-8")

    profiles, diagnostics = discover_profiles(tmp_path)
    by_name = {profile.name: profile for profile in profiles}

    assert set(by_name) == {"broken", "work"}
    assert by_name["work"].valid_toml is True
    assert by_name["broken"].valid_toml is False
    assert any(item.kind is DiagnosticKind.PROFILE_INVALID_NAME for item in diagnostics)


def test_discovery_rejects_profile_symlink(tmp_path: Path) -> None:
    external = tmp_path / "external.toml"
    external.write_text('model = "outside"\n', encoding="utf-8")
    (tmp_path / "work.config.toml").symlink_to(external)

    profiles, diagnostics = discover_profiles(tmp_path)

    assert profiles == []
    assert any(
        item.kind is DiagnosticKind.UNREACHABLE_PATH and "symbolic link" in item.message
        for item in diagnostics
    )


def test_profile_diff_compares_base_to_effective_overlay(tmp_path: Path) -> None:
    base = tmp_path / "config.toml"
    base.write_text(
        'model = "base"\nmodel_verbosity = "high"\n[features]\nmulti_agent = false\n',
        encoding="utf-8",
    )
    profile = tmp_path / "work.config.toml"
    profile.write_text(
        'model = "work"\n[features]\nmulti_agent = true\n',
        encoding="utf-8",
    )

    comparison = compare_profile(base, profile, name="work")
    changes = {item.key_path: item for item in comparison.diff.changes}

    assert set(changes) == {"features.multi_agent", "model"}
    assert changes["model"].before == "base"
    assert changes["model"].after == "work"
    assert "model_verbosity" not in changes


def test_migration_plan_preserves_comments_and_reroots_nested_tables(tmp_path: Path) -> None:
    source = tmp_path / "config.toml"
    source.write_text(
        """model = "base"

[profiles.safe]
# preserve me
approval_policy = "on-request" # keep inline

[profiles.safe.features]
multi_agent = true # keep nested
""",
        encoding="utf-8",
    )

    plan = plan_legacy_profile_migration(source)

    assert plan.diagnostics == []
    assert len(plan.candidates) == 1
    candidate = plan.candidates[0]
    assert candidate.name == "safe"
    assert candidate.target_path == tmp_path / "safe.config.toml"
    assert "# preserve me" in candidate.content
    assert "# keep inline" in candidate.content
    assert "[features]" in candidate.content
    assert "[profiles.safe" not in candidate.content
    assert "# keep nested" in candidate.content


def test_migration_plan_rejects_invalid_name_and_flags_existing_target(tmp_path: Path) -> None:
    source = tmp_path / "config.toml"
    source.write_text(
        """[profiles.safe]
sandbox_mode = "read-only"

[profiles."bad.name"]
sandbox_mode = "read-only"
""",
        encoding="utf-8",
    )
    (tmp_path / "safe.config.toml").write_text('model = "existing"\n', encoding="utf-8")

    plan = plan_legacy_profile_migration(source)

    assert len(plan.candidates) == 1
    assert plan.candidates[0].name == "safe"
    assert any(
        item.kind is DiagnosticKind.PROFILE_COLLISION
        for item in plan.candidates[0].diagnostics
    )
    assert any(item.kind is DiagnosticKind.PROFILE_INVALID_NAME for item in plan.diagnostics)


def test_profile_launch_argv_is_plain_name_only(tmp_path: Path) -> None:
    binary = tmp_path / "codex"
    assert build_profile_argv(binary, "work-2") == [str(binary), "--profile", "work-2"]
    with pytest.raises(InvalidProfileNameError):
        build_profile_argv(binary, "../work")


def test_launch_profile_propagates_selected_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    binary = tmp_path / "codex"
    selected_home = tmp_path / "selected-home"

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["argv"] = argv
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr("codex_tui.profiles.launch.subprocess.run", fake_run)
    returncode = launch_profile(binary, "work", codex_home_path=selected_home)

    assert returncode == 0
    assert captured["argv"] == [str(binary), "--profile", "work"]
    assert captured["env"]["CODEX_HOME"] == str(selected_home.absolute())
    assert captured["shell"] is False


def test_profiles_cli_list_and_plan_are_read_only(tmp_path: Path) -> None:
    base = tmp_path / "config.toml"
    original = """model = "gpt-base"

[profiles.safe]
approval_policy = "on-request"
sandbox_mode = "read-only"
"""
    base.write_text(original, encoding="utf-8")
    (tmp_path / "work.config.toml").write_text('model = "gpt-work"\n', encoding="utf-8")

    listed = RUNNER.invoke(app, ["profiles", "list", "--codex-home", str(tmp_path)])
    assert listed.exit_code == 0
    assert "work: valid" in listed.output

    planned = RUNNER.invoke(
        app,
        [
            "profiles",
            "plan-migration",
            "--config",
            str(base),
            "--schema-file",
            str(FIXTURES / "schema.minimal.json"),
        ],
    )
    assert planned.exit_code == 0
    assert f"safe -> {tmp_path / 'safe.config.toml'}" in planned.output
    assert "writes performed: 0" in planned.output
    assert base.read_text(encoding="utf-8") == original
    assert not (tmp_path / "safe.config.toml").exists()


def test_profiles_cli_plan_fails_on_blocking_source_diagnostic(tmp_path: Path) -> None:
    missing = tmp_path / "missing.toml"

    result = RUNNER.invoke(
        app,
        [
            "profiles",
            "plan-migration",
            "--config",
            str(missing),
            "--no-validate-schema",
        ],
    )

    assert result.exit_code == 1
    assert "BLOCKING" in result.output
    assert "errors: 1" in result.output
    assert "writes performed: 0" in result.output


def test_profiles_cli_diff_redacts_sensitive_values(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('api_token = "one"\n', encoding="utf-8")
    (tmp_path / "work.config.toml").write_text('api_token = "two"\n', encoding="utf-8")

    result = RUNNER.invoke(
        app,
        ["profiles", "diff", "work", "--codex-home", str(tmp_path)],
    )

    assert result.exit_code == 0
    assert "<redacted>" in result.output
    assert "one" not in result.output
    assert "two" not in result.output


def test_profiles_cli_launch_dry_run_validates_discovered_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "config.toml").write_text('model = "base"\n', encoding="utf-8")
    (tmp_path / "work.config.toml").write_text('model = "work"\n', encoding="utf-8")
    fake_binary = tmp_path / "codex"

    monkeypatch.setattr("codex_tui.profile_cli.discover_codex_binary", lambda: fake_binary)
    result = RUNNER.invoke(
        app,
        [
            "profiles",
            "launch",
            "work",
            "--codex-home",
            str(tmp_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert f'CODEX_HOME="{tmp_path}"' in result.output
    assert str(fake_binary) in result.output
    assert '"--profile"' in result.output
    assert '"work"' in result.output
