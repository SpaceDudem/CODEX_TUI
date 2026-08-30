# ADR-002: M2 write safety contract

**Date:** 2026-08-30  
**Status:** Accepted for M2 implementation

## Context

M1 intentionally has no live configuration writer. M2 introduces mutation only after recovery primitives are independently testable.

## Required write sequence

Every managed write must execute in this order:

1. Read source bytes and metadata.
2. Parse the source and proposed candidate.
3. Validate the proposed candidate against the selected schema snapshot.
4. Produce a semantic diff.
5. Create a timestamped backup and SHA-256 manifest.
6. Write candidate bytes to a temporary file in the destination directory.
7. Flush file data and fsync the temporary file.
8. Preserve appropriate source permissions.
9. Re-read and validate the temporary file.
10. Atomically replace the target.
11. fsync the containing directory where supported.
12. Re-read target bytes and validate again.
13. Record post-write SHA-256 and success state.
14. If post-replacement verification fails, restore the exact pre-write bytes from the backup and verify the restored hash.

## Guardrails

- No shell interpolation for filesystem operations.
- Symbolic-link targets are rejected by default for managed writes until an explicit symlink policy is implemented.
- The source path, backup path, schema hash, before hash, proposed hash, final hash, operation ID, and rollback relationship are recorded.
- Backup content never depends exclusively on SQLite; raw files and manifests remain independently recoverable.
- `restore` never deletes the backup it restores from.
- Automatic retention cannot remove manually named checkpoints, last-known-good state, or migration checkpoints.
- Live writes require explicit user invocation. Read-only commands remain idempotent.
- Before overwriting an externally changed target, CODEX_TUI compares the current hash to the hash observed when the proposed change was prepared and aborts on mismatch.

## M2 acceptance boundary

A live `apply` workflow stays disabled until tests prove:

- byte-exact backup and restore;
- atomic replacement on the same filesystem;
- source permission preservation;
- stale-source/concurrent-change detection;
- automatic rollback after injected post-write verification failure;
- manifest integrity checks;
- interruption-safe temporary-file cleanup;
- idempotent backup/restore inspection commands.
