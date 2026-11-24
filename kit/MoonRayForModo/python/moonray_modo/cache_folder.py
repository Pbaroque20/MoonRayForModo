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
# How many were asked for and found kept (found): each is read back from the folder.
_FOUND = [0]
# What a preparation says (moonlightipr_session, panel): while it makes and keeps what was not kept yet, and while it
# reads back what was, the Scene cache's own work.
CACHING = 'Caching scene...'
LOADING = 'Loading scene from cache...'


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


# What the kit makes in the folder, each a folder of its own: what Clear Cache empties (clear). Not Diagnostics (logs), and
# not MoonLightIPR's compiled programs (OptixCache), which take minutes to make again and do not go stale.
CLEARED = ('Scenes', 'Geometry', 'Alpha', 'MoonLightIPR', 'Simplified', 'Textures', 'Environments', 'Procedurals', 'GraphBakes', 'Fur',
           'Ocean', 'Rhea')
# XPU2 RT (Rhea)'s radiance cache (rhea/rhea_cache.h): its files (<scene key>.rhea) and the stamp the running XPU2 reads to
# drop what it holds (rhea_flush).
RHEA = 'Rhea'
RHEA_STAMP = 'flush.stamp'


def clear():
    """Empty what the kit keeps in the folder (CLEARED), and what this Modo holds of it in memory: everything is made
    anew as it is next needed. Only those folders: the cache folder may be one the user chose, with things of their
    own in it. A file a render has open is left. Returns (files removed, bytes freed, files left)."""
    removed = freed = left = 0
    base = root()
    rhea_kept = (base / RHEA).is_dir()
    for kind in CLEARED:
        folder = base / kind
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            try:
                if path.is_dir():
                    path.rmdir()
                    continue
                size = path.stat().st_size
                path.unlink()
                removed, freed = removed + 1, freed + size
            except OSError:
                left += 1
        try:
            folder.rmdir()
        except OSError:
            pass
    # Prepared meshes this Modo still holds would otherwise be used without the folder.
    try:
        from . import moonlightipr_scene
        moonlightipr_scene._packed.clear()
    except Exception:
        pass
    # And the ocean tiles it has seen on disk (ocean.make).
    try:
        from . import ocean
        ocean.forget_seen()
    except Exception:
        pass
    # And Rhea's radiance cache a running XPU2 holds: dropped, not written again (its files went with the folder). Where
    # there was a Rhea folder (an XPU2 may have kept one there): the stamp is all that is left in it.
    if rhea_kept:
        rhea_flush('clear')
    return removed, freed, left


def rhea_folder():
    """Where XPU2 RT (Rhea) keeps its radiance cache on disk, a file a scene, and its flush stamp (XPU2_SESSION_RHEA_CACHE_FOLDER)."""
    return root() / RHEA


def rhea_flush(kind='memory'):
    """Tell a running XPU2 to drop Rhea's radiance cache (rhea/rhea_cache.h reads the stamp as each frame starts and as it
    quits): 'memory' drops what it holds (on disk, written first), 'clear' drops it without writing. True where told."""
    import time
    folder = rhea_folder()
    staged = folder / (RHEA_STAMP + '.' + uuid.uuid4().hex[:8] + '.tmp')
    try:
        folder.mkdir(parents=True, exist_ok=True)
        staged.write_text('%d %s\n' % (time.time_ns(), 'clear' if kind == 'clear' else 'memory'), encoding='ascii')
        os.replace(staged, folder / RHEA_STAMP)
    except OSError:
        try:
            staged.unlink()
        except OSError:
            pass
        return False
    return True


def rhea_files():
    """Rhea's radiance cache files and their size in bytes: (count, bytes)."""
    count = size = 0
    try:
        for entry in rhea_folder().glob('*.rhea'):
            try:
                size += entry.stat().st_size
                count += 1
            except OSError:
                pass
    except OSError:
        pass
    return count, size


def rhea_clear():
    """Clear Radiance Cache: Rhea's files removed and a running XPU2 told to drop what it holds without writing it again.
    Returns (files removed, bytes freed, files left)."""
    removed = freed = left = 0
    rhea_flush('clear')
    for entry in sorted(rhea_folder().glob('*.rhea*')) if rhea_folder().is_dir() else []:
        try:
            size = entry.stat().st_size
            entry.unlink()
            removed, freed = removed + 1, freed + size
        except OSError:
            left += 1
    return removed, freed, left


def found():
    """How many prepared meshes were asked for and found kept, since the kit was loaded: more than before, and none
    missed, says a scene is being read back from the cache (moonlightipr_session)."""
    return _FOUND[0]


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
    with _LOCK:
        _FOUND[0] += 1
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
