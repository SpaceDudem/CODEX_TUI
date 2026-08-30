from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


class DiagnosticKind(StrEnum):
    PARSE_ERROR = "parse_error"
    DUPLICATE = "duplicate"
    UNKNOWN_KEY = "unknown_key"
    DEPRECATED_KEY = "deprecated_key"
    REMOVED_KEY = "removed_key"
    INVALID_TYPE = "invalid_type"
    INVALID_ENUM = "invalid_enum"
    IGNORED_SCOPE = "ignored_scope"
    CONFLICTING_ALIAS = "conflicting_alias"
    PROFILE_LEGACY = "profile_legacy"
    PROFILE_INVALID_NAME = "profile_invalid_name"
    PROFILE_COLLISION = "profile_collision"
    RUNTIME_MISMATCH = "runtime_mismatch"
    SCHEMA_MISMATCH = "schema_mismatch"
    MISSING_DEPENDENCY = "missing_dependency"
    UNREACHABLE_PATH = "unreachable_path"


class Diagnostic(BaseModel):
    model_config = ConfigDict(frozen=True)

    severity: Severity
    kind: DiagnosticKind
    message: str
    source_path: Path | None = None
    key_path: str | None = None
    line: int | None = None
    column: int | None = None


class LayerType(StrEnum):
    SYSTEM = "system"
    MANAGED = "managed"
    CLOUD_MANAGED = "cloud_managed"
    USER = "user"
    USER_PROFILE = "user_profile"
    PROJECT = "project"
    RUNTIME = "runtime"
    LEGACY_MANAGED = "legacy_managed"


class ConfigLayer(BaseModel):
    model_config = ConfigDict(frozen=True)

    layer_id: str
    layer_type: LayerType
    path: Path
    precedence: int
    enabled: bool = True
    trusted: bool | None = None
    writable: bool = False
    profile_name: str | None = None
    source_version: str | None = None


class OverriddenValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: Any
    layer_id: str
    source_path: Path


class EffectiveValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    key_path: str
    value: Any
    winning_layer: str
    winning_path: Path
    overridden_values: list[OverriddenValue] = Field(default_factory=list)
    validation_state: str = "unknown"
    catalog_state: str = "unknown"
    write_scope_state: str = "unknown"


class SettingDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    key_path: str
    section: str | None = None
    value_type: str | None = None
    allowed_values: list[Any] = Field(default_factory=list)
    default_value: Any = None
    description: str | None = None
    maturity: str = "stable"
    introduced_version: str | None = None
    deprecated_version: str | None = None
    removed_version: str | None = None
    aliases: list[str] = Field(default_factory=list)
    replacement_key: str | None = None
    source_kind: str = "schema"
    source_reference: str | None = None
    schema_version: str | None = None
    codex_version: str | None = None
    project_local_allowed: bool | None = None
    sensitive: bool = False
    runtime_observed: bool = False
    last_seen: str | None = None


class SemanticChangeKind(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    CHANGED = "changed"


class SemanticChange(BaseModel):
    model_config = ConfigDict(frozen=True)

    key_path: str
    kind: SemanticChangeKind
    before: Any = None
    after: Any = None


class SemanticDiff(BaseModel):
    model_config = ConfigDict(frozen=True)

    left_path: Path
    right_path: Path
    changes: list[SemanticChange] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.changes


class SchemaSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha256: str
    path: Path
    source_url: str
    acquired_at: str
    size_bytes: int


class BackupOperation(StrEnum):
    MANUAL = "manual-backup"
    PRE_WRITE = "pre-write"
    PRE_RESTORE = "pre-restore"


class BackupManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    manifest_version: int = 1
    operation_id: str
    operation: BackupOperation
    created_at: datetime
    source_path: Path
    backup_path: Path
    source_sha256: str
    backup_sha256: str
    source_size_bytes: int
    source_mode: int
    schema_sha256: str | None = None
    checkpoint_name: str | None = None
    rollback_of: str | None = None


class WriteResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_id: str
    target_path: Path
    backup_manifest_path: Path
    before_sha256: str
    candidate_sha256: str
    final_sha256: str
    rolled_back: bool = False
    rollback_verified: bool = False
