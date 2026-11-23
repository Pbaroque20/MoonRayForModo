"""Seas on Modo's own meshes in the viewport: a flat mesh (a plane of any size, facing any way) wearing a material whose
MoonShine graph displaces it by an Ocean node shows points where that sea puts its surface, as an Ocean Plane does
(ocean_viewport), on its own faces and through its own UVs, as the renders lay the sea on it (nodes.expand_ocean,
ocean.fitted). An Ocean Plane whose material tag names such a material shows that material's sea (draw_level).

A mesh is drawn by the kit's package on it (PACKAGE, lxserv/moonray_entities.py), which is added to the meshes a sea's
material is on as that material's settings are written (written, from properties.write) and as a scene is opened
(attach). Only a flat mesh whose UVs are laid flat on it is drawn: on any other shape the sea would follow the shape's
own frame at every point, which a few points over a plane do not show."""
import math
import time as clock

PACKAGE = 'moonray.oceanPoints'
# How long the scene's seas, once found, serve the drawing before they are looked for again (seconds).
REFRESH = 1.0
# Points across a tile of the sea next to the eye, on a mesh.
ACROSS_TILE = 40
# A mesh of more polygons than this is not read for its sea.
MOST_POLYGONS = 500000

_seas = {'at': None, 'value': None}
_read = {}        # mesh identity -> {'signature', 'mesh' (mesh_reader.Mesh)}
_surfaces = {}    # surface name -> {'key', 'facts', 'code', 'tag', 'mesh'}
_levels = {}      # level name -> (height, tile)
_attached = {}    # material tag -> (meshes in the scene, when): what written() last looked through
_drawn = set()    # the meshes whose seas were drawn (their identities), for redraw()
# For probes: the last fault met while drawing a mesh's sea (never raised), and each mesh's last drawing.
FAULTS = {}
LAST = {}
# And how often Modo asked the package to draw (vitm), how often a mesh's seas were looked for (draw), and what the last
# look found: the mesh's material tags, the scene's seas, the seas it wears.
CALLS = {'vitm': 0, 'draw': 0, 'tags': None, 'seas': None, 'worn': None}


def scene_seas(fresh=False):
    """The scene's seas, as the renders take its Shader Tree (the topmost material of a tag wins): ({material tag:
    {'material': its identity, 'params': its Ocean node's settings, 'factor': its Vector Displacement's Factor}},
    every material tag). Found again at most every REFRESH seconds, unless fresh."""
    now = clock.monotonic()
    if not fresh and _seas['value'] is not None and now - _seas['at'] < REFRESH:
        return _seas['value']
    import modo
    from . import properties
    from .host import channel
    from .layers import material_tag, ordered
    from .material_override import effective
    from .materials import active
    from .ocean_viewport import sea_of
    seas, tags = {}, set()
    for material in reversed(ordered(modo.Scene().renderItem)):
        try:
            if not properties.is_material(material) or not active(material) or not channel(material, 'enable', 1):
                continue
            tag = material_tag(material)
        except (ValueError, LookupError, RuntimeError, AttributeError, TypeError):
            continue
        if tag is None:
            continue
        tags.add(tag)
        found = sea_of(effective(properties.read(material)).get('node_graph'))
        if found:
            seas[tag] = dict(found, material=material.id)
        else:
            seas.pop(tag, None)
    _seas.update(at=now, value=(seas, tags))
    return seas, tags


def forget_seas():
    """The scene's seas looked for again at the next drawing."""
    _seas.update(at=None, value=None)


def worn(tags, every):
    """The materials a mesh's material tags (tags) put on it, as face_tags.worn takes them: a tag no material has is the
    base material's ('')."""
    return {tag if tag in every else '' for tag in tags}


def mesh_tags(mesh):
    """The material tags a mesh's polygons carry (a modo.Mesh), as Modo lists them."""
    import lx
    inner = mesh.geometry.internalMesh
    return {inner.PTagByIndex(lx.symbol.i_PTAG_MATR, index) for index in range(inner.PTagCount(lx.symbol.i_PTAG_MATR))}


def lacking(tags=None):
    """The meshes wearing one of the scene's seas (of those tags, or any) that do not carry the kit's package."""
    import modo
    seas, every = scene_seas(fresh=True)
    wanted = set(seas) if tags is None else set(seas) & set(tags)
    if not wanted:
        return []
    found = []
    for mesh in modo.Scene().items('mesh'):
        try:
            if not mesh.PackageTest(PACKAGE) and worn(mesh_tags(mesh), every) & wanted:
                found.append(mesh)
        except (LookupError, RuntimeError, AttributeError, TypeError):
            continue
    return found


def attach(tags=None):
    """The kit's package added to each mesh wearing one of the scene's seas (of those tags, or any) that has none, so
    that its sea is drawn from then on. Call inside a command (moonray.ocean.attachPoints). (How many meshes it was
    added to, how many it could not be added to.)"""
    added = missed = 0
    for mesh in lacking(tags):
        try:
            mesh.PackageAdd(PACKAGE)
            added += 1
        except (LookupError, RuntimeError, AttributeError, TypeError):
            missed += 1
    return added, missed


def written(item, values):
    """A material's settings written (properties.write, in the same step): where its graph displaces by an Ocean node,
    the meshes it is on are given the package (attach). A graph edited step by step looks through the scene's meshes
    again only once they are more or fewer, or two seconds on."""
    from .material_override import effective
    from .ocean_viewport import sea_of
    if not sea_of(effective(values).get('node_graph')):
        return
    forget_seas()
    redraw()
    try:
        from .layers import material_tag
        tag = material_tag(item)
    except (ValueError, LookupError, RuntimeError, AttributeError):
        return
    if tag is None:
        return
    import modo
    try:
        count = len(modo.Scene().items('mesh'))
    except (LookupError, RuntimeError):
        return
    held = _attached.get(tag)
    now = clock.monotonic()
    if held and held[0] == count and now - held[1] < 2.0:
        return
    _attached[tag] = (count, now)
    if not lacking([tag]):
        return
    # Through the kit's command (moonray.ocean.attachPoints), within the graph editor's own as a part of its step: a
    # package a script added in a step of its own was kept but never drawn (Modo 16.1, 2026-11-22). Where no command can
    # run now, just after.
    import lx
    try:
        lx.eval('moonray.ocean.attachPoints')
    except Exception:
        try:
            from PySide2 import QtCore
            QtCore.QTimer.singleShot(0, lambda: lx.eval('moonray.ocean.attachPoints'))
        except Exception:
            pass


def redraw():
    """The meshes whose seas were drawn, drawn again in every 3D view: Modo keeps a mesh's drawing (its GL draw cache)
    until the mesh itself changes, so with the timeline moved or a sea's settings changed its points stayed as they were
    (Modo 16.1, 2026-11-22). Called as the timeline moves (lxserv/moonray_entities.py) and as a sea's material is
    written. How many meshes."""
    if not _drawn:
        return 0
    import lx
    import modo
    try:
        service = lx.service.View3Dport()
        views = [lx.object.View3D(service.View(index)) for index in range(service.Count())]
        scene = modo.Scene()
    except (LookupError, RuntimeError, AttributeError, TypeError):
        return 0
    count = 0
    for identity in list(_drawn):
        try:
            item = scene.item(identity)
        except LookupError:
            _drawn.discard(identity)
            continue
        for view in views:
            try:
                view.InvalidateSurface(item)
            except (LookupError, RuntimeError, AttributeError, TypeError):
                pass
        count += 1
    CALLS['redraw'] = CALLS.get('redraw', 0) + 1
    return count


def _signature(inner):
    """What tells that a mesh's points have changed (an lx.object.Mesh): how many points and polygons it has, and where
    a few of its points stand."""
    import lx
    points, polygons = inner.PointCount(), inner.PolygonCount()
    places = []
    try:
        point = lx.object.Point(inner.PointAccessor())
        for index in range(0, points, max(1, points // 8)):
            point.SelectByIndex(index)
            places.append(tuple(round(float(v), 9) for v in point.Pos()))
    except (LookupError, RuntimeError, AttributeError, TypeError):
        pass
    return points, polygons, tuple(places)


def _faces_wanted(read, tag, every, index):
    """One byte a face of a mesh read whole: 1 where the face wears tag's material and has a value of the UV map."""
    from_tag = bytes(1 if (name if name in every else '') == tag else 0 for name in read.tags)
    flags = bytes(from_tag[t] if 0 <= t < len(from_tag) else 0 for t in read.tag_indices)
    valid = read.uv_valid[index]
    return bytes(a & b for a, b in zip(flags, valid))


def surface(identity, inner, tag, every, matrix, name):
    """The mesh (identity, its lx.object.Mesh inner, placed by matrix) kept as a surface under name for the faces
    wearing tag's material: the facts ocean_viewport.mesh_surface gives, or None where it cannot be drawn on (not flat,
    UVs not laid flat, too many polygons). Read again only as the mesh, its place or its materials change."""
    from . import mesh_reader, ocean_viewport
    signature = _signature(inner)
    held = _read.get(identity)
    if held is None or held['signature'] != signature:
        if inner.PolygonCount() > MOST_POLYGONS:
            return None
        read = mesh_reader.read(inner)
        if read is None:
            return None
        held = _read[identity] = {'signature': signature, 'mesh': read}
    key = (signature, tuple(round(float(v), 9) for v in matrix), tag, tuple(sorted(every)) if tag == '' else None)
    made = _surfaces.get(name)
    if made is not None and made['key'] == key:
        return made['facts']
    read = held['mesh']
    index = read.uv_map(None)
    code, facts = 3, None
    if index is not None:
        code, facts = ocean_viewport.mesh_surface(name, read.vertices.data, read.counts, read.indices, read.uv_values[index].data,
                                                  _faces_wanted(read, tag, every, index), matrix)
    _surfaces[name] = {'key': key, 'facts': facts, 'code': code, 'tag': tag, 'mesh': identity}
    return facts


def spans(tag):
    """The metres a step of U and of V spans on the meshes a material is on, weighted by their area, as ocean.fitted
    takes them for Fit to Mesh: of the meshes drawn so far. None where none is."""
    u = v = area = 0.0
    for made in _surfaces.values():
        facts = made.get('facts')
        if made.get('tag') != tag or not facts:
            continue
        u += facts['metres'][0] * facts['area']
        v += facts['metres'][1] * facts['area']
        area += facts['area']
    return (u / area, v / area) if area > 0 else None


def draw(item, stroke, matrix, time):
    """Draws the seas a mesh wears on a viewport's stroke object (its package's drawing; item an lx.object.Item, matrix
    its world matrix, time the timeline's): Spacing a fortieth of a tile next to the eye, over the whole mesh. How many
    points were drawn."""
    import modo
    from . import native, ocean_viewport
    CALLS['draw'] += 1
    if not native.ocean():
        return 0
    seas, every = scene_seas()
    CALLS['seas'] = sorted(seas)
    if not seas:
        return 0
    mesh = modo.Mesh(item)
    identity = mesh.id
    tags = mesh_tags(mesh)
    wears = sorted(worn(tags, every) & set(seas))
    CALLS.update(tags=sorted(tags), worn=wears)
    if wears:
        _drawn.add(identity)
    drawn = 0
    for tag in wears:
        name = 'mesh:%s|%s' % (identity, tag)
        facts = surface(identity, mesh.geometry.internalMesh, tag, every, matrix, name)
        if not facts:
            LAST[name] = {'count': 0, 'why': ocean_viewport.NOT_KEPT.get(_surfaces.get(name, {}).get('code'), 'not read')}
            continue
        sea = seas[tag]
        try:
            repeat_u, repeat_v, scale = ocean_viewport.laid(sea['params'], spans(tag))
        except (ValueError, TypeError, KeyError):
            continue
        tile = min(facts['metres'][0] / max(repeat_u, 1e-9), facts['metres'][1] / max(repeat_v, 1e-9))
        spacing = max(tile / ACROSS_TILE, 1e-4)
        distance = max(math.hypot(*facts['extent']), spacing)
        count = ocean_viewport.draw_on(stroke, 'material:' + sea['material'], name, sea['params'], time, (repeat_u, repeat_v),
                                       sea['factor'] * scale, spacing, distance)
        LAST[name] = {'count': count, 'tag': tag, 'repeat': (repeat_u, repeat_v), 'scale': scale, 'spacing': spacing,
                      'distance': distance, 'facts': facts}
        drawn += count or 0
    return drawn


def draw_level(stroke, identity, tag, height, tile, spacing, distance, time):
    """An Ocean Plane whose material tag (tag) names a Modo material: that material's sea on its level (at height, its
    UVs the world's over tile), as the renders lay it (ocean_plane.apply). How many points were drawn; None where no
    material has the tag (the renders give the plane its own sea then, and so is it drawn), 0 where its material makes
    no sea."""
    from . import ocean_viewport
    seas, every = scene_seas()
    if tag not in every:
        return None
    sea = seas.get(tag)
    if sea is None:
        return 0
    name = 'level:' + identity
    if _levels.get(name) != (float(height), float(tile)):
        if not ocean_viewport.level(name, height, tile):
            return 0
        _levels[name] = (float(height), float(tile))
    try:
        repeat_u, repeat_v, scale = ocean_viewport.laid(sea['params'], spans(tag))
    except (ValueError, TypeError, KeyError):
        return 0
    return ocean_viewport.draw_on(stroke, 'material:' + sea['material'], name, sea['params'], time, (repeat_u, repeat_v),
                                  sea['factor'] * scale, spacing, distance) or 0
