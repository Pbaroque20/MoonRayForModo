"""Where the kit keeps what it makes once and uses again (converted textures and environments, MoonLightIPR's images,
fur, graph bakes, procedurals, diagnostics, prepared meshes), and where it tells its renderers to keep theirs
(MOONRAY_MODO_CACHE, in native.environment): the Cache folder in the preview's preferences, or
%LOCALAPPDATA%\\MoonRayForModo where none is chosen. What a folder held before is left in it; another fills as things
are made again. Compiled GPU programs stay where they are, so as not to be compiled again.

The Scene cache, also in the preferences (on unless switched off), keeps a scene's prepared meshes there too (kept): a
mesh simplified and packed for MoonLightIPR, or simplified for MoonRay's realtime, is taken from the folder the next time
it is asked for, the same mesh in the same cut, however the scene was opened."""
import os
import pickle
import tempfile
import threading
import uuid
from pathlib import Path

_HELD = {}
_LOCK = threading.Lock()
# What the prepared meshes may come to, the oldest let go beyond it.
KEPT_BYTES = 10 * 1024 ** 3
# How many are written before the folder is looked over for that.
_WRITTEN = [0]
# How many were asked for and not kept yet (missed): each is made, and kept, now.
_MISSED = [0]
# The status a preparation says while the Scene cache is on (panel).
CACHING = 'Caching scene...'


def _setting(key, default, unread=None):
    """A preference as stored; unread (default where None) where the preferences cannot be read, outside Modo."""
    try:
        from PySide2 import QtCore
        from . import native
        value = QtCore.QSettings('MoonRayForModo', native.settings_name()).value(key, default)
    except Exception:
        return default if unread is None else unread
    return default if value is None else value


def root():
    """The folder, read from the preferences once and again after they are saved (forget)."""
    if 'root' not in _HELD:
        chosen = str(_setting('cache_folder', '') or '').strip()
        _HELD['root'] = Path(chosen) if chosen else Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'MoonRayForModo'
    return _HELD['root']


def scene_cache():
    """Whether prepared meshes are kept in the folder (the Scene cache in the preferences; on where not set, off where
    the preferences cannot be read, as outside Modo)."""
    if 'scene' not in _HELD:
        _HELD['scene'] = str(_setting('scene_cache', 'true', 'false')).lower() in ('true', '1')
    return _HELD['scene']


def missed():
    """How many prepared meshes were asked for and not kept yet, since the kit was loaded: one more than before a
    scene was made ready says it is being cached (moonlightipr_session)."""
    return _MISSED[0]


def forget():
    """The preferences saved: the folder and the Scene cache are read again."""
    _HELD.clear()


def _file(kind, signature):
    import hashlib
    name = hashlib.blake2b(repr(signature).encode('utf-8'), digest_size=16).hexdigest()
    return root() / kind / (name + '.bin')


def kept(kind, signature):
    """A prepared mesh kept under kind (a folder of its own) for this signature (a tuple of its contents' digests and
    how it is cut), or None: not kept, the Scene cache off, or unreadable."""
    if not scene_cache():
        return None
    path = _file(kind, signature)
    try:
        with path.open('rb') as stream:
            held = pickle.load(stream)
    except (OSError, EOFError, pickle.UnpicklingError, AttributeError, ValueError):
        with _LOCK:
            _MISSED[0] += 1
        return None
    if not isinstance(held, tuple) or len(held) != 2 or held[0] != repr(signature):
        return None
    try:
        os.utime(path)  # the newest used is the last let go
    except OSError:
        pass
    return held[1]


def keep(kind, signature, value):
    """Keep a prepared mesh for the next time (kept). Written whole or not at all; nothing said where it cannot be."""
    if not scene_cache():
        return
    path = _file(kind, signature)
    staged = path.with_name(path.name + '.' + uuid.uuid4().hex[:8] + '.tmp')
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with staged.open('wb') as stream:
            pickle.dump((repr(signature), value), stream, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(staged, path)
    except (OSError, pickle.PicklingError, TypeError, AttributeError):
        try:
            staged.unlink()
        except OSError:
            pass
        return
    with _LOCK:
        _WRITTEN[0] += 1
        due = _WRITTEN[0] % 32 == 1
    if due:
        _trim(path.parent)


def _trim(folder):
    """The folder brought back under KEPT_BYTES, the least lately used let go first."""
    try:
        files = sorted((entry.stat().st_mtime, entry.stat().st_size, entry) for entry in folder.glob('*.bin'))
    except OSError:
        return
    total = sum(size for _, size, _ in files)
    for _, size, entry in files:
        if total <= KEPT_BYTES:
            break
        try:
            entry.unlink()
            total -= size
        except OSError:
            pass
