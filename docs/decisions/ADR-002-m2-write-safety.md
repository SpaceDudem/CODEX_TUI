# ADR-002: M2 write safety contract

**Date:** 2026-08-30  
**Status:** Implemented by M2

## Context

M1 intentionally had no live configuration writer. M2 introduces mutation only after recovery primitives are independently testable and the destructive CLI surface is protected by explicit review and concurrency checks.

## Required write sequence

Every managed write executes in this order:

1. Acquire the per-target CODEX_TUI advisory lock.
2. Read source bytes and metadata through a no-follow file descriptor.
3. Compare the source SHA-256 with the caller's required expected hash.
4. Parse and validate the proposed candidate against the selected Codex schema snapshot.
5. Produce a semantic diff before the CLI requests confirmation.
6. Create a timestamped backup and SHA-256 manifest.
7. Flush and fsync the backup payload and manifest, then sync their directories where supported.
8. Re-check the target hash.
9. Write candidate bytes to a temporary file in the destination directory.
10. Apply the intended permission mode, flush, and fsync the temporary file.
11. Re-read and validate the exact temporary bytes.
12. Re-check the target hash immediately before replacement.
13. Atomically replace the target.
14. fsync the containing directory where supported.
15. Re-read target bytes through a no-follow descriptor and validate again.
16. Verify final SHA-256 and permission mode.
17. If post-replacement verification fails, restore the exact pre-write bytes from the verified backup and verify the restored hash and mode.

## Guardrails

- No shell interpolation for filesystem operations.
- Symbolic-link sources, candidates, targets, manifests, payloads, and lock-file substitutions are rejected where they cross a managed trust boundary.
- Managed reads use a single descriptor with `O_NOFOLLOW` where available and `fstat` identity/type validation.
- The source path, backup path, schema hash, before hash, proposed hash, final hash, operation ID, and rollback relationship are recorded.
- Backup content never depends exclusively on SQLite; raw files and JSON manifests remain independently recoverable.
- Backup payloads/manifests are private files and backup directories must not permit group/world access.
- Recovery manifests are bound to the selected trusted backup root.
- A restore cannot target a different path than the path represented by its backup manifest.
- Restore rejects special permission bits and refuses to broaden the current target's permission mask.
- `restore` never deletes the backup it restores from and first snapshots the state it will overwrite.
- Automatic retention cannot remove manually named checkpoints, last-known-good state, or migration checkpoints.
- Live writes require explicit user invocation and confirmation unless `--yes` is deliberately supplied.
- `apply` and `restore` require an expected SHA-256 of the target state reviewed by the caller.
- Read-only commands remain idempotent.

## Concurrency model

CODEX_TUI creates a persistent private sidecar lock file and holds a POSIX advisory `flock` across the managed write transaction. This prevents two cooperating CODEX_TUI writers from interleaving the final hash check and replacement.

POSIX advisory locks cannot force an unrelated editor or process to participate. Therefore the tool does not claim an atomic compare-and-swap guarantee against arbitrary external writers. External changes are detected optimistically through the required caller-supplied SHA-256 plus repeated target-hash checks up to the atomic replacement boundary. This limitation is surfaced as part of the write-safety model rather than hidden.

The M2 mutation implementation is intentionally POSIX-only while this lock contract is in force. Read-only M1 behavior is not subject to that restriction.

## Directory durability

File data is fsynced before replacement. Directory metadata is also fsynced after backup-record creation and atomic replacement. Only platform/filesystem errors explicitly indicating unsupported directory synchronization are tolerated; other directory-sync failures propagate and are treated as write failures.

## M2 acceptance boundary

The live `apply` workflow is permitted only after automated tests prove:

- byte-exact backup and restore;
- same-filesystem atomic replacement;
- source permission preservation;
- required expected-hash stale-source detection;
- competing CODEX_TUI writer exclusion;
- automatic rollback after injected post-write verification failure;
- manifest and payload integrity checks;
- trusted-root and cross-target restore enforcement;
- permission-broadening rejection;
- no-follow managed reads;
- interruption-safe temporary-file cleanup;
- idempotent backup/history inspection commands;
- CLI confirmation and sensitive-value redaction;
- pinned-schema validation before `apply` creates a recovery artifact or modifies a target.
