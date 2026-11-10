"""A VDB shape in Modo's viewport: the box its grid fills and a cloud of points where the grid is thick, so that how big a
volume is (an explosion), and where, shows before it is rendered (a tester's report: the shape was a locator, with no
clue to its size).

All of it is native. The runtime's modo_vdb_grid (as moonlightipr_volumes uses it) reads the grid at a coarse fineness,
POINT_CELLS along its longest edge, once for a file as it stands; the geometry adapter keeps its box and points
(MR_vdb_preview_load, native-modo/vdb_viewport.cpp) and draws them on the viewport's stroke object (MR_vdb_preview_draw).
The reading runs on a thread of its own; the viewport draws what is ready and nothing until it is, so that drawing never
waits on a file. A sequence draws the frame's own file as the timeline moves.
"""
import ctypes
import hashlib
import subprocess
import threading
from pathlib import Path

POINT_CELLS = 40
# A cell is drawn as a point where the grid there is at least this share of its thickest; at most MOST_POINTS of them.
THICK = 0.05
MOST_POINTS = 6000

_ready = {}     # (file, grid) -> the name the adapter keeps it under, or None where it cannot be read
_busy = set()
_lock = threading.Lock()


def _adapter():
    from .evaluated import _adapter as loaded
    bridge = loaded()
    if bridge is None or not hasattr(bridge, 'MR_vdb_preview_draw'):
        return None
    bridge.MR_vdb_preview_load.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_double, ctypes.c_int]
    bridge.MR_vdb_preview_load.restype = ctypes.c_int
    bridge.MR_vdb_preview_draw.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_double]
    bridge.MR_vdb_preview_draw.restype = ctypes.c_int
    return bridge


def ready(path, grid):
    """The name the adapter keeps a VDB file's grid under, where it is ready to draw; None while it is being read, or
    where it cannot be (an adapter older than the kit draws none)."""
    key = (str(path), str(grid or ''))
    with _lock:
        if key in _ready:
            return _ready[key]
        if key in _busy:
            return None
        _busy.add(key)
    threading.Thread(target=_make, args=(key,), daemon=True).start()
    return None


def draw(stroke, name, colour):
    """Draws what the adapter keeps under name on a viewport's stroke object (lx.object.StrokeDraw)."""
    bridge = _adapter()
    if bridge is None or not name:
        return False
    red, green, blue = (float(c) for c in tuple(colour)[:3])
    return bool(bridge.MR_vdb_preview_draw(ctypes.c_void_p(stroke.__peekobj__()), name.encode('utf-8'), red, green, blue))


def _make(key):
    try:
        found = _read(*key)
    except Exception:
        found = None
    with _lock:
        _ready[key] = found
        _busy.discard(key)


def _read(path, grid):
    from . import native
    from .moonlightipr_materials import cache_folder
    bridge = _adapter()
    if bridge is None:
        return None
    source = Path(path)
    stat = source.stat()
    runtime = native.default_runtime()
    digest = hashlib.sha256(repr((str(source.resolve()), stat.st_size, stat.st_mtime_ns, grid, POINT_CELLS, 'viewport-vdb-v1')).encode()).hexdigest()
    target = cache_folder() / (digest + '.mlv')
    if not target.is_file() or not target.stat().st_size:
        tool = Path(runtime) / 'modo_vdb_grid.exe'
        if not tool.is_file():
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = target.with_suffix('.part')
        done = subprocess.run([str(tool), str(source), grid or '', str(POINT_CELLS), str(staged)], env=native.environment(runtime),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), timeout=300)
        if done.returncode or not staged.is_file():
            return None
        staged.replace(target)
    # ctypes lets go of Python's lock for the call: the adapter reads it with Modo going on.
    if not bridge.MR_vdb_preview_load(str(target).encode('utf-8'), digest.encode('utf-8'), THICK, MOST_POINTS):
        return None
    return digest
