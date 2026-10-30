"""The scene as Modo's thread last read it whole, kept by the Scene cache for the next cold start (cache_folder): a
car's reading held Modo for most of a minute, to give the same lists as last time when nothing had changed.

A reading is kept under a hash of what it was made from: the scene file's content and path, the frame, whether
Modo's evaluated geometry was read, Modo's version and the kit's code that makes a reading (reading_code). It is taken again only while the open
scene has no unsaved changes (Modo's scene.changed), and only where the files the scene names (its images among them)
stand as they did when it was read (assets.signature); otherwise the scene is read from Modo as before."""
import hashlib
import os
import pickle
import threading

# The form of a kept reading: one kept in another is not taken.
FORM = 1


def _file_digest(path):
    digest = hashlib.blake2b(digest_size=16)
    with open(path, 'rb') as stream:
        while True:
            block = stream.read(8 * 1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def key(evaluated):
    """What a reading of the open scene is kept under, or None where none may be kept or taken: the Scene cache off,
    no file, or unsaved changes."""
    from . import cache_folder
    if not cache_folder.scene_cache():
        return None
    try:
        import lx
        if int(lx.eval1('query sceneservice scene.changed ? current')):
            return None
        path = lx.eval1('query sceneservice scene.file ? current')
        if not path or not os.path.isfile(path):
            return None
        platform = lx.service.Platform()
        version = (platform.AppVersion(), platform.AppBuild())
        moment = float(lx.service.Selection().GetTime())
        return ('scene', FORM, os.path.normcase(os.path.abspath(path)), _file_digest(path), moment, bool(evaluated), version,
                reading_code())
    except Exception:
        return None


_READING_CODE = []


def reading_code():
    """What makes a reading, as a digest: the kit's modules host.py reaches through its imports (host.snapshot and
    what it calls), as their files hold them. Kept by it in place of the kit's installation, which every install
    changed: a kit installed again, or one whose reading is the same (the preview window, the engines, the preferences
    changed), finds the readings it kept; one whose reading changed reads anew."""
    if _READING_CODE:
        return _READING_CODE[0]
    import re
    here = os.path.dirname(os.path.abspath(__file__))
    pattern = re.compile(r'from \.(\w+) import|from \. import ([\w, ]+)')
    seen, todo = set(), ['host']
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        path = os.path.join(here, name + '.py')
        if not os.path.isfile(path):
            continue
        seen.add(name)
        with open(path, 'r', encoding='utf-8', errors='replace') as stream:
            text = stream.read()
        for one, many in pattern.findall(text):
            todo.extend([one] if one else [part.strip() for part in many.split(',') if part.strip()])
    digest = hashlib.blake2b(digest_size=16)
    for name in sorted(seen):
        with open(os.path.join(here, name + '.py'), 'rb') as stream:
            digest.update(name.encode('utf-8') + b'\0' + stream.read())
    _READING_CODE.append(digest.hexdigest())
    return _READING_CODE[0]


def files(scene):
    """How the files a reading names stand on disk (assets.signature), or None where that cannot be told."""
    try:
        from .assets import signature
        return signature(scene)
    except Exception:
        return None


def held(held_key):
    """Whether a reading is kept under held_key (said before it is taken back; load still checks it)."""
    if held_key is None:
        return False
    from . import cache_folder
    try:
        return cache_folder.scene_cache() and cache_folder._file('Scenes', held_key).is_file()
    except OSError:
        return False


def load(held_key):
    """The reading kept under held_key, where the files it names stand as they did; else None."""
    if held_key is None:
        return None
    from . import cache_folder
    held = cache_folder.kept('Scenes', held_key)
    if not isinstance(held, tuple) or len(held) != 2:
        return None
    try:
        # The rows Modo handed over are known to the scene's digest by evaluated's hook (scene_digest.FLAT), set as it
        # loads: a reading taken from here never read Modo, and hashing its rows failed ("unmarshallable object").
        from . import evaluated  # noqa: F401
        scene = pickle.loads(held[0])
    except Exception:
        return None
    return scene if held[1] is not None and files(scene) == held[1] else None


def freeze(scene):
    """A reading just made, as bytes, before anything is changed in it; None where it cannot be."""
    try:
        return pickle.dumps(scene, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        return None


def keep(held_key, frozen, scene):
    """Keep a reading (frozen) under held_key for the next cold start, written on a thread of its own."""
    if held_key is None or frozen is None:
        return
    standing = files(scene)
    if standing is None:
        return
    from . import cache_folder
    threading.Thread(target=cache_folder.keep, args=('Scenes', held_key, (frozen, standing)), daemon=True).start()
