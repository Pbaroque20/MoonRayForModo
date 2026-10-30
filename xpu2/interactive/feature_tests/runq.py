"""Shared helpers for the comparison scripts: a render queue of a few slots across every running script (lock files
in slots/, a dead holder's slot reclaimed), and a cache of MoonRay references by the scene's content, the frame, the
mode and the MoonRay build (refcache/)."""
import hashlib
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

S = Path(__file__).resolve().parent
SLOTS = S / 'slots'
CACHE = S / 'refcache'
SLOT_COUNT = int(os.environ.get('RUNQ_SLOTS', '2'))


def _alive(pid):
    try:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    except Exception:
        return True


@contextmanager
def slot():
    """Holds one of SLOT_COUNT render slots for the block (waits for a free one)."""
    SLOTS.mkdir(exist_ok=True)
    held = None
    while held is None:
        for k in range(SLOT_COUNT):
            path = SLOTS / ('slot%d.lock' % k)
            try:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                held = path
                break
            except FileExistsError:
                try:
                    pid = int(path.read_text() or '0')
                    if pid and not _alive(pid):
                        path.unlink()
                except (OSError, ValueError):
                    pass
        if held is None:
            time.sleep(1.0)
    try:
        yield
    finally:
        try:
            held.unlink()
        except OSError:
            pass


def threads():
    """Threads a render takes: the machine's share of one slot."""
    return max(2, (os.cpu_count() or 12) // SLOT_COUNT)


def reference_key(scene_text, out_path, frame, mode, exe):
    """The cache key of a MoonRay render: its scene with the output's path neutral, frame, mode, MoonRay's build."""
    neutral = scene_text.replace(Path(out_path).as_posix(), 'OUTPUT')
    st = Path(exe).stat()
    h = hashlib.sha256()
    for part in (neutral, str(frame), mode, str(st.st_size), str(int(st.st_mtime))):
        h.update(part.encode('utf-8'))
        h.update(b'\0')
    return h.hexdigest()[:32]


def cached(key, out_path):
    """Copies a cached reference to out_path; whether it was there."""
    src = CACHE / (key + '.exr')
    if src.exists():
        shutil.copyfile(src, out_path)
        return True
    return False


def store(key, out_path):
    CACHE.mkdir(exist_ok=True)
    if Path(out_path).exists():
        shutil.copyfile(out_path, CACHE / (key + '.exr'))
