# CODEX_TUI

Schema-driven CLI and future Textual TUI for inspecting, validating, profiling, diffing, backing up, and managing Codex configuration across versions.

M1 is deliberately read-only. It discovers Codex, loads TOML without rewriting it, caches immutable schema snapshots, validates configuration, builds a searchable setting catalog, detects legacy profile tables, and produces semantic diffs.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
pytest

codex-tui inspect --config tests/fixtures/config.machine.tui-template.toml
codex-tui validate --config tests/fixtures/config.machine.tui-template.toml
codex-tui catalog
codex-tui diff tests/fixtures/config.machine.tui-template.toml tests/fixtures/config.machine.tui-template.toml
```

The committed machine fixture is sanitized for the public repository. Real Codex machine configuration remains local-only.

See [`docs/PDR.md`](docs/PDR.md) for the implementation contract.
