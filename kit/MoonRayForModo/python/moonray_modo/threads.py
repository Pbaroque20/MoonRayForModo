"""Python's stand-ins for threads it did not start.

A QThread runs its run() on a thread Qt starts. The first time Python code there asks which thread it is on, Python
makes a stand-in for it in its table of threads, and never takes it out: Python only takes out threads it started
itself. Every display, packing and scene-writing thread left one behind, eight or so for each MoonRay render.
"""
import functools
import threading


def forgotten(run):
    """For a QThread's run(): take this thread's stand-in out of Python's table when run() is done."""
    @functools.wraps(run)
    def running(self, *args, **kwargs):
        try:
            return run(self, *args, **kwargs)
        finally:
            held = threading._active.get(threading.get_ident())
            if isinstance(held, threading._DummyThread):
                threading._active.pop(threading.get_ident(), None)
    return running
