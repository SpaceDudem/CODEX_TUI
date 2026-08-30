import json
from pathlib import Path

import httpx
from typer.testing import CliRunner

from codex_tui.cli import app
from codex_tui.codex.version import codex_version_at_least, parse_codex_version
from codex_tui.config.diagnostics import (
    detect_ignored_project_scope,
    detect_legacy_profiles,
)
from codex_tui.config.diff import semantic_diff
from codex_tui.config.effective import compute_effective_values
from codex_tui.config.parser import load_config
from codex_tui.config.validator import validate_config
from codex_tui.models import ConfigLayer, DiagnosticKind, LayerType, Severity
from codex_tui.paths import codex_home, xdg_cache_home, xdg_data_home
from codex_tui.schema.catalog import build_catalog
from codex_tui.schema.fetch import acquire_schema
from codex_tui.schema.snapshot import newest_snapshot, write_immutable_snapshot
from codex_tui.security import display_value, is_sensitive_key_path

FIXTURES = Path(__file__).parents[1] / "fixtures"
RUNNER = CliRunner()


def test_parser_preserves_raw_text_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    text = '# keep me\nmodel = "gpt-test"\n'
    path.write_text(text, encoding="utf-8")
    parsed = load_config(path)
    assert parsed.valid_toml
    assert parsed.raw_text == text
    assert parsed.document is not None
    assert parsed.document.as_string() == text


def test_malformed_toml_returns_structured_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text('approval_policy =\n', encoding="utf-8")
    parsed = load_config(path)
    assert not parsed.valid_toml
    assert parsed.diagnostics
    assert parsed.diagnostics[0].kind is DiagnosticKind.PARSE_ERROR
    assert parsed.diagnostics[0].source_path == path


def test_detect_legacy_profiles_is_version_gated() -> None:
    config = {"profiles": {"safe": {"sandbox_mode": "read-only"}, "work": {}}}
    assert detect_legacy_profiles(
        config, Path("config.toml"), codex_version="codex-cli 0.133.9"
    ) == []

    diagnostics = detect_legacy_profiles(
        config, Path("config.toml"), codex_version="codex-cli 0.134.0"
    )
    assert len(diagnostics) == 2
    assert all(item.kind is DiagnosticKind.PROFILE_LEGACY for item in diagnostics)
    assert diagnostics[0].key_path == "profiles.safe"


def test_project_scope_diagnostics() -> None:
    diagnostics = detect_ignored_project_scope(
        {"model": "gpt-test", "model_provider": "custom", "otel": {"environment": "dev"}},
        Path(".codex/config.toml"),
    )
    assert {item.key_path for item in diagnostics} == {"model_provider", "otel"}
    assert all(item.kind is DiagnosticKind.IGNORED_SCOPE for item in diagnostics)


def test_codex_version_parsing_and_comparison() -> None:
    assert parse_codex_version("codex-cli 0.134.2") == (0, 134, 2)
    assert parse_codex_version("codex 1.2.3-beta.1") == (1, 2, 3)
    assert parse_codex_version("unknown") is None
    assert codex_version_at_least("codex-cli 0.134.0", (0, 134, 0))
    assert not codex_version_at_least("codex-cli 0.133.9", (0, 134, 0))


def test_identical_diff_is_empty() -> None:
    data = {"model": "gpt-x", "features": {"multi_agent": True}}
    result = semantic_diff(Path("a"), data, Path("b"), data)
    assert result.is_empty


def test_semantic_diff_detects_nested_change() -> None:
    result = semantic_diff(
        Path("a"),
        {"features": {"multi_agent": False}},
        Path("b"),
        {"features": {"multi_agent": True}},
    )
    assert len(result.changes) == 1
    assert result.changes[0].key_path == "features.multi_agent"


def test_effective_value_tracks_provenance_and_override_chain() -> None:
    base = ConfigLayer(
        layer_id="user",
        layer_type=LayerType.USER,
        path=Path("user.toml"),
        precedence=100,
    )
    profile = ConfigLayer(
        layer_id="profile:work",
        layer_type=LayerType.USER_PROFILE,
        path=Path("work.config.toml"),
        precedence=200,
    )
    result = compute_effective_values(
        [
            (base, {"model": "gpt-a", "features": {"multi_agent": False}}),
            (profile, {"model": "gpt-b"}),
        ]
    )
    model = result["model"]
    assert model.value == "gpt-b"
    assert model.winning_layer == "profile:work"
    assert model.winning_path == Path("work.config.toml")
    assert len(model.overridden_values) == 1
    assert model.overridden_values[0].value == "gpt-a"
    assert result["features.multi_agent"].value is False


def test_catalog_extracts_types_enums_defaults() -> None:
    schema = json.loads((FIXTURES / "schema.minimal.json").read_text(encoding="utf-8"))
    catalog = {item.key_path: item for item in build_catalog(schema)}
    assert catalog["model"].value_type == "string"
    assert "xhigh" in catalog["model_reasoning_effort"].allowed_values
    assert catalog["features.multi_agent"].default_value is False


def test_catalog_resolves_refs_compositions_and_dynamic_tables() -> None:
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "definitions": {
            "Summary": {
                "oneOf": [
                    {"type": "string", "enum": ["auto", "detailed"]},
                    {"type": "string", "enum": ["none"]},
                ]
            },
            "HybridConfig": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                    "path": {"type": "string"},
                },
            },
            "Plugin": {
                "type": "object",
                "properties": {"enabled": {"type": "boolean", "default": True}},
            },
        },
        "type": "object",
        "properties": {
            "model_reasoning_summary": {
                "allOf": [{"$ref": "#/definitions/Summary"}],
                "description": "Summary mode.",
            },
            "features": {
                "type": "object",
                "properties": {
                    "hybrid": {
                        "anyOf": [
                            {"type": "boolean"},
                            {"$ref": "#/definitions/HybridConfig"},
                        ]
                    }
                },
            },
            "plugins": {
                "type": "object",
                "additionalProperties": {"$ref": "#/definitions/Plugin"},
            },
        },
        "additionalProperties": False,
    }
    catalog = {item.key_path: item for item in build_catalog(schema)}
    assert catalog["model_reasoning_summary"].allowed_values == ["auto", "detailed", "none"]
    assert catalog["model_reasoning_summary"].value_type == "string"
    assert catalog["features.hybrid"].value_type == "boolean | object"
    assert "features.hybrid.enabled" in catalog
    assert "features.hybrid.path" in catalog
    assert "plugins.<name>.enabled" in catalog
    assert catalog["plugins.<name>.enabled"].default_value is True


def test_snapshot_is_content_addressed_and_idempotent(tmp_path: Path) -> None:
    content = b'{"type":"object"}'
    first = write_immutable_snapshot(content, snapshot_dir=tmp_path, source_url="https://example.test")
    second = write_immutable_snapshot(content, snapshot_dir=tmp_path, source_url="https://example.test")
    assert first.sha256 == second.sha256
    assert first.path == second.path
    assert newest_snapshot(tmp_path) == first.path
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_schema_acquisition_uses_cache_when_present(tmp_path: Path) -> None:
    content = b'{"type":"object","properties":{"model":{"type":"string"}}}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        schema, snapshot, from_cache = acquire_schema(
            snapshot_dir=tmp_path, source_url="https://example.test/schema", client=client
        )
        assert schema["type"] == "object"
        assert from_cache is False
        assert snapshot.path.exists()

    def exploding_handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network should not be touched when cache exists")

    with httpx.Client(transport=httpx.MockTransport(exploding_handler)) as client:
        schema, _, from_cache = acquire_schema(
            snapshot_dir=tmp_path, source_url="https://example.test/schema", client=client
        )
        assert schema["type"] == "object"
        assert from_cache is True


def test_codex_home_env_override() -> None:
    assert codex_home({"CODEX_HOME": "/tmp/codex-home"}) == Path("/tmp/codex-home")


def test_xdg_env_overrides() -> None:
    env = {"XDG_CACHE_HOME": "/tmp/cache", "XDG_DATA_HOME": "/tmp/data"}
    assert xdg_cache_home(env) == Path("/tmp/cache")
    assert xdg_data_home(env) == Path("/tmp/data")


def test_validator_reports_schema_error_and_versioned_legacy_profile() -> None:
    schema = json.loads((FIXTURES / "schema.minimal.json").read_text(encoding="utf-8"))
    diagnostics = validate_config(
        {
            "model_reasoning_effort": "ultra",
            "profiles": {"safe": {"sandbox_mode": "read-only"}},
        },
        schema,
        Path("config.toml"),
        codex_version="codex-cli 0.134.0",
    )
    assert any(item.kind is DiagnosticKind.PROFILE_LEGACY for item in diagnostics)
    assert any(item.severity is Severity.ERROR for item in diagnostics)
    assert any(item.kind is DiagnosticKind.INVALID_ENUM for item in diagnostics)


def test_validator_adds_project_scope_warning_without_failing_schema() -> None:
    schema = {"type": "object", "additionalProperties": True}
    diagnostics = validate_config(
        {"model_provider": "custom"},
        schema,
        Path(".codex/config.toml"),
        layer_type=LayerType.PROJECT,
    )
    assert len(diagnostics) == 1
    assert diagnostics[0].kind is DiagnosticKind.IGNORED_SCOPE
    assert diagnostics[0].severity is Severity.WARNING


def test_sensitive_key_redaction() -> None:
    assert is_sensitive_key_path("model_providers.custom.api_key")
    assert is_sensitive_key_path("shell_environment_policy.set.MY_SECRET")
    assert display_value("api_token", "do-not-print") == "<redacted>"
    assert display_value("model", "gpt-test") == "'gpt-test'"


def test_cli_diff_identical_exit_zero() -> None:
    fixture = FIXTURES / "config.machine.tui-template.toml"
    result = RUNNER.invoke(app, ["diff", str(fixture), str(fixture)])
    assert result.exit_code == 0
    assert "No semantic changes." in result.output


def test_cli_diff_redacts_sensitive_values(tmp_path: Path) -> None:
    left = tmp_path / "left.toml"
    right = tmp_path / "right.toml"
    left.write_text('api_token = "secret-a"\n', encoding="utf-8")
    right.write_text('api_token = "secret-b"\n', encoding="utf-8")
    result = RUNNER.invoke(app, ["diff", str(left), str(right)])
    assert result.exit_code == 0
    assert "<redacted>" in result.output
    assert "secret-a" not in result.output
    assert "secret-b" not in result.output


def test_cli_validate_exit_codes(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text('model_reasoning_effort = "ultra"\n', encoding="utf-8")
    schema = FIXTURES / "schema.minimal.json"

    invalid = RUNNER.invoke(
        app,
        ["validate", "--config", str(config), "--schema-file", str(schema)],
    )
    assert invalid.exit_code == 1
    assert "invalid_enum" in invalid.output

    missing_schema = RUNNER.invoke(
        app,
        ["validate", "--config", str(config), "--schema-file", str(tmp_path / "missing.json")],
    )
    assert missing_schema.exit_code == 2
    assert "ERROR runtime" in missing_schema.output


def test_cli_inspect_explicit_config_shows_effective_provenance() -> None:
    fixture = FIXTURES / "config.current-smoke.toml"
    result = RUNNER.invoke(app, ["inspect", "--config", str(fixture), "--effective", "model"])
    assert result.exit_code == 0
    assert "Effective values:" in result.output
    assert "model = 'gpt-5.6-sol'" in result.output
    assert "<- explicit" in result.output
