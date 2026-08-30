import json
from pathlib import Path

import httpx

from codex_tui.config.diagnostics import detect_legacy_profiles
from codex_tui.config.diff import semantic_diff
from codex_tui.config.parser import load_config
from codex_tui.config.validator import validate_config
from codex_tui.models import DiagnosticKind, Severity
from codex_tui.paths import codex_home, xdg_cache_home, xdg_data_home
from codex_tui.schema.catalog import build_catalog
from codex_tui.schema.fetch import acquire_schema
from codex_tui.schema.snapshot import newest_snapshot, write_immutable_snapshot

FIXTURES = Path(__file__).parents[1] / "fixtures"


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


def test_detect_legacy_profiles() -> None:
    diagnostics = detect_legacy_profiles(
        {"profiles": {"safe": {"sandbox_mode": "read-only"}, "work": {}}},
        Path("config.toml"),
    )
    assert len(diagnostics) == 2
    assert all(item.kind is DiagnosticKind.PROFILE_LEGACY for item in diagnostics)
    assert diagnostics[0].key_path == "profiles.safe"


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


def test_catalog_extracts_types_enums_defaults() -> None:
    schema = json.loads((FIXTURES / "schema.minimal.json").read_text(encoding="utf-8"))
    catalog = {item.key_path: item for item in build_catalog(schema)}
    assert catalog["model"].value_type == "string"
    assert "xhigh" in catalog["model_reasoning_effort"].allowed_values
    assert catalog["features.multi_agent"].default_value is False


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


def test_validator_reports_schema_error_and_legacy_profile() -> None:
    schema = json.loads((FIXTURES / "schema.minimal.json").read_text(encoding="utf-8"))
    diagnostics = validate_config(
        {
            "model_reasoning_effort": "ultra",
            "profiles": {"safe": {"sandbox_mode": "read-only"}},
        },
        schema,
        Path("config.toml"),
    )
    assert any(item.kind is DiagnosticKind.PROFILE_LEGACY for item in diagnostics)
    assert any(item.severity is Severity.ERROR for item in diagnostics)
