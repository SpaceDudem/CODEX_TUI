# ADR-001: Codex compatibility boundaries are version/runtime aware

**Date:** 2026-08-30  
**Status:** Accepted

## Context

M1 validation against the current official Codex sources exposed behavior that cannot be represented by JSON Schema alone.

Primary references:

- https://developers.openai.com/codex/config-schema.json
- https://developers.openai.com/codex/config-reference/
- https://learn.chatgpt.com/codex/config-file/config-advanced

## Decisions

### Config profiles

Codex 0.134.0 and later loads `~/.codex/config.toml` and then overlays `$CODEX_HOME/<profile-name>.config.toml` when `--profile <profile-name>` is selected. It no longer reads `[profiles.<name>]` for `--profile`, and the top-level `profile = "name"` selector is no longer supported.

The generated JSON schema can still contain `profile` and `profiles` compatibility fields. CODEX_TUI therefore treats embedded profile diagnostics as **version/runtime behavior**, not merely schema validity. Historical Codex versions remain representable.

### Reasoning effort

The current schema defines `ReasoningEffort` as a non-empty string. Schema validation can establish shape validity, while the selected model/runtime determines which effort strings are actually advertised and usable.

CODEX_TUI keeps these states separate:

- `schema-valid`
- `runtime/model-supported`

Values such as `max` and `ultra` are runtime capability probes rather than automatic schema errors when the active schema permits them.

### Project-local scope

Current Codex documentation states that project-local `.codex/config.toml` ignores these root keys:

- `openai_base_url`
- `chatgpt_base_url`
- `apps_mcp_product_sku`
- `model_provider`
- `model_providers`
- `notify`
- `profile`
- `profiles`
- `experimental_realtime_ws_base_url`
- `otel`

CODEX_TUI surfaces these as `ignored_scope` warnings when evaluating a project layer.

### Schema composition

The current schema uses local `$ref`, `allOf`, `oneOf`, `anyOf`, and dynamic `additionalProperties` tables extensively. The setting catalog must resolve these constructs for inspection while JSON Schema itself remains the authority for validation.

## Consequences

- Schema snapshots and Codex-version observations must remain separate records.
- Runtime capability checks may be stricter than schema validation.
- The catalog can show union types and dynamic paths such as `plugins.<name>.enabled`.
- Migration logic must be gated by the installed/target Codex version.
- M1 remains read-only; profile migration writes belong to M3.
