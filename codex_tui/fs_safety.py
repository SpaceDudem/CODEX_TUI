from __future__ import annotations

import errno
import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from codex_tui.errors import TargetLockError, UnsafePathError

_UNSUPPORTED_DIRECTORY_SYNC_ERRNOS = {
    errno.EINVAL,
    getattr(errno, "ENOTSUP", errno.EINVAL),
    getattr(errno, "EOPNOTSUPP", errno.EINVAL),
}


def read_regular_file_nofollow(path: Path, *, role: str) -> tuple[bytes, os.stat_result]:
    """Read a regular file through one descriptor without following a final symlink."""

    target = path.expanduser().absolute()
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    initial: os.stat_result | None = None
    if not nofollow:
        try:
            initial = target.lstat()
        except OSError as exc:
            raise UnsafePathError(f"Unable to inspect {role} {target}: {exc}") from exc
        if stat.S_ISLNK(initial.st_mode):
            raise UnsafePathError(f"Refusing symbolic-link {role}: {target}")

    flags = os.O_RDONLY | nofollow
    try:
        fd = os.open(target, flags)
    except OSError as exc:
        raise UnsafePathError(f"Unable to open {role} safely {target}: {exc}") from exc

    try:
        current = os.fstat(fd)
        if not stat.S_ISREG(current.st_mode):
            raise UnsafePathError(f"Managed {role} is not a regular file: {target}")
        if initial is not None and (initial.st_dev, initial.st_ino) != (current.st_dev, current.st_ino):
            raise UnsafePathError(f"Managed {role} changed identity while opening: {target}")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            content = handle.read()
        if initial is not None:
            final = target.lstat()
            if stat.S_ISLNK(final.st_mode) or (final.st_dev, final.st_ino) != (
                current.st_dev,
                current.st_ino,
            ):
                raise UnsafePathError(f"Managed {role} changed identity while reading: {target}")
        return content, current
    finally:
        os.close(fd)


def fsync_directory(directory: Path) -> None:
    """Persist directory metadata, suppressing only known unsupported-platform errors."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(directory, flags)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_DIRECTORY_SYNC_ERRNOS:
            return
        raise
    try:
        try:
            os.fsync(fd)
        except OSError as exc:
            if exc.errno not in _UNSUPPORTED_DIRECTORY_SYNC_ERRNOS:
                raise
    finally:
        os.close(fd)


@contextmanager
def target_lock(target: Path, *, timeout_seconds: float = 5.0) -> Iterator[Path]:
    """Serialize CODEX_TUI writers for one target using a persistent advisory lock file."""

    if os.name != "posix":
        raise TargetLockError("Managed write locking is currently supported only on POSIX systems")

    import fcntl

    path = target.expanduser().absolute()
    lock_path = path.parent / f".{path.name}.codex-tui.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise TargetLockError(f"Unable to open target lock {lock_path}: {exc}") from exc

    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise TargetLockError(f"Target lock is not a regular file: {lock_path}")
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        else:
            os.chmod(lock_path, 0o600)

        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                if time.monotonic() >= deadline:
                    raise TargetLockError(
                        f"Timed out waiting for managed target lock: {lock_path}"
                    ) from exc
                time.sleep(min(0.05, max(deadline - time.monotonic(), 0.0)))

        yield lock_path
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        os.close(fd)
