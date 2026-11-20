"""MoonRay > Links: the scene's meshes listed as Adobe Illustrator's Links panel lists placed images, each with its
file and whether it is linked or embedded.

A mesh is Embedded (a mesh of the scene), Linked (a Scene Proxy: Modo's proxy item, the mesh kept in an .lxo of its
own and drawn from there, which keeps the scene light) or Editing (a linked mesh brought back into the scene to be
edited, still tied to its file). Saving the scene writes every Editing mesh that changed to its file (watch_saves),
and the panel's Update File does it on its own; an Editing mesh stays editable until Done Editing makes it a proxy
again.

Modo's own commands do the work: proxy.convert writes a mesh to a file and puts a proxy in its place (Link, Done
Editing), proxy.restore brings a proxy back as a mesh from its file as it is on disk (Edit in Scene, Embed),
proxy.sceneFile points a proxy at another file (Relink). Both convert and restore work on the selection, whatever
their item argument says, and restore brings the file's materials into the Shader Tree again, under an 'imported
shaders' mask; that copy is taken out where the scene's own masks already shade every material of the mesh. A file
proxy.convert writes is the whole scene less its other surfaces (its materials, locators, camera and lights).

A link file holds the mesh's shape at the origin, and the proxy stands where the mesh stood: as proxy.convert leaves
them (the file's mesh keeping its place too), Modo's renderer and the render cache drew the mesh at its own origin, so
_convert puts the file's mesh at the origin and has the proxy read it again (settle).

An Editing mesh is written to its file without touching the scene (write_geometry): its polygons copied, the file
opened, its mesh's polygons replaced by them, saved and closed; where it stands goes to the proxy at Done Editing.
Where that cannot be done (no file yet, hidden polygons), it goes through proxy.convert and proxy.restore instead,
which gives the mesh a new item.

Each item's link is a tag of JSON (TAG): its file, the file's size and time when last written or read, the mesh's
fingerprint then, and the stand-in shape a proxy is drawn with (none yet). Modo copies an item's tags across
proxy.convert and proxy.restore, so the record follows the item through its states; a proxy made outside the panel
has none until the panel first sees it."""
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

TAG = 'MRLK'
LINKED, EDITING, EMBEDDED = 'linked', 'editing', 'embedded'
STATE_TEXT = {LINKED: 'Linked', EDITING: 'Editing', EMBEDDED: 'Embedded'}
OK, EDITED, CHANGED, BOTH, MISSING, NONE = 'ok', 'edited', 'changed', 'both', 'missing', ''
STATUS_TEXT = {OK: 'Up to date', EDITED: 'Edits not yet written', CHANGED: 'File changed on disk',
               BOTH: 'Edits not yet written; file changed on disk', MISSING: 'File missing', NONE: ''}
# Where a status needs the file written (Update File, a save).
NEEDS_WRITE = (EDITED, BOTH, MISSING)
# What a file name may not hold on Windows.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


# ---- The record and the status: no Modo needed. ----------------------------------------------------------------

def read_record(text):
    """A link record from a tag's text: a dict with its 'file'; None where there is none or it is not one."""
    if not text:
        return None
    try:
        held = json.loads(text)
    except (TypeError, ValueError):
        return None
    if not isinstance(held, dict) or not isinstance(held.get('file'), str) or not held['file']:
        return None
    return held


def record_text(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'))


def stamp(path):
    """A file's (size, modification time in ns) as it is now; None where it is not there."""
    try:
        held = Path(path).stat()
    except (OSError, TypeError, ValueError):
        return None
    if not Path(path).is_file():
        return None
    return [held.st_size, held.st_mtime_ns]


def status(state, record, now, mark=None):
    """The status of an item: state (LINKED, EDITING, EMBEDDED), its record (or None), its file's stamp now (or None
    where it is missing) and, for a mesh being edited, its fingerprint now. A file changed on disk is one whose stamp
    is not the one recorded when it was last written or read; a mesh edited is one whose fingerprint is not the one
    recorded then. A record without a stamp or fingerprint (a proxy made outside the panel) says nothing changed."""
    if state == EMBEDDED:
        return NONE
    if now is None:
        return MISSING
    held = (record or {}).get('stamp')
    changed = bool(held) and list(held) != list(now)
    if state == LINKED:
        return CHANGED if changed else OK
    printed = (record or {}).get('print')
    edited = printed is not None and mark is not None and mark != printed
    if edited and changed:
        return BOTH
    return EDITED if edited else CHANGED if changed else OK


def default_folder(scene_file):
    """Where a scene's linked meshes are written unless chosen: a folder beside it, '<scene>_links'; None for a scene
    not saved yet."""
    if not scene_file:
        return None
    held = Path(scene_file)
    return held.parent / (held.stem + '_links')


def file_name(folder, name, taken=()):
    """The file a mesh named name is linked to in folder: its name made safe for a file, '.lxo', with ' (2)' and so on
    where that file is there already or taken (paths, compared without case)."""
    stem = _UNSAFE.sub('_', str(name or '')).strip(' .') or 'Mesh'
    taken = {str(p).lower() for p in taken}
    folder = Path(folder)
    candidate = folder / (stem + '.lxo')
    number = 2
    while candidate.exists() or str(candidate).lower() in taken:
        candidate = folder / ('%s (%d).lxo' % (stem, number))
        number += 1
    return candidate


def spelling(path, count):
    """A link file's path as a proxy is pointed at it: as it is (count 0), else with count '.' folders before its name,
    the same file to Windows (spelled)."""
    path = Path(path)
    return str(path) if not count else str(path.parent) + (os.sep + '.') * count + os.sep + path.name


def spelled(path, loaded):
    """The first spelling of path (spelling) Modo has not loaded in this session (loaded: the spellings it has, compared
    without case). Modo keeps a proxy's file as first loaded, by the path as written, for the whole session: pointed at
    the same path again, unloaded (proxy.unload), its scene closed and opened again, a proxy kept showing the file as it
    was before it was written again (tools/probe_cl_links_reload.py); pointed at another spelling of it, it read it anew."""
    held = {os.path.normcase(str(p)) for p in loaded}
    count = 0
    while os.path.normcase(spelling(path, count)) in held:
        count += 1
    return spelling(path, count)


def same_file(a, b):
    try:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))
    except (TypeError, ValueError):
        return False


# ---- Modo. -------------------------------------------------------------------------------------------------------

def _modo():
    import lx
    import modo
    return lx, modo


def read_tag(item):
    try:
        return read_record(item.readTag(TAG))
    except (LookupError, RuntimeError, AttributeError, TypeError):
        return None


def write_tag(item, record):
    """The record written to the item's tag, its file as the file's own path, however a proxy spells it (spelled)."""
    if record and record.get('file'):
        record = dict(record, file=os.path.normpath(record['file']))
    item.setTag(TAG, record_text(record) if record else None)


def proxy_file(proxy):
    try:
        return str(proxy.channel('scene').get() or '')
    except (AttributeError, LookupError, RuntimeError):
        return ''


def prints(items, time=None):
    """Each mesh's fingerprint by its id: its geometry (the adapter's digest, geometry_cache.fingerprints, else its
    points, polygons and material tags read in Python). Not its place: a link file holds the shape alone, at the origin,
    and where it stands is the proxy's (_convert), so a mesh moved while edited has nothing new for its file."""
    import hashlib
    lx, modo = _modo()
    if time is None:
        time = lx.service.Selection().GetTime()
    items = list(items)
    found = {}
    try:
        from .geometry_cache import fingerprints
        held = fingerprints(time, {item.id for item in items}) or {}
    except Exception:
        held = {}
    for item in items:
        digest = hashlib.blake2b(digest_size=16)
        geometry = held.get(item.id)
        if geometry is None:
            geometry = _python_print(item)
        digest.update(str(geometry).encode('utf-8'))
        found[item.id] = digest.hexdigest()
    return found


def _python_print(item):
    """A mesh's points, polygons and material tags hashed in Python, where the adapter has no digest."""
    import hashlib
    import struct
    digest = hashlib.blake2b(digest_size=16)
    try:
        geometry = item.geometry
        for vertex in geometry.vertices:
            digest.update(struct.pack('<3d', *vertex.position))
        for polygon in geometry.polygons:
            digest.update(struct.pack('<%dI' % len(polygon.vertices), *[v.index for v in polygon.vertices]))
            digest.update((polygon.materialTag or '').encode('utf-8'))
    except Exception as exc:
        digest.update(repr(exc).encode('utf-8'))
    return digest.hexdigest()


def rows(embedded=True, time=None):
    """The panel's rows, in the scene open now: every proxy (Linked), every mesh tied to a file (Editing), and, where
    embedded, every other mesh with polygons (Embedded). Each a dict: id, name, state, file, record, status."""
    lx, modo = _modo()
    scene = modo.Scene()
    found, editing = [], []
    for item in scene.items('proxy'):
        record = read_tag(item)
        # The file itself, however the proxy spells its path (spelled).
        path = os.path.normpath(proxy_file(item)) if proxy_file(item) else ''
        if record is None or not same_file(record['file'], path):
            # A proxy made outside the panel, or relinked in Modo: its record from now on.
            record = dict(record or {}, file=path, stamp=stamp(path))
            try:
                write_tag(item, record)
            except Exception:
                pass
        now = stamp(path)
        found.append({'id': item.id, 'name': item.name, 'state': LINKED, 'file': record['file'], 'record': record,
                      'status': status(LINKED, record, now), 'standin': record.get('standin')})
    for item in scene.items('mesh'):
        record = read_tag(item)
        if record is not None:
            editing.append(item)
            found.append({'id': item.id, 'name': item.name, 'state': EDITING, 'file': record['file'], 'record': record,
                          'standin': record.get('standin')})
        elif embedded:
            try:
                polygons = item.geometry.numPolygons
            except Exception:
                polygons = 0
            if polygons:
                found.append({'id': item.id, 'name': item.name, 'state': EMBEDDED, 'file': '', 'record': None, 'status': NONE,
                              'standin': None})
    marks = prints(editing, time) if editing else {}
    for row in found:
        if row['state'] == EDITING:
            row['print'] = marks.get(row['id'])
            row['status'] = status(EDITING, row['record'], stamp(row['file']), row['print'])
    order = {LINKED: 1, EDITING: 0, EMBEDDED: 2}
    found.sort(key=lambda row: (order[row['state']], row['name'].lower()))
    return found


def _item(ident):
    lx, modo = _modo()
    try:
        return modo.Scene().item(ident)
    except LookupError:
        return None


def _mode():
    lx, modo = _modo()
    for mode in ('vertex', 'edge', 'polygon', 'item'):
        try:
            if lx.eval1('select.typeFrom %s;vertex;edge;polygon;item ?' % mode):
                return mode
        except Exception:
            continue
    return 'item'


@contextmanager
def kept_selection(renamed):
    """The items selected and the selection mode put back afterwards; an item replaced on the way (a mesh become a
    proxy, a proxy a mesh) by the one that took its place, as renamed (old id: new id) says."""
    lx, modo = _modo()
    held = [item.id for item in modo.Scene().selected]
    mode = _mode()
    try:
        yield
    finally:
        try:
            lx.eval('select.drop item')
            for ident in held:
                ident = renamed.get(ident, ident)
                if _item(ident) is not None:
                    lx.eval('select.item {%s} add' % ident)
            lx.eval('select.type %s' % mode)
        except Exception:
            pass


def _only(ident):
    lx, modo = _modo()
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % ident)


def _convert(mesh, path, standin=None):
    """proxy.convert: the mesh written to path, a proxy in its place, named as the mesh was; the proxy (None where none
    was made). The file's mesh is then put at the origin (settle) and the proxy told to read it again: as proxy.convert
    leaves them, the file's mesh keeps its place as well as the proxy, and Modo's renderer, and its render cache the kit
    reads, drew the mesh away from where it stood (at its own origin; tools/probe_cl_links_layout.py). A proxy whose
    file holds its mesh at the origin is drawn where the proxy stands. standin: the library's stand-in (its name) the
    proxy is drawn as in the viewport (settle, show_as), or None."""
    lx, modo = _modo()
    scene = modo.Scene()
    name = mesh.name
    before = {item.id for item in scene.items('proxy')}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _only(mesh.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (mesh.id, path))
    made = [item for item in scene.items('proxy') if item.id not in before]
    if not made:
        return None
    proxy = made[0]
    # Made while the mesh still held its name, the proxy was given another ('Box (2)').
    if proxy.name != name:
        try:
            proxy.name = name
        except Exception:
            pass
    record = read_tag(proxy) or {'file': str(path)}
    settled = settle(Path(path), dict(record, file=str(path)), name, scene, standin)
    reload(proxy, path)
    show_as(proxy, name, standin if settled else None)
    return proxy


def show_as(proxy, name, standin):
    """The proxy drawn in the viewport as its stand-in (proxy.previewItem: '<name> Stand-in' in its file), or as its mesh
    where it has none; it renders its mesh (proxy.renderItem) either way."""
    lx, modo = _modo()
    from .standins import LABEL
    _only(proxy.id)
    lx.eval('!proxy.renderItem item:{%s} name:{%s}' % (proxy.id, name))
    lx.eval('!proxy.previewItem item:{%s} name:{%s}' % (proxy.id, name + LABEL if standin else name))


# The spellings of each link file (by its path, compared without case) Modo has loaded in this Modo session (spelled).
_LOADED = {}


def reload(proxy, path):
    """A proxy made to read its file as it is on disk now: pointed at a spelling of it Modo has not loaded in this session
    (spelled; the one it holds now counts as loaded). The panel shows the file's own path whatever the spelling."""
    lx, modo = _modo()
    key = os.path.normcase(os.path.abspath(str(path)))
    loaded = _LOADED.setdefault(key, set())
    held = proxy_file(proxy)
    if held:
        loaded.add(os.path.normcase(held))
    form = spelled(path, loaded)
    _only(proxy.id)
    lx.eval('!proxy.sceneFile item:{%s} filename:{%s}' % (proxy.id, form))
    loaded.add(os.path.normcase(form))
    return form


def _world_place(item):
    """An item's place in the world as position, rotation (radians, in the item's own rotation order) and scale: what an
    item at the top of another scene is given to stand where it stands."""
    import modo
    matrix = modo.Matrix4(item.channel('worldMatrix').get())
    scale = list(matrix.scale())
    position = list(matrix.position)
    turned = modo.Matrix4(matrix)
    for row in range(3):
        for column in range(3):
            turned.m[row][column] = matrix.m[row][column] / (scale[row] or 1.0)
    try:
        order = str(item.rotation.channel('order').get()) if item.rotation is not None else 'xyz'
    except Exception:
        order = 'xyz'
    order = order.lower() if len(order) == 3 and set(order.lower()) == set('xyz') else 'xyz'
    return position, list(turned.asEuler(order=order)), scale, order


def _place_at(item, place):
    """An item put where _world_place says (out of any parent), its rotation order as there."""
    lx, modo = _modo()
    position, rotation, scale, order = place
    if item.parent is not None:
        lx.eval('select.item {%s} set' % item.id)
        lx.eval('!item.parent {%s} {} 0 inPlace:0' % item.id)
    try:
        item.rotation.channel('order').set(order)
    except Exception:
        pass
    item.position.set(position)
    item.rotation.set(rotation)
    item.scale.set(scale)


def _at_origin(item):
    """An item of a link file put at the world's origin: out of any parent, no move, turn or scale of its own."""
    lx, modo = _modo()
    if item.parent is not None:
        lx.eval('select.item {%s} set' % item.id)
        lx.eval('!item.parent {%s} {} 0 inPlace:0' % item.id)
    for name, values in (('position', [0.0, 0.0, 0.0]), ('rotation', [0.0, 0.0, 0.0]), ('scale', [1.0, 1.0, 1.0])):
        try:
            held = getattr(item, name)
            if [round(v, 9) for v in held.get()] != values:
                held.set(values)
        except Exception:
            pass


def settle(path, record, name, main, standin=None, keep=False):
    """A link file's mesh put at the origin (_at_origin) and given its stand-in (place_standin; none where standin is
    None, unless keep, which leaves the one the file has), the file saved and closed, main made current again. False
    where the file has no mesh to stand for name."""
    lx, modo = _modo()
    with _unseen_scenes():
        lx.eval('!scene.open {%s} normal' % path)
        try:
            target = _file_mesh(modo.Scene(), record, name)
            if target is None:
                return False
            _at_origin(target)
            if standin or not keep:
                place_standin(target, name, standin)
            lx.eval('!scene.save')
            return True
        finally:
            if modo.Scene().filename and same_file(modo.Scene().filename, path):
                lx.eval('!scene.close')
            _back_to(main)


def _standin_items(scene):
    """The stand-ins in a link file (opened as scene): meshes carrying a stand-in's tag."""
    from .standins import TAG as STANDIN
    found = []
    for item in scene.items('mesh'):
        try:
            if item.readTag(STANDIN):
                found.append(item)
        except (LookupError, RuntimeError, AttributeError):
            continue
    return found


def place_standin(target, name, standin):
    """In a link file (the scene open now), the stand-in for its mesh target (standin: the library's name, or None for
    none): the one there taken out, the library's built anew as '<name> Stand-in', stretched to target's bounds (at the
    origin, as the file holds it). False where the library has no such stand-in."""
    lx, modo = _modo()
    from . import standins
    scene = modo.Scene()
    for old in _standin_items(scene):
        lx.eval('select.item {%s} set' % old.id)
        lx.eval('!item.delete')
    entry = standins.find(standin) if standin else None
    if entry is None:
        return False
    low, high = target.geometry.boundingBox
    points, faces = standins.read(entry['file'])
    placed = standins.fitted(points, low, high)
    lx.eval('item.create mesh {%s}' % (name + standins.LABEL))
    made = [item for item in scene.items('mesh') if item.name == name + standins.LABEL]
    if not made:
        return False
    mesh = made[-1]
    with mesh.geometry as geometry:
        corners = [geometry.vertices.new(point) for point in placed]
        for face in faces:
            geometry.polygons.new([corners[i] for i in face])
    mesh.setTag(standins.TAG, entry['name'])
    return True


SHADER_TYPES = ('mask', 'advancedMaterial', 'imageMap', 'constant', 'shaderFolder', 'shader')


def _shaders():
    """The ids of the Shader Tree's items: what sits under the render item."""
    lx, modo = _modo()
    scene = modo.Scene()
    found = set()
    for item in scene.items():
        parent = item.parent
        while parent is not None:
            if parent.type == 'polyRender':
                found.add(item.id)
                break
            parent = parent.parent
    return found


def _material_tags(mesh):
    """The material tags a mesh's polygons carry."""
    import lx
    try:
        held = lx.object.Mesh(mesh.geometry.internalMesh)
        kind = lx.symbol.i_PTAG_MATR
        return {held.PTagByIndex(kind, index) for index in range(held.PTagCount(kind))}
    except Exception:
        try:
            return {polygon.materialTag for polygon in mesh.geometry.polygons}
        except Exception:
            return set()


def _masked_tags(ids):
    """The material tags the masks among ids shade."""
    lx, modo = _modo()
    found = set()
    for ident in ids:
        item = _item(ident)
        if item is None or item.type != 'mask':
            continue
        try:
            if str(item.channel('ptyp').get()) in ('Material', 'material', ''):
                found.add(str(item.channel('ptag').get()))
        except Exception:
            continue
    return found


def _restore(proxy):
    """proxy.restore: the proxy made a mesh again from its file as it is on disk; the mesh. What the restore brought
    into the Shader Tree again is taken out where the scene's own masks already shade every material of the mesh, so
    that each Edit in Scene does not add a copy of the mesh's materials."""
    lx, modo = _modo()
    scene = modo.Scene()
    shaders = _shaders()
    meshes = {item.id for item in scene.items('mesh')}
    _only(proxy.id)
    lx.eval('!proxy.restore item:{%s}' % proxy.id)
    made = [item for item in scene.items('mesh') if item.id not in meshes]
    # A stand-in the restore brought along is the file's, for the proxy's viewport alone: let go of.
    from .standins import TAG as STANDIN
    for item in list(made):
        try:
            if item.readTag(STANDIN):
                made.remove(item)
                _only(item.id)
                lx.eval('!item.delete')
        except (LookupError, RuntimeError, AttributeError):
            continue
    mesh = made[0] if made else None
    added = _shaders() - shaders
    if mesh is not None and added and _material_tags(mesh) <= (_masked_tags(shaders) | {'Default', ''}):
        tops = [ident for ident in added if (_item(ident).parent is None or _item(ident).parent.id not in added)]
        for ident in tops:
            if _item(ident) is not None:
                _only(ident)
                lx.eval('!item.delete')
    return mesh


def _file_mesh(scene, record, name):
    """The mesh of a link file (opened as scene) that stands for the mesh named name: the one tagged with the same
    file, else the one of that name, else the only one with polygons; None where it cannot be told."""
    # Not its stand-in (place_standin), which the file holds beside it.
    aside = {item.id for item in _standin_items(scene)}
    meshes = [m for m in scene.items('mesh') if m.id not in aside]
    tagged = [m for m in meshes if (read_tag(m) or {}).get('file') and same_file(read_tag(m)['file'], record['file'])]
    if len(tagged) == 1:
        return tagged[0]
    named = [m for m in meshes if m.name == name]
    if len(named) == 1:
        return named[0]
    full = [m for m in meshes if m.geometry.numPolygons]
    return full[0] if len(full) == 1 else None


@contextmanager
def _unseen_scenes():
    """A link file opened and closed (settle, write_geometry) left unseen by the preview windows: a scene made and
    another closed tells a preview the scene it rendered was closed (panel._poll), and it cleared its picture and
    stopped the render begun after a Link (the Links GUI probe: MoonLightIPR 'The scene was closed' after Link), and
    asked for the whole scene to be read again (changes.full). What they had noted before is put back."""
    try:
        from .panel import live_panels
        held = [(p.changes, p.changes.closed, p.changes.created, p.changes.full) for p in live_panels()]
    except Exception:
        held = []
    try:
        yield
    finally:
        for changes, closed, created, full in held:
            try:
                changes.closed, changes.created, changes.full = closed, created, full
            except Exception:
                pass


def _scene_key(scene):
    """What tells one open scene from another (scene_watch.key): its scene object's address."""
    try:
        return getattr(scene, 'scene', scene).__peekobj__()
    except Exception:
        return None


def _back_to(main):
    """The scene main made current again, where closing another left a third one current (several scenes open)."""
    lx, modo = _modo()
    key = _scene_key(main)
    if key is None or _scene_key(modo.Scene()) == key:
        return
    try:
        count = int(lx.eval1('query sceneservice scene.N ?'))
        for index in range(count):
            lx.eval('scene.set %d' % index)
            if _scene_key(modo.Scene()) == key:
                return
    except Exception:
        pass


def write_geometry(mesh, record):
    """An Editing mesh written to its file while the scene stays as it is: its polygons copied (select.copy, which
    takes the selected ones; every polygon of it is selected for that and its own selection put back after), the file
    opened, its mesh's polygons replaced (select.paste) and its place set, saved, closed. False where it cannot be done
    so (no file, polygons hidden, no mesh in the file to stand for it): the caller writes it by proxy.convert."""
    lx, modo = _modo()
    path = Path(record['file'])
    if not path.is_file():
        return False
    geometry = mesh.geometry
    total = geometry.numPolygons
    try:
        chosen = [p.index for p in geometry.polygons.selected]
        points = [v.index for v in geometry.vertices.selected]
    except Exception:
        chosen, points = [], []
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('select.type polygon')
    lx.eval('select.drop polygon')
    lx.eval('select.all')
    if len(mesh.geometry.polygons.selected) != total:
        # Hidden polygons are not selected by select.all, and would be left out of the file.
        lx.eval('select.drop polygon')
        return False
    lx.eval('select.copy')
    lx.eval('select.drop polygon')
    # Pasted polygons keep where they stand in the world: the file's mesh is put where this one stands first, so they
    # come in at the same points of its own, and back at the origin after (_at_origin), which does not move them. Pasted
    # into the mesh at the origin, they came in moved by this one's place (the Links stand-ins probe: by its -2 in X).
    place = _world_place(mesh)
    main = modo.Scene()
    with _unseen_scenes():
        lx.eval('!scene.open {%s} normal' % path)
        try:
            held = modo.Scene()
            target = _file_mesh(held, record, mesh.name)
            if target is None:
                return False
            _place_at(target, place)
            lx.eval('select.drop item')
            lx.eval('select.item {%s} set' % target.id)
            lx.eval('select.type polygon')
            lx.eval('select.all')
            lx.eval('!delete')
            lx.eval('select.paste')
            lx.eval('select.drop polygon')
            lx.eval('select.type item')
            # The file holds the mesh's shape at the origin; where it stands is the proxy's (Done Editing gives it).
            _at_origin(target)
            # Its stand-in stretched to its bounds as they now are.
            if record.get('standin'):
                place_standin(target, mesh.name, record['standin'])
            lx.eval('!scene.save')
        finally:
            if modo.Scene().filename and same_file(modo.Scene().filename, path):
                lx.eval('!scene.close')
            _back_to(main)
    # Its own polygon and point selection put back.
    try:
        geometry = mesh.geometry
        if chosen:
            geometry.polygons.select([geometry.polygons[i] for i in chosen], replace=True)
        if points:
            geometry.vertices.select([geometry.vertices[i] for i in points], replace=True)
    except Exception:
        pass
    return True


_WRITING = [False]


def standin_for(name, choice):
    """The stand-in a mesh named name is linked with: choice the library's name of one, standins.AUTO (the library's
    by the name, standins.choose) or standins.NONE (or empty: none). Its name in the library, or None."""
    from . import standins
    if not choice or choice == standins.NONE:
        return None
    if choice == standins.AUTO:
        entry = standins.choose(name)
    else:
        entry = standins.find(choice)
    return entry['name'] if entry else None


def link(ids, folder, standin='auto'):
    """Each mesh written to its own file in folder and a proxy put in its place (Linked), drawn in the viewport as a
    stand-in from the Asset Library (standin: standin_for's choice; by the mesh's name unless said). The proxies' ids."""
    lx, modo = _modo()
    renamed, made, taken = {}, [], []
    with kept_selection(renamed):
        for ident in ids:
            mesh = _item(ident)
            if mesh is None or mesh.type != 'mesh':
                continue
            path = file_name(folder, mesh.name, taken)
            taken.append(path)
            mark = prints([mesh]).get(mesh.id)
            chosen = standin_for(mesh.name, standin)
            proxy = _convert(mesh, path, chosen)
            if proxy is None:
                continue
            write_tag(proxy, {'file': str(path), 'stamp': stamp(path), 'print': mark, 'standin': chosen})
            renamed[ident] = proxy.id
            made.append(proxy.id)
    return made


def set_standin(ids, choice):
    """Each linked mesh drawn as another stand-in (standin_for's choice; none for NONE): its file given it, the proxy
    reading the file again. A mesh being edited takes it when it is made a proxy again. The ids changed."""
    lx, modo = _modo()
    renamed, changed = {}, []
    with kept_selection(renamed):
        for ident in ids:
            item = _item(ident)
            record = read_tag(item) if item is not None else None
            if item is None or record is None:
                continue
            chosen = standin_for(item.name, choice)
            if item.type == 'proxy':
                path = os.path.normpath(proxy_file(item)) or record['file']
                if not settle(Path(path), dict(record, file=path), item.name, modo.Scene(), chosen):
                    continue
                reload(item, path)
                show_as(item, item.name, chosen)
                record.update(file=path, stamp=stamp(path))
            record['standin'] = chosen
            write_tag(item, record)
            changed.append(item.id)
    return changed


def edit(ids):
    """Each proxy brought back into the scene as a mesh from its file as it is now, still tied to it (Editing). The
    meshes' ids."""
    renamed, made = {}, []
    with kept_selection(renamed):
        for ident in ids:
            proxy = _item(ident)
            if proxy is None or proxy.type != 'proxy':
                continue
            path = proxy_file(proxy)
            record = dict(read_tag(proxy) or {}, file=path)
            mesh = _restore(proxy)
            if mesh is None:
                continue
            record.update(stamp=stamp(path), print=prints([mesh]).get(mesh.id))
            write_tag(mesh, record)
            renamed[ident] = mesh.id
            made.append(mesh.id)
    return made


def update(ids, only_changed=False):
    """Each Editing mesh written to its file, where only_changed only those whose status needs it; it stays editable.
    A Linked proxy among ids is read again from its file as it is on disk (reload), where it changed there. The ids
    written or read again (a mesh written by proxy.convert and restored has a new one)."""
    lx, modo = _modo()
    renamed, done = {}, []
    _WRITING[0] = True
    try:
        with kept_selection(renamed):
            for ident in ids:
                mesh = _item(ident)
                if mesh is not None and mesh.type == 'proxy':
                    path = os.path.normpath(proxy_file(mesh))
                    record = dict(read_tag(mesh) or {}, file=path)
                    if stamp(path) is not None and (not only_changed or status(LINKED, record, stamp(path)) == CHANGED):
                        reload(mesh, path)
                        record.update(stamp=stamp(path))
                        write_tag(mesh, record)
                        done.append(mesh.id)
                    continue
                record = read_tag(mesh) if mesh is not None and mesh.type == 'mesh' else None
                if record is None:
                    continue
                if only_changed:
                    mark = prints([mesh]).get(mesh.id)
                    if status(EDITING, record, stamp(record['file']), mark) not in NEEDS_WRITE:
                        continue
                if not write_geometry(mesh, record):
                    proxy = _convert(mesh, record['file'], record.get('standin'))
                    mesh = _restore(proxy) if proxy is not None else None
                    if mesh is None:
                        continue
                    renamed[ident] = mesh.id
                record.update(stamp=stamp(record['file']), print=prints([mesh]).get(mesh.id))
                write_tag(mesh, record)
                done.append(mesh.id)
    finally:
        _WRITING[0] = False
    return done


def done(ids):
    """Each Editing mesh written to its file and made a proxy again (Linked). The proxies' ids."""
    renamed, made = {}, []
    with kept_selection(renamed):
        for ident in ids:
            mesh = _item(ident)
            record = read_tag(mesh) if mesh is not None and mesh.type == 'mesh' else None
            if record is None:
                continue
            mark = prints([mesh]).get(mesh.id)
            proxy = _convert(mesh, record['file'], record.get('standin'))
            if proxy is None:
                continue
            record.update(stamp=stamp(record['file']), print=mark)
            write_tag(proxy, record)
            renamed[ident] = proxy.id
            made.append(proxy.id)
    return made


def relink(ident, path):
    """A proxy pointed at another file (proxy.sceneFile), or an Editing mesh tied to another (written there at the next
    write)."""
    lx, modo = _modo()
    item = _item(ident)
    if item is None:
        return False
    record = dict(read_tag(item) or {}, file=os.path.normpath(str(path)), stamp=stamp(path))
    renamed = {}
    with kept_selection(renamed):
        if item.type == 'proxy':
            # By a spelling Modo has not loaded (reload): the file may have been another proxy's earlier on.
            reload(item, record['file'])
    write_tag(item, record)
    return True


def embed(ids):
    """Each proxy made a mesh of the scene again and each Editing mesh untied from its file (Embedded); the files are
    left on disk. The meshes' ids."""
    renamed, made = {}, []
    with kept_selection(renamed):
        for ident in ids:
            item = _item(ident)
            if item is None:
                continue
            if item.type == 'proxy':
                mesh = _restore(item)
                if mesh is None:
                    continue
                renamed[ident] = mesh.id
                item = mesh
            if item.type == 'mesh':
                write_tag(item, None)
                made.append(item.id)
    return made


def select(ids):
    lx, modo = _modo()
    lx.eval('select.drop item')
    for ident in ids:
        if _item(ident) is not None:
            lx.eval('select.item {%s} add' % ident)


def reveal(path):
    """The file shown in Explorer, selected; its folder where it is missing."""
    import subprocess
    path = Path(path)
    if path.is_file():
        subprocess.Popen(['explorer', '/select,', str(path)])
    elif path.parent.is_dir():
        os.startfile(str(path.parent))


# ---- The panel's actions, as one command each. ---------------------------------------------------------------------

# What moonray.links.act does. Modo lets a script change an item (a tag, a channel) only inside a command: from a
# button's click (a Qt event) the link record could not be written ('bad result'). Run as a command, each action is
# also one step to undo.
ACTIONS = ('link', 'edit', 'update', 'done', 'relink', 'embed', 'standin', 'saved')
LAST = {'action': None, 'result': None, 'error': None}


def act(action, ids='', path=''):
    """moonray.links.act's work: ids as JSON; path the folder (link: or JSON {"folder", "standin"}), the file (relink) or
    the stand-in (standin: a library name, 'auto' or 'none'). What it did is in LAST."""
    LAST.update(action=action, result=None, error=None)
    try:
        chosen = json.loads(ids) if ids else []
        if action == 'link':
            held = json.loads(path) if str(path).lstrip().startswith('{') else {'folder': path}
            LAST['result'] = link(chosen, Path(held['folder']), held.get('standin', 'auto'))
        elif action == 'standin':
            LAST['result'] = set_standin(chosen, path or 'none')
        elif action == 'edit':
            LAST['result'] = edit(chosen)
        elif action == 'update':
            LAST['result'] = update(chosen)
        elif action == 'done':
            LAST['result'] = done(chosen)
        elif action == 'relink':
            LAST['result'] = [ident for ident in chosen[:1] if relink(ident, path)]
        elif action == 'embed':
            LAST['result'] = embed(chosen)
        elif action == 'saved':
            LAST['result'] = update(waiting(), only_changed=True)
        else:
            raise ValueError('No such Links action: %s' % action)
    except Exception as exc:
        LAST['error'] = '%s: %s' % (type(exc).__name__, exc)
        raise
    return LAST['result']


def run(action, ids=(), path=''):
    """An action run as moonray.links.act (from the panel, or the save hook); what it did (LAST's result). Raises with
    what went wrong."""
    lx, modo = _modo()
    LAST.update(action=action, result=None, error=None)
    try:
        lx.eval('moonray.links.act {%s} {%s} {%s}' % (action, json.dumps(list(ids)), str(path or '')))
    except Exception as exc:
        raise RuntimeError(LAST['error'] or str(exc))
    if LAST['error']:
        raise RuntimeError(LAST['error'])
    return LAST['result']


def waiting():
    """The ids of the Editing meshes of the scene open now whose status needs a write (NEEDS_WRITE)."""
    lx, modo = _modo()
    meshes = [item for item in modo.Scene().items('mesh') if read_tag(item) is not None]
    if not meshes:
        return []
    marks = prints(meshes)
    return [item.id for item in meshes
            if status(EDITING, read_tag(item), stamp(read_tag(item)['file']), marks.get(item.id)) in NEEDS_WRITE]


# ---- Saving the scene writes the Editing meshes that changed. -----------------------------------------------------

LISTENERS = []      # called after a save's writes, with the ids written (the panel refreshes)
_SAVE = {}


def after_save():
    """Every Editing mesh of the scene open now whose status needs a write, written (moonray.links.act saved). Looked
    at first, so that a save with nothing to write leaves no step to undo."""
    if _WRITING[0]:
        return []
    try:
        written = run('saved') if waiting() else []
    except Exception as exc:
        written = []
        try:
            import lx
            lx.out('MoonRay Links: the meshes being edited were not written to their files: %s' % exc)
        except Exception:
            pass
    for listener in list(LISTENERS):
        try:
            listener(written)
        except Exception:
            pass
    return written


def watch_saves():
    """Saving a scene (scene.save, scene.saveAs and the like) writes its Editing meshes that changed, once the save is
    done (after_save, on Qt's next turn: commands are not run inside another's events). Once; quietly where Modo's
    command events cannot be listened to."""
    if 'com' in _SAVE:
        return True
    try:
        import lx
        import lxifc
    except ImportError:
        return False

    class Listener(lxifc.CmdSysListener):
        def cmdsysevent_ExecutePost(self, cmd, isSandboxed, isPostCmd):
            if _WRITING[0] or isSandboxed:
                return
            try:
                name = lx.object.Command(cmd).Name()
            except Exception:
                return
            if not name.startswith('scene.save'):
                return
            try:
                from PySide2 import QtCore
                QtCore.QTimer.singleShot(0, after_save)
            except Exception:
                pass
    try:
        held = Listener()
        from . import quit_release
        _SAVE.update(listener=held, com=quit_release.listen(held))
    except Exception:
        return False
    return True
