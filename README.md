# CODEX_TUI

Schema-driven CLI and future Textual TUI for inspecting, validating, profiling, diffing, backing up, and managing Codex configuration across versions.

## Status

M1 provides the read-only configuration and schema engine. Live Codex configuration writes remain disabled until M2's backup, atomic-write, verification, and rollback layer is complete.

## Install for development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

## M1 commands

```bash
codex-tui inspect
codex-tui inspect --profile work
codex-tui inspect --config tests/fixtures/config.current-smoke.toml --effective model
codex-tui validate --config tests/fixtures/config.current-smoke.toml
codex-tui catalog --search reasoning
codex-tui diff config-a.toml config-b.toml
```

`inspect` reports discovered layers and effective-value provenance. `validate` uses an immutable cached snapshot of the official Codex JSON schema, with offline fallback. `catalog` resolves local schema references and composition constructs for browsing. `diff` compares TOML semantically and redacts potentially sensitive values.

## Compatibility model

CODEX_TUI treats three compatibility questions separately:

1. **Schema validity** — whether the setting/value satisfies the pinned Codex JSON schema.
2. **Layer effectiveness** — whether Codex honors the setting from the selected config layer.
3. **Runtime/model support** — whether the installed Codex/model actually advertises a schema-valid capability.

See `docs/decisions/ADR-001-codex-compatibility-boundaries.md` for current profile, reasoning-effort, and project-layer decisions.

## Safety boundary

M1 is read-only. It never rewrites `~/.codex/config.toml`, profile files, project config, or the user's real machine configuration. Public tests use sanitized fixtures.

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
- **M2 — Backup/write/rollback:** next; no live apply command ships until byte-exact recovery tests pass.
- **M3 — Profiles:** profile-v2 migration and launch workflows.
- **M4 — Introspection/history:** capability probes and versioned catalog history.
- **M5 — Textual TUI:** presentation layer over the same backend.

## License

Apache-2.0
