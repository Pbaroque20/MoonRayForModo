"""Python's garbage collection on Modo's main thread only.

Python collects reference cycles on whichever thread happens to allocate when a threshold is crossed: often one of the
kit's worker threads (display conversion, scene packing, cache writing). A cycle can hold objects of Modo's, and
freeing those off Modo's main thread runs Modo's code on a thread Modo keeps no state for. On 2026-11-18 Modo crashed
so (0xC0000005 in valet3000's CkptBeginBuf, which reads its undo state from thread-local storage) while a display worker
was making a threading.Timer, as a camera item was clicked during a MoonLightIPR realtime preview.

So once a window of the kit's is up, automatic collection is off and a timer on the main thread collects instead,
when Python itself would: the same thresholds, generation by generation. A full collection also waits until the last
one's time is under 2% of the time since, as Python's own rule keeps full collections rare.

Only where Qt's event loop runs (a window of the kit's), never at import: in modo_cl no timer would ever fire, and
cycles would never be collected."""
import gc
import threading
import time

INTERVAL_MS = 100
FULL_SHARE = 0.02
_state = {'timer': None, 'full_took': 0.0, 'full_at': 0.0}


def due(counts, thresholds, full_allowed=True):
    """The generation Python would collect now for these counts (gc.get_count()) and thresholds (gc.get_threshold()),
    or None. As Python: nothing until the youngest is over its threshold, then the oldest that is over its own; the
    full one only where allowed."""
    if not thresholds[0] or counts[0] <= thresholds[0]:
        return None
    if full_allowed and counts[2] > thresholds[2]:
        return 2
    if counts[1] > thresholds[1]:
        return 1
    return 0


def collect():
    """The timer's tick on the main thread."""
    if gc.isenabled():
        gc.disable()    # switched back on by someone: the worker threads must not collect
    now = time.perf_counter()
    generation = due(gc.get_count(), gc.get_threshold(), now - _state['full_at'] >= _state['full_took'] / FULL_SHARE)
    if generation is None:
        return None
    gc.collect(generation)
    if generation == 2:
        _state['full_at'] = time.perf_counter()
        _state['full_took'] = _state['full_at'] - now
    return generation


def install():
    """From a window of the kit's, on the main thread: collection moves to a timer there, once. True where it is in
    place."""
    # What Modo holds of the kit's is let go of as Modo quits: hooked here too, where Qt's application was not up yet
    # as the kit's servers were loaded.
    try:
        from . import quit_release
        quit_release.hook()
    except ImportError:
        pass    # loaded on its own, as in tests
    if _state['timer'] is not None:
        return True
    if threading.current_thread() is not threading.main_thread():
        return False
    try:
        from PySide2 import QtCore
    except ImportError:
        return False
    application = QtCore.QCoreApplication.instance()
    if application is None or QtCore.QThread.currentThread() is not application.thread():
        return False
    # No parent: Python owns the timer and frees it while Python still stands. Parented to Qt's application, it was
    # freed by Modo after Python had been finalized, and Modo crashed so on every quit (python39 PyErr_Fetch under
    # shiboken's SbkDeallocWrapper, from QObject::~QObject in front3000's WManShutdown; tools/probe_quit_release.py).
    timer = QtCore.QTimer()
    timer.setInterval(INTERVAL_MS)
    timer.timeout.connect(collect)
    timer.start()
    _state['timer'] = timer
    application.aboutToQuit.connect(quitting)
    gc.disable()
    return True


def quitting():
    """Modo is quitting: the timer stopped, and collection Python's own again for the way out."""
    timer = _state['timer']
    if timer is not None:
        timer.stop()
    gc.enable()
