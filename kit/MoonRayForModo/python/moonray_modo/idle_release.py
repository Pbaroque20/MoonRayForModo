"""Release completed renderer sessions without interrupting work or discarding cached images."""
import time
from PySide2 import QtCore


class IdleRelease(QtCore.QObject):
    def __init__(self, parent, release, available):
        super().__init__(parent)
        self.release = release
        self.available = available
        self.since = None
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    def arm(self):
        # Arm before emitting completion: a completion handler may submit the next pass.
        self.since = time.monotonic()
        self.timer.start()

    def cancel(self):
        self.since = None
        self.timer.stop()

    def release_now(self):
        if self.since is None or not self.available():
            return False
        self.cancel()
        self.release()
        return True

    def _tick(self):
        from .preferences import Preferences
        minutes = max(0, Preferences().get('idle_release_minutes'))
        if minutes and self.since is not None and time.monotonic() - self.since >= minutes * 60:
            self.release_now()
