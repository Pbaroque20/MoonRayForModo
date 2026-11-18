# python
"""Isolated GUI test: whether the preview's live timer keeps ticking while Modo's message queue never empties, as in a
drag of an item on its keyframe with Auto Key on (the preview looked once in a 30 s drag). The queue is kept full by a
zero-interval timer doing a little work each time; the live timer's ticks are counted over 3 s, idle, then busy with
a coarse timer (a WM_TIMER on Windows, made only when the queue is empty) and with a precise one (posted). Writes
test-results/timer-starvation/report.json."""
import json
import pathlib
import time
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/timer-starvation'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {'ticks': 0}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1))


def counted():
    held['ticks'] += 1


def busy():
    # A few milliseconds of work on Modo's thread, again at once: the queue is never empty.
    until = time.perf_counter() + 0.004
    while time.perf_counter() < until:
        pass


def measure(name, kind, loaded, next_step):
    from moonray_modo.panel import Panel
    panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    timer = QtCore.QTimer()
    timer.setTimerType(kind)
    timer.setInterval(60)
    timer.timeout.connect(counted)
    held['ticks'] = 0
    load = QtCore.QTimer()
    load.setInterval(0)
    load.timeout.connect(busy)
    began = time.perf_counter()
    timer.start()
    if loaded:
        load.start()

    def stop():
        load.stop()
        timer.stop()
        seconds = time.perf_counter() - began
        result[name] = {'ticks': held['ticks'], 'seconds': round(seconds, 2), 'expected': int(seconds / 0.06),
                        'panel timer type': str(panel.timer.timerType())}
        save()
        QtCore.QTimer.singleShot(500, next_step)
    held['stop'] = QtCore.QTimer()
    held['stop'].setSingleShot(True)
    held['stop'].setTimerType(QtCore.Qt.PreciseTimer)
    held['stop'].timeout.connect(stop)
    held['stop'].start(3000)


def finish():
    result['done'] = True
    save()
    lx.eval('!app.quit')


lx.eval('moonray.page preview')
QtCore.QTimer.singleShot(3000, lambda: measure('idle, coarse', QtCore.Qt.CoarseTimer, False,
    lambda: measure('busy, coarse', QtCore.Qt.CoarseTimer, True,
        lambda: measure('busy, precise', QtCore.Qt.PreciseTimer, True, finish))))
save()
