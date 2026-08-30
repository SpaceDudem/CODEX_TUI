# M1 checkpoint — read-only engine

M1 is complete when this document is on `main`.

## Delivered

- Codex binary and version discovery with bounded subprocess execution.
- `CODEX_HOME` and XDG path discovery.
- Comment/order-preserving TOML parsing with structured diagnostics.
- User, named-profile, and project layer discovery.
- Effective-value provenance and override-chain calculation.
- Immutable SHA-256 schema snapshots with cache/offline fallback.
- JSON Schema draft selection from each snapshot.
- Schema-derived catalog with local `$ref`, `allOf`, `oneOf`, `anyOf`, and dynamic `additionalProperties` handling.
- Version-aware profile compatibility diagnostics for Codex 0.134.0+.
- Project-layer ignored-setting diagnostics.
- Semantic config diff.
- Sensitive-value redaction for CLI diagnostics/diffs/provenance.
- CLI: `inspect`, `validate`, `catalog`, `diff`.
- Public-safe fixtures; real machine config stays outside the repository.

## Automated acceptance

GitHub Actions validates:

- Python 3.11
- Python 3.12
- 21 unit/CLI tests
- bytecode compilation
- Ruff
- strict mypy
- live official Codex schema download
- composed-schema catalog extraction
- current-schema smoke-config validation using the downloaded cache

## Safety boundary

M1 has no live configuration writer. M2 introduces backup manifests, atomic writes, post-write verification, and byte-exact rollback before any live apply workflow is exposed.
