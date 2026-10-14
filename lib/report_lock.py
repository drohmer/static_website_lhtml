"""One build at a time writes the layout reports: a competing build waits."""
from contextlib import contextmanager
from pathlib import Path
import fcntl
import os
import time

TIMEOUT = 600       # seconds: a measure of a whole deck takes a few minutes


@contextmanager
def report_lock(folder, log=None, timeout=TIMEOUT, poll=1.0):
    path = Path(str(Path(folder).resolve()) + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as stream:
        start, waiting = time.monotonic(), False
        while True:
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() - start >= timeout:
                    raise RuntimeError(f'Another build has been writing {folder} for {timeout} s; '
                                       f'retry after it finishes') from None
                if log is not None and not waiting:
                    log.keyvalue('info', f'Another build is writing {folder}: waiting for it ...', indent_level=2)
                waiting = True
                time.sleep(poll)
        stream.seek(0)
        stream.truncate()
        stream.write(str(os.getpid()))
        stream.flush()
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
