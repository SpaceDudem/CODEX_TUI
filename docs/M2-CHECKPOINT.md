# M2 checkpoint — backup, atomic write, and rollback

M2 is complete when this document is merged to `main` with the final acceptance CI green.

## Delivered

- Immutable byte-exact backup payloads with SHA-256 JSON manifests.
- Source size and permission-mode capture.
- Private backup directory, manifest, and payload permissions.
- Trusted backup-root binding for recovery manifests.
- Same-bytes backup verification through one no-follow descriptor.
- No-follow managed source/target reads with regular-file and identity checks.
- Candidate TOML validation before backup or replacement.
- Pinned Codex JSON-schema validation before `apply` creates a recovery artifact.
- Semantic change preview with sensitive-value redaction.
- Required caller-supplied SHA-256 concurrency token for `apply` and `restore`.
- Per-target POSIX advisory lock covering the managed write transaction.
- Same-directory temporary candidate writes.
- File and directory fsync durability handling.
- Atomic `os.replace` target replacement.
- Permission-mode preservation for normal apply.
- Post-write hash, mode, TOML/schema, and optional runtime verification hooks.
- Automatic byte-exact rollback after post-replacement verification failures.
- Historical restore that first snapshots the state it will overwrite.
- Cross-target restore rejection.
- Unsafe/special restore permission rejection and permission-broadening prevention.
- `backup`, `history`, `restore`, and `apply` CLI commands.
- Interactive destructive confirmation with deliberate `--yes` override.
- Recovery artifacts are never consumed or deleted by restore.

## Automated acceptance

The M2 suite covers:

- byte-exact backup and manifest verification;
- tampered payload detection;
- manifest payload path-escape detection;
- symbolic-link source/target rejection;
- stale expected-hash rejection before backup/replacement;
- invalid TOML candidate rejection before backup;
- schema-invalid candidate rejection before backup;
- mode preservation;
- temporary-file cleanup;
- injected post-replace failure and exact automatic rollback;
- historical restore plus pre-restore checkpoint creation;
- single-descriptor managed target reads;
- competing CODEX_TUI writer lock timeout;
- `fchmod` portability fallback;
- real directory-fsync failure propagation;
- explicitly unsupported directory-fsync tolerance;
- trusted backup-root enforcement;
- cross-target restore rejection;
- permission-broadening rejection;
- CLI backup/history flow;
- CLI semantic apply preview;
- CLI confirmation behavior;
- CLI sensitive-value redaction;
- CLI stale-token and schema-validation failures.

At the checkpoint freeze, the Python 3.11/3.12 suite contains at least 45 passing tests. Final acceptance additionally requires compilation, Ruff, strict mypy, and the live official Codex schema smoke job to pass on the final documentation/code head.

## Concurrency boundary

The per-target lock is an advisory POSIX lock and serializes cooperating CODEX_TUI writers. An unrelated process can ignore that lock. The required SHA-256 token and repeated target checks detect external changes up to the replacement boundary, but M2 does not claim a kernel-enforced content compare-and-swap against arbitrary external writers.

This limitation is explicit in `docs/decisions/ADR-002-m2-write-safety.md`.

## Safety boundary for M3+

M3 profile migration must use these M2 primitives rather than inventing a separate writer. Candidate profile generation and migration planning should remain read-only until the user explicitly applies a migration plan.

No retention/deletion command is introduced by M2. Recovery-history deletion remains a later, explicitly destructive feature.
