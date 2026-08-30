# M2 implementation plan — backup/write/rollback

This plan implements `docs/decisions/ADR-002-m2-write-safety.md`.

## Slice A — recovery primitives

- SHA-256 file hashing
- immutable backup file creation
- JSON manifest creation and verification
- permission capture/preservation
- backup discovery and inspection
- byte-exact restore to test targets

## Slice B — atomic writer

- stale-source hash check
- symlink rejection
- same-directory temporary file
- flush + fsync
- parse/validation callback before replace
- atomic `os.replace`
- containing-directory fsync where supported
- post-replace hash/read/validation
- automatic rollback on injected or real post-write verification failure
- temporary-file cleanup

## Slice C — CLI exposure

Before live apply is exposed:

- `backup --config PATH`
- `history --config PATH`
- `restore --backup MANIFEST --target PATH` with explicit confirmation
- test-only candidate apply API

Only after all M2 recovery acceptance tests are green:

- `apply --config PATH --candidate PATH --expected-sha SHA256`

`apply` remains explicit and never targets a live config by default during CI/tests.
