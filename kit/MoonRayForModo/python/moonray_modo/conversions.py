"""Texture conversions run side by side while a scene is written, and waited for once at its end.

Each conversion (maketx for MoonRay, oiiotool for MoonLightIPR) is a program of its own, run once per texture and
cached. Run one after another, a scene of a few hundred textures took minutes to convert (a tester's: 9 minutes).
Inside together(), a conversion is started and the scene goes on being written with the path it will have; at the
end of together() every conversion is waited for, and the first that failed is raised. Outside it, a conversion is
done at once, as before.
"""
import concurrent.futures
import contextlib
import contextvars
import os
import threading

_pool = None
_lock = threading.Lock()
_batch = contextvars.ContextVar('moonray_conversion_batch', default=None)


def _executor():
    global _pool
    with _lock:
        if _pool is None:
            # Each converter uses a few threads of its own; half the processor's threads, at most eight at a time.
            _pool = concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, (os.cpu_count() or 2) // 2)),
                                                          thread_name_prefix='MoonRayTextures')
        return _pool


class Batch:
    def __init__(self):
        self.jobs = {}

    def submit(self, key, work):
        if key not in self.jobs:
            # Run as the caller would have (its colour settings are context variables), converting at once there.
            context = contextvars.copy_context()
            context.run(_batch.set, None)
            self.jobs[key] = _executor().submit(context.run, work)
        return self.jobs[key]

    def wait(self):
        failed = None
        for job in list(self.jobs.values()):
            try:
                job.result()
            except Exception as error:
                failed = failed or error
        if failed is not None:
            raise failed


@contextlib.contextmanager
def together():
    """Conversions asked for inside run side by side, and are all done when it ends. Nested, the outermost waits."""
    if _batch.get() is not None:
        yield _batch.get()
        return
    batch = Batch()
    token = _batch.set(batch)
    try:
        yield batch
        batch.wait()
    finally:
        _batch.reset(token)


def run(key, work):
    """Do work (which makes the file key names) now, or, inside together(), alongside the others."""
    batch = _batch.get()
    if batch is None:
        work()
    else:
        batch.submit(key, work)
