# ADR-003: Codex profile-v2 model

**Date:** 2026-08-30  
**Status:** Accepted for M3 implementation

## Current Codex behavior

M3 models current Codex profile-v2 behavior rather than the legacy `[profiles.*]` representation.

- The base user configuration is `$CODEX_HOME/config.toml`.
- Selecting `--profile work` layers `$CODEX_HOME/work.config.toml` on top of the base user configuration.
- A profile name is a non-empty plain ASCII name containing only letters, digits, `_`, or `-`.
- Profile-v2 files are user-level files under `CODEX_HOME`; current Codex does not discover project-local profile-v2 files.
- Legacy `[profiles.*]` tables remain migration input but are not the target storage representation.
- Supported CLI entry points accept `--profile`; CODEX_TUI does not assume equivalent profile selection exists for app-server or Desktop until Codex exposes it.

Upstream implementation references used for this decision:

- `openai/codex` `codex-rs/config/src/loader/mod.rs` for layer order.
- `openai/codex` `codex-rs/protocol/src/config_types.rs` for `ProfileV2Name` validation.
- `openai/codex` `codex-rs/utils/cli/src/shared_options.rs` for the CLI `--profile` option.

## M3 discovery contract

`codex-tui profiles list` scans only direct children of `CODEX_HOME` whose names end in `.config.toml`, excluding the base `config.toml`.

Invalid profile-like filenames are diagnostics rather than silently selectable profiles. Each discovered profile is parsed independently so one malformed file does not hide the rest of the profile inventory.

## Effective comparison

Profile comparison is not a raw file diff. CODEX_TUI recursively overlays the profile mapping over base configuration and then compares base configuration with that effective base-plus-profile result. Base-only settings therefore remain inherited rather than appearing as removals.

## Legacy migration contract

`codex-tui profiles plan-migration` is read-only.

For each valid legacy `[profiles.<name>]` table it:

1. validates the name against the current profile-v2 rule;
2. re-roots the table as `<name>.config.toml`;
3. preserves comments, inline comments, whitespace, and nested table structure through `tomlkit` item copying;
4. validates the generated TOML;
5. optionally validates it against the selected Codex JSON schema;
6. reports a collision if the target profile file already exists;
7. performs zero writes.

No migration command may silently overwrite an existing profile file.

## Migration apply boundary

M3 planning does not yet create profile files in `CODEX_HOME`. Creating a new target requires a safe create-new-file extension to the M2 write layer: exclusive creation, parent-directory durability, candidate/schema validation, private/default permission policy, and collision rejection. M3 must use that shared safety layer rather than writing files directly.

Removing legacy `[profiles.*]` from the base config is a separate later step. It must occur only after candidate profile files have been created and validated, and it must use M2 backup/atomic-write/rollback semantics.

## Launch contract

The supported launcher constructs an argument vector equivalent to:

```text
codex --profile <validated-name>
```

It uses subprocess argument arrays with `shell=False` and inherited terminal I/O. Launch refuses an invalid name, missing profile, or malformed profile before invoking Codex.

## Non-goals for this milestone

M3 does not claim:

- project-local profile-v2 support that Codex itself does not currently provide;
- in-session profile hot switching;
- app-server/Desktop profile selection without an upstream supported selector;
- migration writes before the create-new-file safety primitive is complete.
