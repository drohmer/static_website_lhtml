import threading
import time

import pytest

from lib.report_lock import report_lock


class Log:
    def __init__(self):
        self.lines = []

    def keyvalue(self, key, value, **kwargs):
        self.lines.append(value)


def test_competing_build_gives_up_after_the_timeout(tmp_path):
    with report_lock(tmp_path / '.layout'):
        with pytest.raises(RuntimeError, match='Another build'):
            with report_lock(tmp_path / '.layout', timeout=0.2, poll=0.05):
                pass
    with report_lock(tmp_path / '.layout'):         # released
        pass


def test_competing_build_waits_for_the_first_one(tmp_path):
    released, log = threading.Event(), Log()

    def first():
        with report_lock(tmp_path / '.layout'):
            time.sleep(0.3)
        released.set()

    thread = threading.Thread(target=first)
    thread.start()
    time.sleep(0.1)
    with report_lock(tmp_path / '.layout', log, timeout=5, poll=0.05):
        assert released.is_set()
    thread.join()
    assert len(log.lines) == 1 and 'waiting' in log.lines[0]
