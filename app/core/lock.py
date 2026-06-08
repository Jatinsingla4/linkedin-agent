"""Single-instance file lock.

Prevents two agent runs from polling Telegram's ``getUpdates`` at once (which
causes HTTP 409 Conflict and dropped commands). Uses ``fcntl.flock`` where
available; degrades to a no-op on platforms without it.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class LockHeldError(RuntimeError):
    """Raised when another instance already holds the lock."""


@contextmanager
def single_instance(lock_path: str | Path = ".agent.lock"):
    """Acquire an exclusive lock for the duration of the context.

    Raises :class:`LockHeldError` if another process holds it.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-unix fallback
        logger.debug("fcntl unavailable — running without single-instance lock")
        yield
        return

    path = Path(lock_path)
    handle = open(path, "w")
    try:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            handle.close()
            raise LockHeldError(f"Another agent instance is already running ({lock_path})") from e
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()
