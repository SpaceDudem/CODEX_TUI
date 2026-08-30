# CODEX_TUI — Product Design Requirements (PDR)

**Version:** 0.1.0  
**Date:** 2026-08-30  
**Status:** Baseline for implementation  
**Primary artifact:** schema-driven Codex configuration manager with a Textual TUI  
**Initial platform:** local Codex CLI installations  
**Canonical input:** `config.machine.tui-template.toml`

---

## 1. Purpose

CODEX_TUI is a local configuration-management and introspection tool for Codex CLI. It provides a safe, version-aware interface for discovering, inspecting, validating, editing, profiling, comparing, backing up, restoring, and launching Codex configurations.

The product must treat Codex configuration as a changing external schema rather than a fixed set of hard-coded menu entries. The TUI is a presentation layer over a reusable configuration engine. The engine must remain usable without the TUI through a first-class CLI.

The main operational goals are:

1. Show the effective Codex configuration and where every value came from.
2. Prevent invalid TOML, accidental scope changes, duplicate settings, stale aliases, and unsupported values.
3. Discover configuration changes across Codex versions.
4. Preserve comments and human-edited formatting.
5. Back up every configuration before a write and provide reliable rollback.
6. Manage reusable profile files and launch Codex with an explicitly selected profile.
7. Surface stable, experimental, deprecated, removed, undocumented, and runtime-discovered settings distinctly.
8. Keep a local historical catalog of Codex configuration capabilities.

---

## 2. Problem Statement

Codex configuration evolves quickly and can be assembled from multiple files and scopes. A plain-text `config.toml` workflow creates several failure modes:

- duplicate or conflicting keys;
- keys placed under the wrong TOML table because of section scoping;
- stale aliases retained after a rename;
- values copied from older Codex releases;
- project-level settings that Codex ignores because they are machine-owned;
- profile behavior changing across Codex versions;
- experimental flags becoming stable, renamed, or removed;
- separate user, project, profile, system, and runtime layers producing an effective value that is difficult to trace;
- comments and hand-maintained structure being destroyed by generic serializers;
- config edits being applied without a restorable pre-change state.

CODEX_TUI must make these conditions visible before changes are applied.

---

## 3. Current Codex Facts That Drive the Design

The implementation must model current Codex behavior while keeping that behavior versioned.

### 3.1 Configuration layers

Codex currently builds effective configuration from multiple layers. The observed loader order includes system/managed sources, base user config, an optional named user profile, project-local `.codex/config.toml` layers, and runtime overrides.

CODEX_TUI must represent each layer independently and calculate a merged effective view without losing provenance.

### 3.2 Named profiles

Current Codex profile-v2 behavior uses separate files:

```text
$CODEX_HOME/config.toml
$CODEX_HOME/work.config.toml
$CODEX_HOME/autonomous.config.toml
$CODEX_HOME/full-access.config.toml
```

A profile is selected with a plain profile name such as:

```bash
codex --profile work
```

Legacy `[profiles.<name>]` tables are transitional input only. CODEX_TUI must detect them, explain the migration, and generate profile-v2 files without silently overwriting the source configuration.

### 3.3 Project-local restrictions

Some settings are machine-owned and are ignored from project-local `.codex/config.toml`. The catalog must therefore record where a setting is legal to write. A value can be syntactically valid TOML and still be ineffective at a particular layer.

### 3.4 Schema-driven validation

The official Codex JSON schema is the primary machine-readable specification. The implementation must snapshot the schema used for every validation run.

The catalog may enrich schema data with:

- official Codex configuration documentation;
- Codex open-source configuration types and loader behavior;
- supported CLI output;
- controlled runtime probes;
- user-observed fields from existing configurations.

No enrichment source may silently override a stricter official schema rule.

### 3.5 Reasoning effort

The currently documented reasoning-effort values are:

```text
minimal
low
medium
high
xhigh
```

Other values discovered in historical files or model/runtime behavior must be classified as runtime-discovered or experimental until validated against the installed Codex version.

---

## 4. Product Principles

### 4.1 Backend first

All parsing, cataloging, validation, merging, backup, rollback, migration, and launch logic lives outside TUI widgets.

### 4.2 Provenance everywhere

Every effective setting should answer:

- what is the value?
- which file supplied it?
- which layer supplied it?
- what lower-precedence value did it override?
- is it supported by the current schema?
- when was it first/last observed?
- can the selected layer legally write it?

### 4.3 No destructive implicit edits

A read/inspect command never changes configuration.

A write operation must:

1. validate the proposed change;
2. display or persist a semantic diff;
3. create a backup;
4. write atomically;
5. re-read the result;
6. re-validate the written file;
7. retain enough metadata for rollback.

### 4.4 Preserve human ownership

Comments, ordering, inline comments, and intentionally disabled example entries should survive ordinary edits wherever TOML semantics allow.

### 4.5 Version everything external

Schema snapshots, Codex version observations, catalog records, generated stock templates, and migrations must carry a version/timestamp/source identity.

### 4.6 Experimental means visibly experimental

Undocumented and unstable settings belong in a separate catalog class. The TUI must not present them as normal supported choices.

---

## 5. Scope

### 5.1 Version 1 scope

CODEX_TUI v1 includes:

- local Codex CLI discovery;
- Codex version detection;
- config layer discovery;
- TOML parsing with comment preservation;
- official schema acquisition and local caching;
- schema snapshot history;
- setting catalog generation;
- type/enum/default/description extraction;
- semantic config validation;
- duplicate/conflict/scope diagnostics;
- current-versus-effective configuration views;
- semantic diffs;
- timestamped backups;
- SHA-256 manifests;
- atomic writes;
- rollback;
- profile-v2 discovery and management;
- legacy `[profiles]` migration;
- CLI frontend;
- Textual TUI frontend;
- launch command that invokes Codex with selected profile/options;
- installed-versus-catalog capability comparison;
- release/schema change reports.

### 5.2 Deferred scope

The following are later milestones:

- remote machine fleet management;
- centralized multi-host policy distribution;
- automatic editing of enterprise-managed requirements;
- remote credential management;
- Codex Desktop profile injection;
- direct package-manager upgrades without explicit user action;
- cloud-hosted configuration storage;
- telemetry collection outside the user's local environment.

---

## 6. Non-Goals

CODEX_TUI is not:

- a replacement for Codex;
- a credential vault;
- an arbitrary TOML editor;
- an updater that modifies Codex automatically;
- a mechanism for bypassing Codex policy enforcement;
- a tool that treats undocumented flags as guaranteed supported behavior.

---

## 7. Architecture

```text
                         +----------------------+
                         |      Textual TUI     |
                         +----------+-----------+
                                    |
                         +----------v-----------+
                         |   Application API    |
                         +----------+-----------+
                                    |
        +---------------------------+----------------------------+
        |                           |                            |
+-------v--------+         +--------v---------+         +--------v---------+
| Config Engine  |         | Catalog/Schema   |         | Codex Adapter    |
| parse/merge    |         | discover/version |         | CLI/app behavior |
| validate/write |         | diff/classify    |         | probes/launch    |
+-------+--------+         +--------+---------+         +--------+---------+
        |                           |                            |
        +---------------------------+----------------------------+
                                    |
                         +----------v-----------+
                         | Local State/History  |
                         | backups/snapshots/db |
                         +----------------------+
```

The TUI and CLI use the same Application API.

---

## 8. Repository Layout

```text
CODEX_TUI/
├── codex_tui/
│   ├── __init__.py
│   ├── app.py
│   ├── cli.py
│   ├── paths.py
│   ├── models.py
│   ├── config/
│   │   ├── parser.py
│   │   ├── layers.py
│   │   ├── effective.py
│   │   ├── validator.py
│   │   ├── diagnostics.py
│   │   ├── normalizer.py
│   │   ├── diff.py
│   │   ├── writer.py
│   │   ├── backup.py
│   │   └── migrate.py
│   ├── schema/
│   │   ├── fetch.py
│   │   ├── snapshot.py
│   │   ├── catalog.py
│   │   ├── classify.py
│   │   └── diff.py
│   ├── codex/
│   │   ├── binary.py
│   │   ├── version.py
│   │   ├── introspect.py
│   │   ├── launch.py
│   │   └── probes.py
│   ├── profiles/
│   │   ├── discover.py
│   │   ├── manager.py
│   │   └── migrate.py
│   ├── history/
│   │   ├── store.py
│   │   ├── manifest.py
│   │   └── retention.py
│   └── tui/
│       ├── app.py
│       ├── bindings.py
│       ├── screens/
│       └── widgets/
├── data/
│   ├── catalog/
│   ├── schemas/
│   ├── stock/
│   └── migrations/
├── tests/
│   ├── fixtures/
│   ├── unit/
│   └── integration/
├── scripts/
├── pyproject.toml
├── README.md
└── PDR.md
```

---

## 9. Technology Decisions

### 9.1 Python

Python is the implementation language for v1 because it supports rapid local tooling, mature TOML libraries, a strong TUI ecosystem, straightforward subprocess integration, and portable testing.

### 9.2 Textual

Textual is the TUI framework. The product architecture must keep Textual-specific code under `codex_tui/tui/`.

### 9.3 tomlkit

`tomlkit` is the primary editable TOML representation because preservation of comments, ordering, and human formatting is a product requirement.

Python `tomllib` remains useful as a strict secondary parser for parse validation where appropriate.

### 9.4 Pydantic

Pydantic models define CODEX_TUI's own internal records and state. Codex configuration validity remains schema-driven rather than being fully duplicated as hand-maintained Pydantic config models.

### 9.5 SQLite

SQLite stores catalog metadata, schema observations, version history, diagnostics, and manifests that benefit from indexed queries.

Raw schema snapshots and backups remain normal files so recovery never depends exclusively on the database.

### 9.6 Git

Git support is optional but recommended for the CODEX_TUI data/history directory. Built-in backup/rollback must function without Git.

---

## 10. Filesystem Layout

Use XDG-compatible paths where available.

```text
~/.config/codex-tui/
    settings.toml

~/.local/share/codex-tui/
    catalog.sqlite3
    schemas/
    stock/
    history/
    backups/
    reports/
    cache/

~/.cache/codex-tui/
    downloads/
    runtime-probes/
```

`CODEX_HOME` is discovered independently and must never be assumed to equal a specific home-directory path.

---

## 11. Core Data Model

### 11.1 SettingDefinition

Minimum fields:

```text
key_path
section
value_type
allowed_values
default_value
description
maturity
introduced_version
deprecated_version
removed_version
aliases
replacement_key
source_kind
source_reference
schema_version
codex_version
project_local_allowed
sensitive
runtime_observed
last_seen
```

### 11.2 ConfigLayer

```text
layer_id
layer_type
path
precedence
enabled
trusted
writable
profile_name
source_version
```

Expected layer types include:

```text
system
managed
cloud_managed
user
user_profile
project
runtime
legacy_managed
```

### 11.3 EffectiveValue

```text
key_path
value
winning_layer
winning_path
overridden_values[]
validation_state
catalog_state
write_scope_state
```

### 11.4 Diagnostic

Severity:

```text
info
warning
error
blocking
```

Kinds include:

```text
parse_error
duplicate
unknown_key
deprecated_key
removed_key
invalid_type
invalid_enum
ignored_scope
conflicting_alias
profile_legacy
runtime_mismatch
schema_mismatch
missing_dependency
unreachable_path
```

### 11.5 BackupManifest

```text
manifest_version
created_at
codex_version
source_path
backup_path
source_sha256
backup_sha256
schema_sha256
operation
semantic_diff_path
rollback_of
```

---

## 12. Schema and Catalog Pipeline

### 12.1 Acquisition

The pipeline must fetch the official Codex JSON schema and cache it locally.

Network behavior:

- use a local cached schema immediately when valid;
- avoid repeated downloads during one run;
- use conditional requests when metadata is available;
- keep immutable snapshots keyed by content hash;
- record acquisition time and source;
- tolerate offline operation using the newest trusted cached snapshot.

### 12.2 Extraction

Generate setting records recursively from the schema.

Extract:

- paths;
- types;
- enums;
- defaults;
- descriptions;
- deprecation markers;
- object/table structure;
- additional-property rules;
- references.

### 12.3 Enrichment

Enrichment may add metadata from official docs and source/runtime observations.

Enrichment never weakens schema validation.

### 12.4 Classification

Every catalog item has one maturity state:

```text
stable
beta
experimental
deprecated
removed
runtime-discovered
unknown
```

### 12.5 Version diff

For any two schema/catalog snapshots, report:

```text
added
removed
renamed
deprecated
type_changed
enum_changed
default_changed
description_changed
scope_changed
maturity_changed
```

---

## 13. Configuration Engine Requirements

### CE-001 Parsing

Parse base and layered TOML while preserving comments and ordering.

### CE-002 Strict syntax validation

Reject malformed TOML before any semantic operation.

### CE-003 Scope awareness

Know the active TOML table for every key and detect common accidental-scope errors.

### CE-004 Layer discovery

Discover applicable Codex layers for a selected working directory.

### CE-005 Effective merge

Compute the effective value and provenance of every known key.

### CE-006 Unknown-key handling

Unknown keys remain visible. They are never silently deleted.

### CE-007 Alias handling

Detect old/new aliases and avoid emitting both when a canonical replacement is known.

### CE-008 Semantic validation

Validate type, allowed values, layer legality, and cross-field constraints where known.

### CE-009 Comment preservation

Ordinary updates must retain unrelated comments and formatting.

### CE-010 Normalization

Normalization is an explicit command. It may reorder or restyle content only with a previewable diff.

---

## 14. Profile Requirements

### PR-001 Profile-v2 discovery

Discover `$CODEX_HOME/*.config.toml` files that represent valid named profiles.

### PR-002 Legacy profile migration

Detect `[profiles.<name>]` and generate a migration plan.

Migration output:

```text
config.toml
safe.config.toml
workspace.config.toml
autonomous.config.toml
full-access.config.toml
reasoning-high.config.toml
...
```

### PR-003 Migration safety

Profile migration must create backups and never remove the legacy tables until the generated files have parsed and validated.

Removal of legacy profile tables is a separate apply step with a semantic diff.

### PR-004 Profile comparison

Compare any profile against base and any other profile.

### PR-005 Profile launch

Launch Codex with the selected named profile without mutating the base config.

---

## 15. Backup, Write, and Rollback Requirements

### WR-001 Pre-write backup

Every config write creates a backup first.

### WR-002 Atomic write

Write to a temporary file in the destination filesystem, flush, validate, then atomically replace the target.

### WR-003 Hashing

Record SHA-256 for before and after states.

### WR-004 Re-validation

Re-open and validate the file after replacement.

### WR-005 Automatic recovery

If post-write validation fails, restore the pre-write backup and report the failed attempted state.

### WR-006 Retention

Default retention:

- preserve all manually named checkpoints;
- preserve last-known-good;
- preserve pre-migration backups;
- preserve recent automatic backups according to configurable count/age limits.

### WR-007 Destructive confirmation

Operations that remove keys, files, profiles, backups, or history require explicit confirmation.

---

## 16. CLI Requirements

The initial executable contract is:

```bash
codex-tui inspect
codex-tui layers
codex-tui validate
codex-tui diff
codex-tui catalog
codex-tui catalog diff
codex-tui profiles
codex-tui profiles migrate
codex-tui backup
codex-tui restore
codex-tui history
codex-tui doctor
codex-tui launch
codex-tui tui
```

### 16.1 `inspect`

Show:

- Codex binary path;
- Codex version;
- CODEX_HOME;
- discovered layers;
- selected profile;
- effective model/reasoning/sandbox/approval values;
- schema snapshot identity;
- diagnostics count;
- plugin/MCP/skills/project summaries;
- unsupported/deprecated/experimental counts.

### 16.2 `layers`

Show precedence, source file, trust state, writability, and active/inactive status.

### 16.3 `validate`

Return process status suitable for scripting:

```text
0 = valid
1 = validation errors
2 = tool/runtime failure
```

### 16.4 `diff`

Default to semantic diff. Provide an optional raw unified diff.

### 16.5 `doctor`

Check:

- Codex binary;
- config readability;
- TOML validity;
- schema cache;
- profile layout;
- duplicate/legacy configuration;
- configured filesystem paths;
- optional MCP endpoints/commands without changing them;
- history-store consistency.

### 16.6 Progress and resumability

Long-running discovery/catalog/update commands must display progress and write checkpoints so interrupted operations can resume safely.

---

## 17. TUI Requirements

### 17.1 Primary layout

Desktop terminal layout:

```text
+----------------------+-------------------------------+----------------------+
| Sections / Layers    | Settings                      | Detail / Provenance  |
|                      |                               |                      |
| Model                | model                         | value                |
| Reasoning            | model_reasoning_effort        | effective source     |
| Approvals            | approval_policy               | allowed values       |
| Sandbox              | sandbox_mode                  | description          |
| Features             | ...                           | maturity             |
| TUI                  |                               | version history      |
| MCP                  |                               | diagnostics          |
| Plugins              |                               |                      |
| Skills               |                               |                      |
| Projects             |                               |                      |
+----------------------+-------------------------------+----------------------+
| status: schema | codex version | profile | diagnostics | modified | backup       |
+----------------------------------------------------------------------------------+
```

### 17.2 Required views

- Dashboard
- Effective Config
- Layer Browser
- Setting Catalog
- Profiles
- Semantic Diff
- Diagnostics
- Backups/History
- Schema/Version Changes
- Launch
- Advanced/Experimental

### 17.3 Setting editor

The editor widget is generated from catalog type:

```text
boolean       -> toggle
enum          -> select
string        -> input
integer       -> numeric input
array         -> list editor
table/map     -> structured editor
path          -> path-aware input
unknown       -> raw TOML editor with warning
```

### 17.4 Search

Search across:

- key path;
- description;
- aliases;
- section;
- allowed values;
- version;
- maturity;
- source;
- diagnostics.

### 17.5 Visual states

At minimum distinguish:

```text
effective
overridden
modified
invalid
deprecated
experimental
runtime-discovered
ignored-at-layer
read-only
```

Color alone must never be the only indicator.

### 17.6 Apply flow

```text
Edit
  -> validate proposed model
  -> semantic diff
  -> explicit apply
  -> backup
  -> atomic write
  -> re-read
  -> re-validate
  -> success / rollback report
```

---

## 18. Codex Introspection Requirements

### CI-001 Binary discovery

Resolve the actual Codex executable used by the shell.

### CI-002 Version capture

Store exact reported Codex version with every catalog/runtime observation.

### CI-003 CLI capability capture

Capture supported help/command output without requiring interactive operation.

### CI-004 Runtime probes

Runtime probes must be:

- read-only by default;
- bounded by timeouts;
- individually logged;
- cached by Codex version;
- explicitly marked when behavior is inferred rather than documented.

### CI-005 Source/schema comparison

Compare installed behavior against the newest known catalog without automatically assuming newest equals installed.

### CI-006 Offline mode

Inspection and editing must continue using cached data when network access is unavailable.

---

## 19. Canonical-Config Migration Required Before v1 Release

The current `config.machine.tui-template.toml` is an input fixture, not the final v1 canonical format.

The first migration must:

1. parse and validate the current merged file;
2. inventory all keys and tables;
3. identify keys unsupported by the current official schema;
4. identify legacy profile tables;
5. split valid profiles into profile-v2 files;
6. classify experimental/runtime-only values;
7. retain all unique local skills, projects, plugins, marketplaces, and MCP definitions that remain valid;
8. produce a semantic migration report;
9. leave the original file untouched;
10. generate a candidate v1 base config and profile directory;
11. require an explicit later apply action before replacing any live Codex config.

Specific known review items include:

- legacy `[profiles.*]` tables;
- `reasoning-max` / `reasoning-ultra` values;
- any feature flags absent from the installed-version schema;
- any TUI identifiers absent from the installed-version catalog;
- any user/project setting stored at a layer where current Codex ignores it.

---

## 20. Security Requirements

### SEC-001 Secrets

Never print environment variable values or credentials merely because a config references them.

### SEC-002 Environment inspection

Inspect names and policy patterns by default. Reading secret values requires a distinct explicit feature and is outside v1.

### SEC-003 MCP

MCP diagnostics may test reachability only when requested by the doctor/probe workflow. No MCP server is modified automatically.

### SEC-004 Shell execution

All subprocess invocations use argument arrays rather than shell interpolation unless a specific shell test requires shell semantics.

### SEC-005 Path handling

Canonicalize paths for diagnostics without rewriting user-authored paths unless explicitly requested.

### SEC-006 File permissions

Backups should preserve or tighten source configuration permissions as appropriate.

### SEC-007 Logs

Logs redact token/secret-like values and command environment contents.

---

## 21. Reliability Requirements

### REL-001 Idempotency

Running inspect, validate, catalog, doctor, or diff repeatedly produces no configuration changes.

### REL-002 Deterministic output

Given the same config files, schema snapshot, Codex version, and working directory, semantic results should be deterministic.

### REL-003 Failure isolation

A failed schema refresh must not corrupt the last trusted schema.

### REL-004 Database independence

Config recovery must remain possible if the SQLite catalog is lost.

### REL-005 Tests

Every migration and write path needs fixture-based tests.

---

## 22. Testing Strategy

### 22.1 Unit tests

Cover:

- TOML parsing;
- table scoping;
- catalog extraction;
- enum validation;
- layer precedence;
- semantic diff;
- profile name validation;
- backup manifests;
- atomic writes;
- schema diff;
- redaction.

### 22.2 Fixture tests

Use anonymized fixtures for:

- current merged machine config;
- malformed empty assignment;
- duplicate MCP representation;
- accidental table scoping;
- legacy profile tables;
- project-local ignored keys;
- unsupported feature flags;
- profile-v2 base/overlay behavior.

### 22.3 Integration tests

Run against an installed Codex binary when available.

Integration tests must skip cleanly when Codex is absent.

### 22.4 Golden tests

Maintain expected semantic diagnostics and normalized output for representative configs.

---

## 23. Observability

CODEX_TUI's own logging is local and separate from Codex OTEL settings.

Log events:

```text
startup
codex_discovered
schema_loaded
schema_refreshed
layers_discovered
validation_complete
backup_created
write_started
write_complete
write_failed
rollback_started
rollback_complete
profile_migration_planned
profile_migration_applied
runtime_probe_complete
```

Default logs must avoid prompt content and secret values.

---

## 24. Performance Targets

For a normal local configuration:

- initial cached startup: under 1 second target;
- config parse/validation: under 250 ms target;
- semantic diff: under 250 ms target;
- catalog search interaction: perceived immediate;
- network schema refresh occurs asynchronously from the UI interaction path only when the architecture supports it safely; CLI commands remain synchronous and report progress;
- no repeated network fetch within a single operation.

These are engineering targets rather than release blockers for the first prototype.

---

## 25. Versioning and Historical Catalog

Each Codex version observation creates or references:

```text
codex version
schema content hash
schema acquisition time
documentation observation time
source commit/revision when available
runtime probe set
catalog snapshot
```

The TUI must support:

```text
Installed
Latest cached
Previous
Compare...
```

A version-change report should answer:

- what settings appeared?
- what disappeared?
- what enum values changed?
- what defaults changed?
- what aliases/deprecations appeared?
- what did this machine use that is now unsupported?
- what new settings are available but unset?

---

## 26. Acceptance Criteria for v1

CODEX_TUI v1 is ready when all of the following are true:

1. It can discover the live Codex base config without modifying it.
2. It can parse the current machine fixture while preserving comments.
3. It can identify the legacy profile tables in the fixture.
4. It can generate separate profile-v2 candidates.
5. It can validate base/profile candidates against a pinned schema snapshot.
6. It can explain effective values and provenance across layers.
7. It can flag keys that are ignored at their current layer.
8. It can classify unknown/deprecated/experimental keys without deleting them.
9. It can create a timestamped backup and manifest.
10. It can apply a test edit atomically.
11. It can restore the exact pre-edit bytes.
12. It can produce a semantic diff before apply.
13. It can operate offline with cached schema/catalog data.
14. The CLI can perform inspect, validate, diff, profiles, backup, restore, doctor, and launch workflows.
15. The TUI can browse and edit the same Application API used by the CLI.
16. Automated tests cover the known failure modes from the two original configs.

---

## 27. Milestones

### M0 — PDR and fixtures

Deliver:

- this PDR;
- canonical input fixture;
- known-issues fixture set;
- architecture decisions.

Exit condition: data model and write safety rules are frozen enough to code.

### M1 — Config/schema engine

Deliver:

- project scaffold;
- path discovery;
- `tomlkit` parser;
- schema fetch/cache/snapshot;
- catalog extraction;
- strict validation;
- diagnostics;
- semantic diff.

Exit condition:

```bash
codex-tui inspect
codex-tui validate
codex-tui diff
codex-tui catalog
```

work against fixtures and a live config in read-only mode.

### M2 — Backup/write/rollback

Deliver:

- manifests;
- atomic writer;
- retention;
- restore;
- golden tests.

Exit condition: byte-exact rollback passes automated tests.

### M3 — Profiles

Deliver:

- profile-v2 discovery;
- legacy migration;
- profile diff;
- profile launch.

Exit condition: current canonical fixture can be converted into base + profile candidate files without touching the live config.

### M4 — Introspection/version history

Deliver:

- Codex version capture;
- capability probes;
- schema/catalog snapshots;
- version-diff report;
- offline cache behavior.

### M5 — Textual TUI

Deliver:

- dashboard;
- sections/settings/detail panes;
- diagnostics;
- editor widgets;
- diff/apply workflow;
- backups/history;
- profile selector;
- advanced/experimental browser.

### M6 — Hardening

Deliver:

- integration tests;
- failure injection;
- recovery tests;
- packaging;
- install/uninstall docs;
- release checklist.

---

## 28. First Implementation Slice

The first code slice after this PDR should implement only read-only capabilities:

```text
1. project scaffold
2. XDG/CODEX_HOME path resolver
3. Codex binary/version resolver
4. tomlkit config loader
5. layer record model
6. official schema fetch + immutable cache
7. schema catalog extractor
8. validation diagnostics
9. semantic diff model
10. `inspect`, `validate`, `catalog`, `diff`
```

No live configuration writes belong in the first slice.

The current machine config should be represented by an anonymized copy in `tests/fixtures/` and treated as immutable test input. The real machine configuration remains local-only.

---

## 29. Design Decisions Frozen by This PDR

The following choices are accepted for implementation unless a discovered Codex constraint requires revision:

- Python implementation;
- Textual frontend;
- `tomlkit` editable TOML model;
- Pydantic internal records;
- SQLite catalog/history metadata;
- schema-driven setting catalog;
- CLI and TUI sharing one backend;
- profile-v2 as the target profile format;
- immutable schema snapshots;
- semantic diffs;
- pre-write backup on every write;
- atomic replacement;
- byte-exact rollback target;
- XDG-compatible CODEX_TUI state paths;
- experimental settings isolated from normal supported settings;
- live configs remain untouched through M1.

---

## 30. Immediate Next Action

Start milestone M1 with the repository scaffold and read-only engine.

The first implementation checkpoint is successful when this sequence works:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'

codex-tui inspect --config tests/fixtures/config.machine.tui-template.toml
codex-tui validate --config tests/fixtures/config.machine.tui-template.toml
codex-tui catalog
codex-tui diff \
  tests/fixtures/config.machine.tui-template.toml \
  tests/fixtures/config.machine.tui-template.toml
```

Expected behavior:

- progress is visible for schema acquisition/catalog building;
- the original fixture is never changed;
- diagnostics identify the legacy profile representation and any current-schema mismatches;
- running the commands repeatedly is idempotent;
- cached schema data prevents unnecessary repeat downloads.
