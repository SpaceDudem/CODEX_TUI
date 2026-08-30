from __future__ import annotations

from pathlib import Path


class CodexTuiError(RuntimeError):
    """Base error for recoverable CODEX_TUI operations."""


class WriteSafetyError(CodexTuiError):
    """A managed filesystem mutation could not be completed safely."""


class UnsafePathError(WriteSafetyError):
    """A target violates the managed-write path policy."""


class StaleSourceError(WriteSafetyError):
    """The target changed after the caller prepared its expected hash."""


class BackupIntegrityError(WriteSafetyError):
    """A backup or manifest failed integrity verification."""


class CandidateValidationError(WriteSafetyError):
    """Candidate configuration bytes failed pre-write validation."""


class PostWriteVerificationError(WriteSafetyError):
    """The replaced target did not verify as the intended candidate."""


class RollbackError(WriteSafetyError):
    """Automatic rollback itself failed or could not be verified."""


class WriteRolledBackError(WriteSafetyError):
    """A post-replace failure occurred and the exact prior bytes were restored."""

    def __init__(self, message: str, *, backup_manifest_path: Path) -> None:
        super().__init__(message)
        self.backup_manifest_path = backup_manifest_path
