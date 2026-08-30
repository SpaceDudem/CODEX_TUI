# CODEX_TUI

Schema-driven CLI and future Textual TUI for inspecting, validating, profiling, diffing, backing up, restoring, and safely managing Codex configuration across versions.

## Status

- **M1:** read-only configuration/schema engine complete.
- **M2:** backup, atomic-write, verification, restore, and rollback engine implemented and under final CI/review before merge.
- **M3 next:** profile-v2 discovery, migration planning, comparison, and launch workflows.

The user's real machine configuration is never committed to this public repository. Public tests use sanitized fixtures.

## Install for development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Inspect and validate

```bash
codex-tui inspect
codex-tui inspect --profile work
codex-tui inspect --config tests/fixtures/config.current-smoke.toml --effective model
codex-tui validate --config tests/fixtures/config.current-smoke.toml
codex-tui catalog --search reasoning
codex-tui diff config-a.toml config-b.toml
```

`inspect` reports discovered layers and effective-value provenance. `validate` uses an immutable cached snapshot of the official Codex JSON schema, with offline fallback. `catalog` resolves local schema references and composition constructs for browsing. `diff` compares TOML semantically and redacts potentially sensitive values.

## Recovery and managed writes

Create a byte-exact checkpoint and capture the SHA-256 concurrency token:

```bash
codex-tui backup \
  --config ~/.codex/config.toml \
  --checkpoint before-change
```

Inspect verified recovery history:

```bash
codex-tui history --config ~/.codex/config.toml
```

Apply a candidate only after schema validation and semantic preview:

```bash
codex-tui apply \
  --config ~/.codex/config.toml \
  --candidate ./candidate.toml \
  --expected-sha <sha256-from-reviewed-target-state>
```

Restore a verified historical manifest while first protecting the current state:

```bash
codex-tui restore \
  --manifest ~/.local/share/codex-tui/backups/.../manifest.json \
  --config ~/.codex/config.toml \
  --expected-sha <sha256-of-current-reviewed-target>
```

`apply` and `restore` prompt before replacement. `--yes` is available for deliberate non-interactive use. Both commands reject stale expected hashes. `apply` validates the candidate against the selected Codex schema before creating the pre-write recovery snapshot.

The M2 writer is intentionally POSIX-only while it uses a per-target advisory `flock`. The lock serializes CODEX_TUI writers. Unrelated external editors do not participate in advisory locks, so external concurrency is protected optimistically with the required SHA token and repeated target checks; CODEX_TUI does not claim a filesystem-level compare-and-swap guarantee against arbitrary processes.

See `docs/decisions/ADR-002-m2-write-safety.md` for the complete safety contract.

## Compatibility model

CODEX_TUI treats three compatibility questions separately:

1. **Schema validity** — whether the setting/value satisfies the pinned Codex JSON schema.
2. **Layer effectiveness** — whether Codex honors the setting from the selected config layer.
3. **Runtime/model support** — whether the installed Codex/model actually advertises a schema-valid capability.

See `docs/decisions/ADR-001-codex-compatibility-boundaries.md` for current profile, reasoning-effort, and project-layer decisions.

## Development checks

```bash
pytest
python -m compileall -q codex_tui
ruff check codex_tui tests
mypy codex_tui
```

GitHub Actions runs these checks on Python 3.11 and 3.12 and performs a current official Codex schema smoke test.

## Milestones

- **M1 — Read-only engine:** complete; see `docs/M1-CHECKPOINT.md`.
- **M2 — Backup/write/rollback:** implementation complete; see `docs/M2-CHECKPOINT.md` after final acceptance.
- **M3 — Profiles:** profile-v2 migration and launch workflows.
- **M4 — Introspection/history:** capability probes and versioned catalog history.
- **M5 — Textual TUI:** presentation layer over the same backend.

## License

Apache-2.0
