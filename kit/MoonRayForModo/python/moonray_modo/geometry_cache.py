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


def fingerprints(time, identities=None, watched=None):
    """Each plain mesh's fingerprint by its identity: the adapter's digest of its evaluated mesh, with its own
    channels'. None where the adapter has no digest (older than this kit). watched: what is held in memory for the
    open scene (session): a mesh no edit was heard of since its fingerprint was taken (Edits), at the same moment, keeps
    it, without its points and polygons read again; the others are read."""
    call = _bridge()
    if call is None:
        return None
    import lx
    import modo
    scene = modo.Scene()
    read = lx.object.Scene(scene).Channels(None, float(time))
    from .incremental import deformed_meshes, own_geometry
    bent = deformed_meshes(scene)
    if bent is None:
        return None
    earlier = {}
    if watched is not None:
        heard = _EDITS.heard(watched)
        # Only where nothing else makes a mesh's geometry (no mesh operations, no kind of item not known to make none)
        # does an edit of the mesh's item say all there is to know.
        if heard is not None and watched.get('time') == float(time) and own_geometry(scene):
            earlier = {identity: value for identity, value in (watched.get('prints') or {}).items() if identity not in heard}
    found = {}
    from time import perf_counter as clock
    spent = [0.0, 0.0]
    kept = 0
    for item in scene.items('mesh', superType=False):
        if identities is not None and item.id not in identities:
            continue
        if item.id in bent:
            continue
        if item.id in earlier:
            found[item.id] = earlier[item.id]
            kept += 1
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
    LAST['digests_kept'] = kept
    if watched is not None and identities is None:
        watched['prints'], watched['time'] = dict(found), float(time)
    return found


# ---- Held in memory while the scene is open ----
# The last reading of each open scene (by scene_watch's key), with its fingerprints, held in RAM: a preview started
# again reads neither the kept reading from disk (812 MB, 1 s on a tester's car) nor, for the meshes no edit was heard
# of (Edits), their points and polygons for their fingerprints (6 s). Let go when the scene closes (scene_watch); never
# written anywhere.
_SESSION = {}


class _Heard:
    """What Modo told of since each scene's fingerprints were taken: the items edited (a channel's value, added,
    removed, put under another, tagged), or that anything may have changed (anything else it tells of). Its listener
    (lxifc.SceneItemListener, one COM object kept, as changes.Changes) is added with the first scene held."""

    def __init__(self):
        self.listener = None

    def start(self):
        if self.listener is not None:
            return
        import lx
        import lxifc
        heard = self

        class Listener(lxifc.SceneItemListener):
            def _item(self, item, *args):
                try:
                    heard.mark(lx.object.Item(item).Ident())
                except (RuntimeError, LookupError, TypeError):
                    heard.mark(None)

            def _any(self, *args):
                heard.mark(None)

            def sil_ChannelValue(self, action, item, index):
                self._item(item)
            sil_ItemAdd = sil_ItemRemove = sil_ItemParent = sil_ItemChild = sil_ItemTag = _item
            sil_ItemPostDelete = sil_SceneClear = sil_ItemAddChannel = sil_ItemRemoveChannel = _any
            sil_ItemLocal = sil_ItemSource = sil_ItemPackage = _any
        made = Listener()
        com = lx.object.Unknown(made)
        try:
            lx.service.Listener().AddListener(com)
        except (RuntimeError, LookupError):
            return
        self.listener = (made, com)

    def mark(self, identity):
        for held in _SESSION.values():
            if identity is None:
                held['everything'] = True
            else:
                held['edited'].add(identity)

    def quiet(self, held):
        """Whether nothing at all was told of since held's fingerprints were taken (and something was listening)."""
        return self.listener is not None and not held.get('everything', True) and not held.get('edited')

    def heard(self, held):
        """The items edited since held's fingerprints were taken, cleared for the next; None where anything may have
        changed, or nothing was listening."""
        if self.listener is None:
            return None
        everything, edited = held.get('everything', True), set(held.get('edited') or ())
        held['everything'], held['edited'] = False, set()
        return None if everything else edited


_EDITS = _Heard()


def session():
    """What is held in memory for the open scene: {'key', 'held' (fingerprints, reading, standing) or None, 'prints',
    'time', 'edited', 'everything'}; made the first time, and let go when the scene closes."""
    import modo
    from . import scene_watch
    scene_key = scene_watch.key(modo.Scene())
    if scene_key is None:
        return None
    if scene_key not in _SESSION:
        scene_watch.watch(_closed)
        _SESSION[scene_key] = {'key': None, 'held': None, 'prints': None, 'time': None, 'edited': set(), 'everything': True}
        _EDITS.start()
    return _SESSION[scene_key]


def _closed(scene_key):
    """A scene closed: what was held in memory for it let go (every scene's where it cannot be told which)."""
    if scene_key is None:
        _SESSION.clear()
    else:
        _SESSION.pop(scene_key, None)


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


# ---- An edited mesh read without the render cache ----
# Where the render cache was read, each plain mesh it gave is read directly as well (the adapter's MR_mesh_matches:
# Modo's own triangulation, its own normal of each point for each polygon, its UV maps), and noted in the reading
# ('_direct') where the two are the very same, triangle for triangle, with the order its UV maps came in. Once such a
# mesh is edited, its surfaces are read directly (direct_prototypes), with no render cache made: on a tester's cars
# 269 of 334 meshes and 70 of 71 were the same; the others (a few polygons cut another way, subdivision surfaces) are
# read from the render cache as before.
DIRECT = '_direct'


class _Segment(__import__('ctypes').Structure):
    import ctypes as _c
    _fields_ = [('material', _c.c_char_p), ('part', _c.c_char_p), ('vertices', _c.c_void_p), ('vertexCount', _c.c_longlong),
                ('corners', _c.c_void_p), ('sizes', _c.c_void_p), ('faceCount', _c.c_longlong), ('normals', _c.c_void_p),
                ('uvCount', _c.c_int), ('uvs', _c.POINTER(_c.c_void_p))]


def _direct_bridge():
    import ctypes
    try:
        from . import evaluated
        bridge = evaluated._load()
        matches, surfaces = bridge.MR_mesh_matches, bridge.MR_mesh_surfaces
    except (AttributeError, ValueError, OSError):
        return None
    matches.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(_Segment), ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    matches.restype = ctypes.c_int
    surfaces.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    surfaces.restype = ctypes.c_char_p
    return matches, surfaces


def _flat(held, typecode):
    """The array behind rows the render cache gave (rows.Rows, rows.Faces), or None where they are not one."""
    from array import array
    data = getattr(held, 'data', None)
    return data if isinstance(data, array) and data.typecode == typecode and data.itemsize == 4 else None


def _mesh(identity, time):
    import lx
    import modo
    item = modo.Scene().item(identity)
    if item.type != 'mesh':
        return None
    return modo.meshgeometry.MeshProvider.meshFromMeshChannel(lx.object.Item(item), 'deformed', float(time))


def verify(data, identities, time):
    """{identity: {'order': UV map names, 'by_part': bool}} for those of the meshes whose surfaces in data read
    directly are the very same (MR_mesh_matches)."""
    import ctypes
    bridge = _direct_bridge()
    if bridge is None:
        return {}
    matches = bridge[0]
    by_item = {}
    for proto in (data.get('prototypes') or {}).values():
        by_item.setdefault(proto.get('item'), []).append(proto)
    found = {}
    for identity in identities:
        protos = by_item.get(identity)
        if not protos:
            continue
        segments, keep = [], []
        for proto in protos:
            for segment in proto.get('segments') or ():
                vertices, faces = _flat(segment.get('vertices'), 'f'), segment.get('faces')
                corners, sizes = _flat(faces, 'i'), getattr(faces, 'counts', None)
                normals = _flat(segment.get('normals'), 'f') if segment.get('normals') else None
                uvs = [_flat(u, 'f') for u in segment.get('uv_sets') or ()]
                if vertices is None or corners is None or sizes is None or getattr(sizes, 'itemsize', 0) != 4 or \
                        (segment.get('normals') and normals is None) or any(u is None for u in uvs):
                    segments = None
                    break
                pointers = (ctypes.c_void_p * max(len(uvs), 1))(*[u.buffer_info()[0] for u in uvs])
                material = str(proto.get('material') or '').encode('utf-8')
                part = str(proto.get('part') or '').encode('utf-8')
                keep += [pointers, material, part]
                segments.append(_Segment(material, part, vertices.buffer_info()[0], len(vertices) // 3, corners.buffer_info()[0],
                                         sizes.buffer_info()[0], len(sizes), normals.buffer_info()[0] if normals is not None else None,
                                         len(uvs), ctypes.cast(pointers, ctypes.POINTER(ctypes.c_void_p))))
            if segments is None:
                break
        if not segments:
            continue
        try:
            mesh = _mesh(identity, time)
        except (LookupError, RuntimeError, TypeError, ValueError, AttributeError):
            continue
        if mesh is None:
            continue
        by_part = any(proto.get('part') for proto in protos)
        uv_count = segments[0].uvCount
        order = (ctypes.c_int * max(uv_count, 1))()
        array_type = _Segment * len(segments)
        if matches(mesh.__peekobj__(), int(by_part), array_type(*segments), len(segments), order) != 1:
            continue
        names = _uv_names(identity)
        found[identity] = {'order': [names[order[u]] for u in range(uv_count)], 'by_part': by_part}
    return found


def _uv_names(identity):
    """The mesh item's UV maps' names by name, as the adapter takes them."""
    import modo
    return sorted(str(m.name) for m in modo.Scene().item(identity).geometry.vmaps.uvMaps)


def direct_prototypes(identity, noted, before, time):
    """The mesh's surfaces read directly, as {prototype key in before: prototype}, in place of those before held for it;
    None where they cannot be (no longer one of a kind that matched, or its materials and parts are others)."""
    import struct
    import tempfile
    from array import array
    from hashlib import blake2b
    from .rows import Rows, Faces
    bridge = _direct_bridge()
    if bridge is None:
        return None
    mine = {key: proto for key, proto in (before.get('prototypes') or {}).items() if proto.get('item') == identity}
    if not mine:
        return None
    try:
        mesh = _mesh(identity, time)
    except (LookupError, RuntimeError, TypeError, ValueError, AttributeError):
        return None
    if mesh is None:
        return None
    handle, path = tempfile.mkstemp(prefix='MoonRay-surfaces-', suffix='.bin')
    os.close(handle)
    try:
        # n-gons refused (2): the render cache cut some otherwise than Modo's triangulation (verify passed them only as they were).
        if bridge[1](mesh.__peekobj__(), path.encode('utf-8'), int(bool(noted.get('by_part', False))) | 2):
            return None
        with open(path, 'rb') as stream:
            held = stream.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if held[:4] != b'MRS1':
        return None
    at = 4

    def number():
        nonlocal at
        value, = struct.unpack_from('<i', held, at)
        at += 4
        return value

    def text():
        nonlocal at
        size = number()
        at += size
        return held[at - size:at].decode('utf-8', errors='replace')

    def floats(count):
        nonlocal at
        values = array('f')
        values.frombytes(held[at:at + 4 * count])
        at += 4 * count
        return values
    names = [text() for _ in range(number())]
    try:
        chosen = [names.index(name) for name in noted.get('order') or ()]
    except ValueError:
        return None
    read = {}
    for _ in range(number()):
        material, part, corners = text(), text(), number()
        positions, normals = floats(3 * corners), floats(3 * corners)
        uvs = [floats(2 * corners) for _ in names]
        read[(material, part)] = (corners, positions, normals, [uvs[u] for u in chosen])
    by_key = {(proto.get('material') or '', proto.get('part') or ''): key for key, proto in mine.items()}
    if set(by_key) != set(read):
        return None

    def rows(values, width, kind):
        return Rows(values, width, 'direct:%s:%d:%s' % (kind, width, blake2b(memoryview(values), digest_size=16).hexdigest()))
    made = {}
    for key, (corners, positions, normals, uvs) in read.items():
        old = mine[by_key[key]]
        indices, sizes = array('i', range(corners)), array('i', [3]) * (corners // 3)
        mark = blake2b(memoryview(indices), digest_size=16)
        mark.update(memoryview(sizes))
        segment = {'face_varying': True, 'joined': True, 'vertices': rows(positions, 3, 'p'),
                   'faces': Faces(indices, sizes, 'direct-faces:' + mark.hexdigest()), 'radii': [], 'velocities': [],
                   'normals': rows(normals, 3, 'n'), 'uv_sets': [rows(u, 2, 'uv') for u in uvs]}
        made[by_key[key]] = dict(old, segments=[segment])
    return made


def displaces(scene=None):
    """Whether any Shader Tree layer displaces (Modo's render cache then displaces meshes, read displaced)."""
    import lx
    import modo
    scene = scene or modo.Scene()
    layer = lx.service.Scene().ItemTypeLookup('textureLayer')
    for item in scene.iterItems():
        try:
            if item.TestType(layer) and str(item.channel('effect').get() or '').lower().startswith('displace'):
                return True
        except (AttributeError, LookupError, RuntimeError, TypeError):
            continue
    return False


def bypass(only, before, time, displaced):
    """before with the surfaces of those of only that can be read directly so read (direct_prototypes), and the
    items left for the render cache; (None, only) where none could be."""
    noted = before.get(DIRECT) or {}
    if not noted or (displaced and displaces()):
        return None, set(only)
    prototypes = dict(before.get('prototypes') or {})
    left = set()
    for identity in only:
        made = direct_prototypes(identity, noted[identity], before, time) if identity in noted else None
        if made is None:
            left.add(identity)
            continue
        prototypes.update(made)
    if left == set(only):
        return None, left
    LAST['read_directly'] = len(set(only) - left)
    return dict(before, prototypes=prototypes, surfaces=[dict(s) for s in before.get('surfaces') or ()]), left
