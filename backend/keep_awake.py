"""Prevent automatic Windows sleep only while the real service is running."""
from contextlib import contextmanager
import sys
import threading


@contextmanager
def keep_awake(enabled):
    if not enabled or sys.platform != 'win32':
        yield
        return
    stop = threading.Event()
    def hold():
        import ctypes
        continuous = 0x80000000
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(continuous | 0x00000001)
            stop.wait()
        finally:
            ctypes.windll.kernel32.SetThreadExecutionState(continuous)
    thread = threading.Thread(target=hold, name='prevent-idle-sleep', daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join()
