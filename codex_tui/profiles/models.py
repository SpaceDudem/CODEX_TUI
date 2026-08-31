from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from codex_tui.models import Diagnostic, SemanticDiff


class ProfileInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    path: Path
    valid_toml: bool
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class LegacyProfileCandidate(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    source_key: str
    target_path: Path
    content: str
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ProfileMigrationPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_path: Path
    candidates: list[LegacyProfileCandidate] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ProfileComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    base_path: Path
    profile_path: Path
    diff: SemanticDiff
