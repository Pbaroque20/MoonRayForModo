"""Modo's evaluated geometry kept between Modo's sessions, mesh by mesh (the Scene cache, cache_folder).

A whole reading of Modo's render cache (evaluated.capture) is most of a cold start's wait: on a tester's car, 45 s of
46 after one mesh had been moved a millimetre, as an unsaved scene is never taken from the scene-read cache
(scene_reading). Yet every one of its 345 meshes made its surfaces from itself alone. So the last reading is kept on
disk with a fingerprint of each mesh it read (its points, polygons, tags and maps, by the geometry adapter's
MR_mesh_digest, and its own channels), and a cold start reads again only the surfaces of meshes whose fingerprint
changed, or that are not plain meshes (instanced from other scenes, generated, deformed, streamed); the others are
taken from the kept reading (evaluated.capture's only/before, the adapter's MR_geometry_snapshot_some), with each
surface's place and visibility listed anew. Where nothing changed (no mesh's fingerprint, no surface's item's place or
channels, nor the Shader Tree: standing), Modo's render cache is not made at all, and the kept surfaces are taken
whole: making it was a cold start's 8 s on a tester's car even with every mesh kept.

What else makes surfaces is in the key the reading is kept under: the scene file's path, whether Modo
displaced them (and then every Shader Tree layer's channels and the images they name, as Modo's displacement reads
them), the render item's channels, Modo's version, the adapter and the kit's reading code. Not the moment: a plain
mesh's fingerprint is taken at the moment read, and what is not a plain mesh is read again every time, so one kept
reading serves every frame of an animation; it is written again only where a plain mesh changed."""
import hashlib
import os
import pickle
import threading

# The form of what is kept: one kept in another is not taken.
FORM = 2
KIND = 'Geometry'
# What a cold start did, for probes: 'kept' readings taken, meshes read again, why one was not taken.
LAST = {}


def _bridge():
    try:
        from . import evaluated
        bridge = evaluated._load()
        call = bridge.MR_mesh_digest
    except (AttributeError, ValueError, OSError):
        return None
    import ctypes
    call.argtypes = [ctypes.c_void_p]
    call.restype = ctypes.c_char_p
    return call


def _channels(digest, item, read):
    """The item's own channels' values into digest: numbers and text, not objects (its mesh, its matrices)."""
    import lx
    integer, number, text = lx.symbol.i_TYPE_INTEGER, lx.symbol.i_TYPE_FLOAT, lx.symbol.i_TYPE_STRING
    for index in range(item.ChannelCount()):
        try:
            kind = item.ChannelType(index)
            if kind == integer:
                value = read.Integer(item, index)
            elif kind == number:
                value = round(read.Double(item, index), 9)
            elif kind == text:
                value = read.String(item, index)
            else:
                continue
        except (LookupError, RuntimeError, TypeError, ValueError):
            continue
        digest.update(('%d=%r;' % (index, value)).encode('utf-8', errors='replace'))


def fingerprints(time, identities=None):
    """Each plain mesh's fingerprint by its identity: the adapter's digest of its evaluated mesh, with its own
    channels'. None where the adapter has no digest (older than this kit)."""
    call = _bridge()
    if call is None:
        return None
    import lx
    import modo
    scene = modo.Scene()
    read = lx.object.Scene(scene).Channels(None, float(time))
    from .incremental import deformed_meshes
    bent = deformed_meshes(scene)
    if bent is None:
        return None
    found = {}
    from time import perf_counter as clock
    spent = [0.0, 0.0]
    for item in scene.items('mesh', superType=False):
        if identities is not None and item.id not in identities:
            continue
        if item.id in bent:
            continue
        raw = lx.object.Item(item)
        try:
            # The evaluated mesh channel holds a mesh filter, which makes the mesh (as Modo's MeshProvider does).
            began = clock()
            mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(raw, 'deformed', float(time))
            made = clock()
            held = call(mesh.__peekobj__())
            spent[0] += made - began
            spent[1] += clock() - made
        except (LookupError, RuntimeError, TypeError, ValueError, AttributeError):
            continue
        if not held or held.startswith(b'!'):
            continue
        digest = hashlib.blake2b(held, digest_size=16)
        _channels(digest, raw, read)
        found[item.id] = digest.hexdigest()
    LAST['meshes_made_seconds'], LAST['digests_seconds'] = round(spent[0], 3), round(spent[1], 3)
    return found


def _settings(time, displaced):
    """What, beside the meshes, makes the surfaces Modo's render cache gives: as a digest."""
    import lx
    import modo
    scene = modo.Scene()
    read = lx.object.Scene(scene).Channels(None, float(time))
    digest = hashlib.blake2b(digest_size=16)
    digest.update(b'displaced' if displaced else b'plain')
    _channels(digest, lx.object.Item(scene.renderItem), read)
    if displaced:
        # Modo displaces by the Shader Tree's textures: every layer's channels, and the images they name as they stand.
        layer = lx.service.Scene().ItemTypeLookup('textureLayer')
        for item in scene.iterItems():
            if not item.TestType(layer) and item.type != 'videoStill':
                continue
            digest.update(item.id.encode('utf-8'))
            _channels(digest, lx.object.Item(item), read)
            if item.type == 'videoStill':
                try:
                    path = str(item.channel('filename').get() or '')
                    stat = os.stat(path)
                    digest.update(('%s:%d:%d' % (path, stat.st_size, stat.st_mtime_ns)).encode('utf-8', errors='replace'))
                except (OSError, AttributeError, LookupError, RuntimeError, TypeError):
                    digest.update(b'-')
    return digest.hexdigest()


def key(time, displaced):
    """What the scene's evaluated geometry is kept under, or None where it is not to be kept: the Scene cache off, no
    scene file, or something Modo cannot be asked."""
    from . import cache_folder
    if not cache_folder.scene_cache():
        return None
    try:
        import lx
        path = lx.eval1('query sceneservice scene.file ? current')
        if not path:
            return None
        platform = lx.service.Platform()
        from .scene_reading import reading_code
        return ('geometry', FORM, os.path.normcase(os.path.abspath(path)), bool(displaced),
                (platform.AppVersion(), platform.AppBuild()), _adapter_mark(), reading_code(), _settings(time, displaced))
    except Exception:
        return None


_ADAPTER = []


def _adapter_mark():
    if not _ADAPTER:
        from . import evaluated
        from pathlib import Path
        path = Path(evaluated.__file__).resolve().parents[2] / 'bin/MoonRayGeometry.lx'
        try:
            stat = path.stat()
            _ADAPTER.append('%d:%d' % (stat.st_size, stat.st_mtime_ns))
        except OSError:
            _ADAPTER.append('-')
    return _ADAPTER[0]


def standing(data, time):
    """Where the kept surfaces' items stand and how they are shaded, as digests: by each surface's item, its own and
    its parents' channels and its world matrix a frame before, at and after time; and the Shader Tree (every layer's
    place and channels) with the render camera's. None where a surface's item is not a mesh or a mesh instance (a
    replicator's copies, a proxy's): its surfaces come only from Modo's render cache."""
    import lx
    import modo
    scene = modo.Scene()
    read = lx.object.Scene(scene).Channels(None, float(time))
    step = 1.0 / max(float(scene.fps or 24.0), 1.0)
    from .host import world_matrix
    places = {}
    for identity in sorted({surface.get('source_item') for surface in data.get('surfaces') or ()}):
        try:
            item = scene.item(identity)
        except (LookupError, TypeError, ValueError):
            return None
        if item.type not in ('mesh', 'meshInst'):
            return None
        digest = hashlib.blake2b(digest_size=16)
        for moment in (time - step, time, time + step):
            digest.update(repr([round(v, 9) for v in world_matrix(item, moment)]).encode('utf-8'))
        held = item
        while held is not None:
            digest.update(held.id.encode('utf-8'))
            _channels(digest, lx.object.Item(held), read)
            held = held.parent
        places[identity] = digest.hexdigest()
    shading = hashlib.blake2b(digest_size=16)
    layer = lx.service.Scene().ItemTypeLookup('textureLayer')
    for item in scene.iterItems():
        if not item.TestType(layer):
            continue
        parent = item.parent
        shading.update(('%s<%s:%s;' % (item.id, parent.id if parent else '', item.parentIndex)).encode('utf-8'))
        _channels(shading, lx.object.Item(item), read)
    camera = scene.renderCamera
    if camera is not None:
        shading.update(camera.id.encode('utf-8'))
        _channels(shading, lx.object.Item(camera), read)
    return {'places': places, 'shading': shading.hexdigest()}


def load(held_key):
    """The reading kept under held_key, the fingerprints it was read with and where its items stood (standing), or
    None."""
    if held_key is None:
        return None
    from . import cache_folder
    from . import evaluated  # noqa: F401  (its hook knows the rows a reading holds)
    held = cache_folder.kept(KIND, held_key)
    if not isinstance(held, tuple) or len(held) != 3:
        return None
    try:
        prints, frozen, stood = held
        data = pickle.loads(frozen)
    except Exception:
        return None
    if not isinstance(prints, dict) or not isinstance(data, dict) or not data.get('prototypes'):
        return None
    return prints, data, stood


def changed(prints_before, prints_now, data):
    """The items whose surfaces are to be read again: every owner of a kept surface that is not a plain mesh with
    the fingerprint it had, and every plain mesh whose fingerprint is new or other."""
    owners = {held.get('item') for held in data.get('prototypes', {}).values()}
    again = {owner for owner in owners if not owner or prints_now.get(owner) is None or prints_now[owner] != prints_before.get(owner)}
    again |= {identity for identity, value in prints_now.items() if prints_before.get(identity) != value}
    return again


def keep(held_key, prints, data, stood):
    """Keep a reading just made, with the fingerprints it was read with and where its items stood: frozen now, before
    anything is changed in it, and written on a thread of its own."""
    if held_key is None or prints is None:
        return
    try:
        frozen = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        LAST['not_kept'] = '%s: %s' % (type(exc).__name__, exc)
        return
    from . import cache_folder
    threading.Thread(target=cache_folder.keep, args=(KIND, held_key, (prints, frozen, stood)), daemon=True).start()
