"""One build at a time writes the layout reports: a competing build waits.

The lock is taken on a file, with the interface of the system: flock where
it exists (Linux, macOS), msvcrt on Windows. Where neither does, the build
goes on without a lock rather than failing: a lock is a convenience between
two builds of the same project, not a condition for producing a report.
"""
from contextlib import contextmanager
from pathlib import Path
import os
import time

try:                                    # Linux, macOS
    import fcntl

    def _take(stream):
        """Take the lock, or raise BlockingIOError if another build has it."""
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(stream):
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

except ImportError:                     # pragma: no cover - Windows
    try:
        import msvcrt

        # The lock is a byte far beyond the pid written at the start of the
        # file: on Windows a locked byte cannot be written, even by its owner.
        _OFFSET = 1 << 30

        def _take(stream):
            stream.seek(_OFFSET)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:    # EACCES: the file is locked by another build
                raise BlockingIOError(str(error)) from None

        def _release(stream):
            try:
                stream.seek(_OFFSET)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

    except ImportError:                 # a system with neither: no lock
        def _take(stream):
            return None

        def _release(stream):
            return None

TIMEOUT = 600       # seconds: a measure of a whole deck takes a few minutes


@contextmanager
def report_lock(folder, log=None, timeout=TIMEOUT, poll=1.0):
    path = Path(str(Path(folder).resolve()) + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as stream:
        start, waiting = time.monotonic(), False
        while True:
            try:
                _take(stream)
                break
            except BlockingIOError:
                if time.monotonic() - start >= timeout:
                    raise RuntimeError(f'Another build has been writing {folder} for {timeout} s; '
                                       f'retry after it finishes') from None
                if log is not None and not waiting:
                    log.info(f'Another build is writing {folder}: waiting for it ...')
                waiting = True
                time.sleep(poll)
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid()))
        stream.flush()
        try:
            yield
        finally:
            _release(stream)
